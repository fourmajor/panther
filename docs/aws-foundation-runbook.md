# Panther AWS Foundation Runbook

Status: Initial bootstrap

This runbook establishes the minimum AWS foundation needed to upload Panther assets. It creates no
game data and does not require automatic CI.

## 1. Create the dedicated account

Create a new dedicated AWS account through the AWS signup process. Use a unique account email,
enable root-user MFA immediately, and do not create root access keys.

Create an administrative CLI profile that uses short-lived credentials. The examples below call it
`panther-admin`; a different local name is fine.

Do not create IAM access keys. CDK creates a one-account AWS Organization, the Identity Center user,
and all permission sets and assignments. Because CloudFormation does not expose the Identity Store
user resource in `us-west-2`, CDK manages that user with an on-demand custom resource. Its Lambda
runs only when the stack creates, updates, or deletes the user.

Enabling the organization-level IAM Identity Center instance and activating IAM access to the
Billing console are access-related console exceptions. AWS does not expose those operations
through CloudFormation, CDK, or a supported public API.

## 2. Confirm the target

```bash
AWS_PROFILE=panther-admin aws sts get-caller-identity
```

Confirm that the returned account ID is the new Panther account before continuing.

The initial region is `us-west-2`. Override it at deployment time with
`PANTHER_AWS_REGION` or CDK context if needed.

## 3. Install and verify the CDK application

```bash
cd infra
npm ci
npm test
npm run synth -- --context account=ACCOUNT_ID
```

## 4. Bootstrap the account

```bash
AWS_PROFILE=panther-admin npx cdk bootstrap aws://ACCOUNT_ID/us-west-2
```

Replace `ACCOUNT_ID` with the verified Panther account ID.

## 5. Deploy the foundation and one-account Organization

```bash
AWS_PROFILE=panther-admin npm run deploy -- PantherFoundation \
  --context account=ACCOUNT_ID \
  --context budgetEmail=YOUR_EMAIL \
  --context monthlyBudgetUsd=10
```

Cost alerts now require an owner email parameter and retain it on later stack updates. The
`budgetEmail` context supplies its initial default; explicit parameter overrides change an existing
recipient. SNS anomaly email requires recipient confirmation; direct Budgets email is independent.
Before deploying to an existing account, follow [the cost-alert runbook](cost-alerts.md) to adopt
AWS's automatically created service monitor and daily subscription through CDK import. That runbook
also covers the new `PantherCostAnomalies` stack, all alert layers, delivery tests and limitations.

The account ID context is required. Requiring it prevents CDK from silently inheriting a different
default AWS profile.

## 6. Enable organization-level IAM Identity Center

In the AWS console, enable IAM Identity Center for the new Organization in `us-west-2`. This is a
documented manual exception because AWS does not provide a CloudFormation resource or public API
for enabling an organization instance.

Read the resulting instance identifiers with the CLI:

```bash
AWS_PROFILE=panther-admin aws sso-admin list-instances --region us-west-2
```

## 7. Deploy access

```bash
AWS_PROFILE=panther-admin npm run deploy -- PantherAccess \
  --context account=ACCOUNT_ID \
  --context administratorEmail=YOUR_EMAIL \
  --context identityCenterInstanceArn=INSTANCE_ARN \
  --context identityStoreId=IDENTITY_STORE_ID
```

CDK creates the first Identity Center user and two assigned permission sets:

- `PantherAdministrator` for infrastructure administration
- `PantherAssetUploader` for routine access to private game assets and read-only Cost Explorer

Use `PantherAssetUploader` for game-specific sessions. Reserve `PantherAdministrator` for CDK and
account-administration work. The temporary root profile is only for account bootstrap and recovery.

### Cost Explorer: role permissions and the separate console gate

`PantherAdministrator` already has Cost Explorer access through `AdministratorAccess`.
The uploader's CDK inline policy allows Cost Explorer Get/Describe/List operations, including
forecasts, saved-report viewing and preferences viewing, plus the account/billing-view context
needed by the console. It does not grant billing changes, paid-feature activation, report writes,
payment-method access or administration. Do not attach full Billing or AdministratorAccess to
the uploader to resolve a console error.

AWS separately requires the root user to activate IAM access to the Billing console. **A successful
Cost Explorer API request does not verify this console gate.** If both roles cannot use the console:

1. As root, open **Account → IAM user and role access to Billing information → Edit**.
2. Enable **Activate IAM Access** and save, then sign out of root.
3. Open fresh Identity Center console sessions for each role and verify Cost Explorer.

This is an unavoidable manual operation: AWS documents a root-only console setting and provides
no supported public API or CloudFormation resource for it, so CDK cannot set it (including via a
custom resource). Do not automate private console endpoints or create root keys. Owner completion
is tracked in [#85](https://github.com/fourmajor/panther/issues/85); do not assume it is enabled.
If already enabled, collect the exact console error and confirm the account/role rather than
adding redundant permissions to the administrator.

After a `PantherAccess` deployment, verify provisioning reached the existing IAM role using
`iam simulate-principal-policy` for allowed CE reads and denied CE/billing writes, then make one
small real Cost Explorer query with each CLI profile. API requests may have a small per-request
charge; do not poll them. Cost Explorer's global API uses `us-east-1`; this is an endpoint exception,
not a change to Panther's `us-west-2` infrastructure region. Deploy `PantherAccess` with
`--exclusively` and its existing Identity Center inputs; preview the diff and leave users and
assignments unchanged.

Sources: [AWS console activation](https://docs.aws.amazon.com/cost-management/latest/userguide/control-access-billing.html),
[Cost Management actions](https://docs.aws.amazon.com/cost-management/latest/userguide/billing-permissions-ref.html),
[console-only Billing operations](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/migrate-granularaccess-whatis.html).

## 8. Activate the Identity Center user

Users created through the Identity Store API do not have an initial password. AWS does not expose
the email-OTP setting through CloudFormation, CDK, or a public API, so enable it in the IAM Identity
Center console under **Settings**, **Authentication**, **Standard authentication**, **Configure**,
then **Send email OTP**.

Start a first sign-in from the AWS access portal. Follow the emailed verification link to set a
password and register MFA. Do not recreate the user in the console.

The foundation stack outputs the private and published bucket names. The same names are also stored
in these standard SSM parameters:

```text
/panther/foundation/private-asset-bucket
/panther/foundation/published-asset-bucket
```

## 9. Verify the private bucket

```bash
AWS_PROFILE=panther-uploader aws ssm get-parameter \
  --name /panther/foundation/private-asset-bucket \
  --query Parameter.Value \
  --output text
```

For normal game uploads, use the [Panther CLI](cli.md) with the user's Panther login. Agents must
read `panther instructions` first. The following is the historical administrative bootstrap path,
not the DM upload workflow:

```bash
AWS_PROFILE=panther-uploader aws s3 cp /path/to/portrait.png \
  s3://PRIVATE_BUCKET/games/GAME_ID/assets/ASSET_ID/original/portrait.png \
  --content-type image/png \
  --metadata asset-kind=portrait
```

The actual game ID, asset ID, portrait, and related metadata remain outside this repository.

## 10. Deploy the media explorer

Deploy the read-only media explorer with the short-lived administrator profile:

```bash
cd infra
AWS_PROFILE=panther-sso-admin npm run deploy -- PantherMediaExplorer \
  --context account=ACCOUNT_ID \
  --exclusively
```

Supply `PANTHER_IDENTITIES_FILE` as described in [private account configuration](private-account-configuration.md)
before CDK synthesis, diff or deployment. Its actual contents and production templates stay outside GitHub.

CDK creates the private web bucket, CloudFront distribution, Cognito user pool, configured users, protected
HTTP API, and on-demand Lambda functions. The default Cognito domain prefix is checked into
`infra/cdk.json`; change that context value if AWS reports that the globally named prefix is already
in use. `--exclusively` prevents this focused deployment from also updating the existing foundation
stack without its deployment-time budget email context.

Accounts are supplied through private deployment configuration, never a list in application source.
Their generated initial passwords are stored as standard SSM SecureString parameters under
`/panther/media-explorer/users/USERNAME/password`.
Adding an account does not add it to management/publisher allowlists, create a Player record, or
grant an application admin role. Formal member/admin roles are tracked in issue #83. Passwords
must be handed off privately, never committed, placed in an issue, or exposed in deployment output.

Retrieve the initial account passwords with administrative access:

```bash
AWS_PROFILE=panther-sso-admin aws ssm get-parameter \
  --region us-west-2 \
  --name /panther/media-explorer/users/USERNAME/password \
  --with-decryption \
  --query Parameter.Value \
  --output text
```

Password generation and user provisioning happen inside the CDK deployment. No password is passed
through CDK context, committed to Git, or returned in a CloudFormation output. CloudFormation cannot
natively set permanent Cognito passwords or create SSM SecureString values, so an on-demand custom
resource performs those two operations and owns their lifecycle.

Read the explorer URL from the deployment output or later with:

```bash
AWS_PROFILE=panther-sso-admin aws cloudformation describe-stacks \
  --region us-west-2 \
  --stack-name PantherMediaExplorer \
  --query "Stacks[0].Outputs[?OutputKey=='MediaExplorerUrl'].OutputValue | [0]" \
  --output text
```

## 11. Register and delegate the application domain

The selected domain is `panther.place`. Domain registration is the narrow manual API exception:
CloudFormation and CDK cannot register a domain. Register it for one year with auto-renewal and
privacy protection through the Route 53 Domains API. Do not put registrant contact details in Git,
CDK context, shell history, or CloudFormation.

Route 53 automatically creates a temporary hosted zone during registration. Panther deliberately
creates the authoritative zone with CDK so its lifecycle, tags, certificate validation, and records
remain reproducible. Bootstrap CDK in the stack's required region and deploy the domain stack:

```bash
cd infra
AWS_PROFILE=panther-sso-admin npx cdk bootstrap aws://ACCOUNT_ID/us-east-1 \
  --context account=ACCOUNT_ID

AWS_PROFILE=panther-sso-admin npx cdk deploy PantherDomain \
  --context account=ACCOUNT_ID \
  --exclusively
```

After the registration operation succeeds, read the four name servers from the `PantherDomain`
hosted zone and update the registered domain to use them. Updating registrar name servers is not
supported by CloudFormation or CDK:

```bash
AWS_PROFILE=panther-sso-admin aws route53 get-hosted-zone \
  --id CDK_HOSTED_ZONE_ID \
  --query DelegationSet.NameServers \
  --output text

AWS_PROFILE=panther-sso-admin aws route53domains update-domain-nameservers \
  --region us-east-1 \
  --domain-name panther.place \
  --nameservers Name=NAME_SERVER_1 Name=NAME_SERVER_2 Name=NAME_SERVER_3 Name=NAME_SERVER_4
```

Verify that the domain now reports the CDK zone's name servers. Then confirm that the registrar-created
zone contains only its default `NS` and `SOA` records and delete that unused zone so Panther pays for
only one hosted zone. This cleanup is part of the unavoidable registrar side effect, not an ongoing
infrastructure workflow.

Use ordinary CDK deployments for the certificate, application aliases, and every subsequent DNS
change. The domain stack is deliberately located in `us-east-1` because its CloudFront certificate
must live there. This is the documented exception to the default `us-west-2` region.

## Long-lived sign-in and session limits

Panther application sign-in and AWS administrative SSO are different systems. CDK configures both
Panther Cognito clients with 3,650-day rotating refresh tokens and one-hour API tokens. The web
app uses a first-party HttpOnly cookie through uncached `/auth/*` Lambda routes; the CLI uses the
OS credential store. Existing sign-ins do not gain extra lifetime retroactively. Update the CLI
before deploying rotation, then sign in once again to receive the new lifetime. Do not lengthen
individual bearer API tokens or disable revocation to avoid login prompts.

CDK configures both Panther AWS permission sets with the supported maximum `PT12H` role session.
Deploy `PantherAccess` with its existing `administratorEmail`, `identityCenterInstanceArn`, and
`identityStoreId` context values; inspect the diff to ensure that no user or assignment is recreated.
Use the modern AWS CLI `sso_session` profile configuration so role credentials and SSO tokens can
renew within the underlying interactive SSO session. Never create permanent access keys as a workaround.

The underlying Identity Center **user interactive session** supports a maximum of **90 days**.
This is a documented manual exception: AWS exposes that setting in the Identity Center console,
not in the public SSO Admin API/CloudFormation/CDK resource schema checked for this change.
`PutApplicationSessionConfiguration` controls background-session application status, not this duration.
Do not call private console endpoints or confuse permission-set lifetime with interactive-session lifetime.

The account owner must open IAM Identity Center in `us-west-2`, select **Settings → Authentication →
Session duration → Configure**, set **User interactive sessions** to **90 days** (129,600 minutes),
and save. This affects new sessions only. Then run `aws sso login --profile panther-sso-admin` again.
That fresh login is required before deploying a duration change when the current credentials are
already expired. The same requirement applies to the first long-lived Panther application login.

Long-lived sign-ins are intended for trusted personal devices. Signing out/revoking sessions,
disabling an account, clearing credentials/cookies, or browser retention limits can end them earlier.
There is no always-on session server, database, NAT gateway, or new fixed compute charge.

References: [Identity Center interactive sessions](https://docs.aws.amazon.com/singlesignon/latest/userguide/user-interactive-sessions.html),
[permission-set limits](https://docs.aws.amazon.com/singlesignon/latest/userguide/howtosessionduration.html),
[AWS CLI session prerequisites](https://docs.aws.amazon.com/singlesignon/latest/userguide/user-session-duration-prereqs-considerations.html).
