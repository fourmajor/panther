# Panther cost alerts

Issue #9. These are delayed warnings, **not a hard spending cap**. No automatic shutdown,
budget actions, paid reports, polling Lambda, provisioned database, NAT, or EC2 is created.

## Layers and cost

| Layer | Default | Delivery |
| --- | --- | --- |
| Actual account cost | Above $1, then 25/50/80/100% of $10/month | Direct AWS Budgets email |
| Forecast account cost | Above 80/100% of $10/month | Direct AWS Budgets email |
| Service anomaly | Impact at least $1, no percentage hurdle | Immediate SNS email and independent daily email summary |

Actual and forecast budgets are separate because AWS allows five notifications per budget.
CloudFormation replaces budgets when notification definitions change. Budget names are therefore
AWS-assigned and exposed as `ActualCostBudgetName` / `ForecastCostBudgetName` stack outputs, allowing
create-before-delete updates without a fixed-name collision. The original `panther-monthly-cost`
budget is replaced during adoption; its configuration remains recoverable from repository history
and the private pre-deployment inventory. Budget-specific history may not transfer, but actual AWS
billing records are unchanged. Always resolve current names from outputs, not old bookmarks.
All services/regions are included. Credits/refunds do not offset the monitored cost, so promotional
credit cannot conceal consumption. Tax, support and upfront charges count: a domain purchase can
legitimately trigger alerts. The monitored amount is not necessarily the net amount payable.
The $1 anomaly threshold is a practical low default, not an AWS minimum; positive fractional
thresholds are supported. Anomalies represent unexpected impact, not total monthly cost.

Budgets notifications and Cost Anomaly Detection have no service charge. SNS is usage-priced,
with no always-on topic fee; tiny alert volumes normally fit its free allowance. Outside the
allowance, published SNS pricing lists $0.50/million requests and $2/100,000 email deliveries.
No customer-managed KMS key is added just for billing notifications: TLS is enforced and the
publisher is restricted to Cost Anomaly Detection acting for this account. Messages contain
billing information, never game assets or credentials.

AWS updates billing asynchronously. Anomaly detection runs approximately three times daily,
depends on billing data that can lag 24 hours, and needs at least ten days of service history.
Forecasts also need sufficient history and may be absent on a new account. "Immediate" means
after AWS detects an anomaly, not immediately after a charge. Budgets are a complementary layer,
including costs the anomaly service may not cover. Do not manufacture spend to test the detector.

## Deployment and adoption

All resources are native CDK/CloudFormation. `PantherCostAnomalies` owns the service monitor and
daily subscription; `PantherFoundation` owns budgets, the SNS topic/email subscription and immediate
anomaly subscription. Both stacks deploy in `us-west-2`. Cost Explorer is a global billing service;
its read APIs use the `us-east-1` endpoint, but its CloudFormation resources are supported in
`us-west-2`. No additional regional compute is required.

For a fresh account, first inspect whether AWS automatically created its single allowed SERVICE
monitor and daily subscription. Do not deploy a duplicate or delete these to get past a conflict.
The import-only app performs read-only discovery, checks the account, and synthesizes their exact
existing configuration (including tags). It stops on unexpected topology. Review the generated
template, keep it private, and use **CDK import**, never deploy the import-only app:

```sh
cd infra
export AWS_PROFILE=panther-sso-admin
export PANTHER_AWS_ACCOUNT_ID=ACCOUNT_ID
aws sts get-caller-identity
npx cdk diff PantherCostAnomalies --app 'node ops/import-cost-anomalies.cjs' --exclusively --method=template
```

Discovery prints identifiers shaped as `{ "ServiceMonitor": {"MonitorArn": "..."},
"DailyAnomalySubscription": {"SubscriptionArn": "..."} }`. Save that exact logical-ID mapping
as private JSON outside Git (no stack-name wrapper). The CLI can validate and save it with
`--resource-mapping-inline JSON --record-resource-mapping /private/path/mapping.json` without
performing an import. Import using:

```sh
npx cdk import PantherCostAnomalies --app 'node ops/import-cost-anomalies.cjs' --resource-mapping /private/path/mapping.json
```

Import preserves the resource identities, history and existing daily delivery. Then use the normal
app to rename them, lower the threshold and deploy the remaining resources. Never use import flags
to bypass unrelated changes. If no monitor exists, use the normal app to create the resources.
Existing unexpected monitors/subscriptions need an explicit reviewed adoption plan.

```sh
npm test
npx cdk diff PantherCostAnomalies PantherFoundation --context account=ACCOUNT_ID --context budgetEmail=OWNER_EMAIL
npx cdk deploy PantherCostAnomalies PantherFoundation --context account=ACCOUNT_ID --context budgetEmail=OWNER_EMAIL \
  --parameters PantherCostAnomalies:BudgetEmail=OWNER_EMAIL \
  --parameters PantherFoundation:BudgetEmail=OWNER_EMAIL
```

Verify the account and `us-west-2` in the diff before every deployment. Never include the owner
email, account inventories, import templates or receipt evidence in Git/public issue comments.
On later updates, CloudFormation retains `BudgetEmail`; omitting context cannot remove alerts.
The context value supplies an initial parameter default. To change recipients explicitly, pass
both parameter overrides above; changing only the default does not replace an existing value.

Configurable contexts: `monthlyBudgetUsd` (10), `firstSpendUsd` (1),
`actualBudgetPercentages` (`25,50,80,100`, max four), `forecastBudgetPercentages` (`80,100`, max five),
`anomalyThresholdUsd` (1). Positive, finite, distinct thresholds are validated at synthesis.

## Confirmation and safe verification

1. The owner clicks **Confirm subscription** in the SNS email for `panther-cost-alerts`.
   This is a recipient-consent action, not a resource configuration CDK can confirm for them.
   Direct Budgets emails are independent of this SNS confirmation; do not confuse the two.
2. Read `CostAlertTopicArn` from the foundation outputs. Use `sns list-subscriptions-by-topic`
   to verify the email endpoint and a real subscription ARN rather than `PendingConfirmation`.
3. Publish one clearly labeled **TEST** message to that exact CDK-managed topic, including the
   account ID, a unique test ID, and the billing investigation link. This runtime notification
   is a data-plane test, not a manual AWS resource mutation or a fabricated billing anomaly:

```sh
aws sns publish --region us-west-2 --topic-arn VERIFIED_TOPIC_ARN \
  --subject 'Panther COST ALERT TEST - no spending event' \
  --message 'TEST ONLY. Account: VERIFIED_ACCOUNT_ID. Test ID: UNIQUE_ID. No threshold was crossed by this test. Investigate real alerts at https://console.aws.amazon.com/costmanagement/home#/budgets'
```

4. Ask the recipient to confirm the matching test ID arrived. SNS accepting Publish proves only
   acceptance, not inbox delivery. Do not call the issue complete until confirmation is recorded.
5. Inspect `budgets describe-budget`, `describe-notifications-for-budget` and
   `describe-subscribers-for-notification` for both named budgets. Inspect `ce get-anomaly-monitors`
   and `get-anomaly-subscriptions` for the retained monitor, $1 daily fallback and immediate SNS path.
   Check CloudFormation drift after import and normal deployment.
6. Verify a native Budgets email when actual spend crosses a configured threshold (existing spend
   may already qualify) and native anomaly delivery when AWS produces an anomaly. There is no
   fake-anomaly insertion API. Record service-event validation as pending until observed, separately
   from configuration checks and the synthetic SNS delivery test. Never claim the synthetic test
   exercised AWS billing detection or direct Budgets email. New-account learning delays are expected.

AWS-authenticated operational checks are infrastructure administration, not game-asset operations.
Do not put billing administration permissions in the normal Panther game CLI.

## When an alert arrives

- Confirm the account, budget/anomaly name, actual or forecast amount, threshold and billing date.
  Native AWS messages include cost details and investigation links; immediate anomaly SNS messages
  include the account, impact, root causes and anomaly link. Don't put sensitive data in public issues.
- Open Billing/Cost Explorer from a trusted bookmark; group by service, region and usage type.
  Compare with known deployments/domain purchases. Determine whether the amount includes tax,
  prepaid/upfront fees, or consumption covered by credits before interpreting the net invoice.
- Stop an identified runaway local worker or authorized paid job if appropriate. Fix cloud
  configuration through reviewed CDK. Do not mass-delete assets or disable the entire account.
- Unexpected regions/services or suspected credential misuse require security investigation, not
  merely a larger budget. Document the cause and changes privately.
- For known-safe noise, change only the relevant threshold through CDK with a reason and explicit
  review/restore date. Keep the other layers active. Never unsubscribe or raise every threshold
  just to silence messages; subsequent charges may still be dangerous.

## A louder second channel

Email is the only configured recipient channel. Start by making Panther alerts VIP/high-priority
notifications in the owner's mail app (device-side setting; no AWS cost). This still shares email's
delivery failure modes. A genuinely independent channel remains an owner choice:

- **Slack/Teams push via Amazon Q Developer in chat applications:** AWS documents the SNS
  integration; requires an existing workspace, app authorization and a chosen private channel.
  Q chat integration itself has no additional charge; SNS/related service and workspace charges
  may apply. Define AWS configuration in CDK after choosing the channel; don't grant broad actions.
- **SMS:** per-message/carrier costs plus possible registration and recurring origination-number
  charges, with country-specific setup and sandbox restrictions. Requires an explicit destination,
  recipient consent and spending limit. Not enabled by default for this near-zero-idle account.
- **Dedicated push/paging provider:** potentially stronger escalation, but adds an account,
  integration credential and provider pricing/limits. Evaluate only if email/workspace push is
  insufficient; no provider signup or subscription is authorized here.

## Sources (checked September 2026)

- [Budgets pricing](https://aws.amazon.com/aws-cost-management/aws-budgets/pricing/)
- [Budgets notification limit](https://docs.aws.amazon.com/cli/latest/reference/budgets/create-budget.html)
- [Anomaly timing/history and account defaults](https://aws.amazon.com/aws-cost-management/aws-cost-anomaly-detection/faqs/)
- [Anomaly threshold expression](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-ce-anomalysubscription.html)
- [Anomaly SNS permissions and confirmation](https://docs.aws.amazon.com/cost-management/latest/userguide/ad-SNS.html)
- [SNS pricing](https://aws.amazon.com/sns/pricing/)
- [SMS setup](https://docs.aws.amazon.com/sns/latest/dg/sms_sending-overview.html)
- [Chat application pricing](https://aws.amazon.com/chatbot/pricing/)
- [CDK import](https://docs.aws.amazon.com/cdk/v2/guide/ref-cli-cmd-import.html)
