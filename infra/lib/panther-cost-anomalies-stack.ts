import { CfnParameter, RemovalPolicy, Stack, StackProps } from "aws-cdk-lib";
import * as ce from "aws-cdk-lib/aws-ce";
import { Construct } from "constructs";

export function anomalyThreshold(usd: number): string {
  if (!Number.isFinite(usd) || usd <= 0 || usd > 1e10) {
    throw new Error("anomalyThresholdUsd must be positive and at most 10000000000");
  }
  return JSON.stringify({ Dimensions: {
    Key: "ANOMALY_TOTAL_IMPACT_ABSOLUTE", Values: [String(usd)],
    MatchOptions: ["GREATER_THAN_OR_EQUAL"],
  } });
}

export function alertEmail(scope: Construct, defaultEmail?: string): string {
  return new CfnParameter(scope, "BudgetEmail", {
    type: "String", default: defaultEmail,
    allowedPattern: "[^\\s@]+@[^\\s@]+\\.[^\\s@]+",
    description: "Owner email for Panther cost alerts; retain the previous value on updates",
  }).valueAsString;
}

/** Separate stack allows native CDK import of AWS's automatically created resources. */
export class PantherCostAnomaliesStack extends Stack {
  readonly monitorArn: string;

  constructor(scope: Construct, id: string, props: StackProps & {
    budgetEmail?: string; anomalyThresholdUsd: number;
  }) {
    super(scope, id, props);
    const email = alertEmail(this, props.budgetEmail);
    const monitor = new ce.CfnAnomalyMonitor(this, "ServiceMonitor", {
      monitorName: "panther-services", monitorType: "DIMENSIONAL", monitorDimension: "SERVICE",
    });
    monitor.applyRemovalPolicy(RemovalPolicy.RETAIN);
    this.monitorArn = monitor.attrMonitorArn;
    const daily = new ce.CfnAnomalySubscription(this, "DailyAnomalySubscription", {
      subscriptionName: "panther-daily-anomalies", frequency: "DAILY",
      monitorArnList: [this.monitorArn],
      thresholdExpression: anomalyThreshold(props.anomalyThresholdUsd),
      subscribers: [{ type: "EMAIL", address: email }],
    });
    daily.applyRemovalPolicy(RemovalPolicy.RETAIN);
  }
}
