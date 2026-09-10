import assert from "node:assert/strict";
import test from "node:test";
import { App } from "aws-cdk-lib";
import { Template, Match } from "aws-cdk-lib/assertions";
import { PantherCostAnomaliesStack, anomalyThreshold } from "../lib/panther-cost-anomalies-stack";
import { PantherFoundationStack } from "../lib/panther-foundation-stack";

function foundation(overrides = {}) {
  return new PantherFoundationStack(new App(), "Test", {
    env: { account: "123456789012", region: "us-west-2" },
    applicationOrigin: "https://panther.place", monthlyBudgetUsd: 10,
    anomalyMonitorArn: "arn:aws:ce::123456789012:anomalymonitor/test", ...overrides,
  });
}

test("layered account-wide budgets retain logical identity and cannot lose recipients", () => {
  const template = Template.fromStack(foundation()).toJSON();
  const actual = template.Resources.MonthlyCostBudget.Properties;
  assert.equal(actual.Budget.BudgetName, undefined); // permit safe create-before-delete replacement
  assert.deepEqual(actual.NotificationsWithSubscribers.map((n: any) => [n.Notification.ThresholdType, n.Notification.Threshold]),
    [["ABSOLUTE_VALUE", 1], ["PERCENTAGE", 25], ["PERCENTAGE", 50], ["PERCENTAGE", 80], ["PERCENTAGE", 100]]);
  const forecast = template.Resources.ForecastCostBudget.Properties;
  assert.equal(forecast.Budget.BudgetName, undefined);
  assert.deepEqual(forecast.NotificationsWithSubscribers.map((n: any) => n.Notification), [80, 100].map(value => ({
    ComparisonOperator: "GREATER_THAN", NotificationType: "FORECASTED", ThresholdType: "PERCENTAGE", Threshold: value,
  })));
  for (const budget of [actual, forecast]) {
    assert.equal(budget.Budget.CostTypes.IncludeCredit, false);
    assert.equal(budget.Budget.CostTypes.IncludeRefund, false);
    assert.equal(budget.Budget.CostFilters, undefined);
    assert.equal(budget.NotificationsWithSubscribers.length <= 5, true);
    for (const n of budget.NotificationsWithSubscribers) assert.deepEqual(n.Subscribers,
      [{ Address: { Ref: "BudgetEmail" }, SubscriptionType: "EMAIL" }]);
  }
  assert.equal(template.Parameters.BudgetEmail.Default, undefined);
  assert.ok(template.Parameters.BudgetEmail.AllowedPattern);
});

test("immediate anomaly delivery is TLS-only and account-scoped, without always-on compute", () => {
  const template = Template.fromStack(foundation());
  template.resourceCountIs("AWS::SNS::Topic", 1);
  template.hasResourceProperties("AWS::SNS::Subscription", { Protocol: "email", Endpoint: { Ref: "BudgetEmail" } });
  template.hasResourceProperties("AWS::SNS::TopicPolicy", { PolicyDocument: { Statement: Match.arrayWith([
    Match.objectLike({ Effect: "Deny", Condition: { Bool: { "aws:SecureTransport": "false" } } }),
    Match.objectLike({ Effect: "Allow", Principal: { Service: "costalerts.amazonaws.com" },
      Action: "sns:Publish", Condition: { StringEquals: { "aws:SourceAccount": "123456789012" } } }),
  ]) } });
  template.hasResourceProperties("AWS::CE::AnomalySubscription", { Frequency: "IMMEDIATE",
    ThresholdExpression: anomalyThreshold(1), Subscribers: [Match.objectLike({ Type: "SNS" })] });
  for (const type of ["AWS::Lambda::Function", "AWS::EC2::Instance", "AWS::EC2::NatGateway", "AWS::KMS::Key", "AWS::Budgets::BudgetsAction"]) template.resourceCountIs(type, 0);
});

test("service monitor and independent daily fallback are CDK owned and retained", () => {
  const template = Template.fromStack(new PantherCostAnomaliesStack(new App(), "Anomalies", { anomalyThresholdUsd: 1 }));
  template.hasResourceProperties("AWS::CE::AnomalyMonitor", { MonitorType: "DIMENSIONAL", MonitorDimension: "SERVICE" });
  template.hasResourceProperties("AWS::CE::AnomalySubscription", { Frequency: "DAILY", ThresholdExpression: anomalyThreshold(1),
    Subscribers: [{ Type: "EMAIL", Address: { Ref: "BudgetEmail" } }] });
  for (const type of ["AWS::CE::AnomalyMonitor", "AWS::CE::AnomalySubscription"]) template.allResources(type, { DeletionPolicy: "Retain" });
});

test("invalid alert thresholds fail closed; valid customized thresholds are supported", () => {
  for (const overrides of [{ monthlyBudgetUsd: 0 }, { firstSpendUsd: NaN }, { actualBudgetPercentages: [] },
    { actualBudgetPercentages: [10, 20, 30, 40, 50] }, { forecastBudgetPercentages: [80, 80] },
    { forecastBudgetPercentages: [Infinity] }, { actualBudgetPercentages: [-1] }]) assert.throws(() => foundation(overrides));
  for (const value of [0, -1, NaN, Infinity, 1e11]) assert.throws(() => anomalyThreshold(value));
  const template = Template.fromStack(foundation({ monthlyBudgetUsd: 20, firstSpendUsd: 0.5,
    actualBudgetPercentages: [10, 50, 100], forecastBudgetPercentages: [90], anomalyThresholdUsd: 0.5 }));
  template.hasResourceProperties("AWS::CE::AnomalySubscription", { ThresholdExpression: anomalyThreshold(0.5) });
});
