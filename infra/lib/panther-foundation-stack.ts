import {
  CfnOutput,
  Duration,
  RemovalPolicy,
  Stack,
  StackProps,
  Tags,
} from "aws-cdk-lib";
import * as budgets from "aws-cdk-lib/aws-budgets";
import * as ce from "aws-cdk-lib/aws-ce";
import * as iam from "aws-cdk-lib/aws-iam";
import * as sns from "aws-cdk-lib/aws-sns";
import * as subscriptions from "aws-cdk-lib/aws-sns-subscriptions";
import * as organizations from "aws-cdk-lib/aws-organizations";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as ssm from "aws-cdk-lib/aws-ssm";
import { Construct } from "constructs";
import { alertEmail, anomalyThreshold } from "./panther-cost-anomalies-stack";

export interface PantherFoundationStackProps extends StackProps {
  readonly applicationOrigin: string;
  readonly budgetEmail?: string;
  readonly monthlyBudgetUsd: number;
  readonly firstSpendUsd?: number;
  readonly actualBudgetPercentages?: number[];
  readonly forecastBudgetPercentages?: number[];
  readonly anomalyMonitorArn?: string;
  readonly anomalyThresholdUsd?: number;
}

export class PantherFoundationStack extends Stack {
  constructor(scope: Construct, id: string, props: PantherFoundationStackProps) {
    super(scope, id, props);

    Tags.of(this).add("Project", "Panther");
    Tags.of(this).add("ManagedBy", "AWS-CDK");
    Tags.of(this).add("Environment", "production");

    const organization = new organizations.CfnOrganization(this, "Organization", {
      featureSet: "ALL",
    });
    organization.applyRemovalPolicy(RemovalPolicy.RETAIN);

    const privateAssets = this.createAssetBucket(
      "PrivateAssets",
      props.applicationOrigin,
    );
    const publishedAssets = this.createAssetBucket("PublishedAssets");

    new ssm.StringParameter(
      this,
      "PrivateAssetBucketParameter",
      {
        parameterName: "/panther/foundation/private-asset-bucket",
        description: "Bucket containing private Panther originals and working assets",
        stringValue: privateAssets.bucketName,
      },
    );

    new ssm.StringParameter(this, "PublishedAssetBucketParameter", {
      parameterName: "/panther/foundation/published-asset-bucket",
      description: "Bucket containing assets explicitly approved for publication",
      stringValue: publishedAssets.bucketName,
    });

    const email = alertEmail(this, props.budgetEmail);
    const firstSpend = props.firstSpendUsd ?? 1;
    const actualPercentages = props.actualBudgetPercentages ?? [25, 50, 80, 100];
    const forecastPercentages = props.forecastBudgetPercentages ?? [80, 100];
    for (const [name, value] of [["monthlyBudgetUsd", props.monthlyBudgetUsd], ["firstSpendUsd", firstSpend]] as const) {
      if (!Number.isFinite(value) || value <= 0) throw new Error(`${name} must be positive`);
    }
    for (const [name, values, max] of [
      ["actualBudgetPercentages", actualPercentages, 4],
      ["forecastBudgetPercentages", forecastPercentages, 5],
    ] as const) {
      if (!values.length || values.length > max || new Set(values).size !== values.length ||
          values.some(value => !Number.isFinite(value) || value <= 0 || value > 1000)) {
        throw new Error(`${name} must contain 1-${max} distinct positive percentages up to 1000`);
      }
    }
    const notification = (type: string, thresholdType: string, threshold: number) => ({
      notification: { comparisonOperator: "GREATER_THAN", notificationType: type, thresholdType, threshold },
      // Direct Budgets email remains active even while SNS awaits confirmation.
      subscribers: [{ address: email, subscriptionType: "EMAIL" }],
    });
    const budget = {
      budgetType: "COST", timeUnit: "MONTHLY",
      budgetLimit: { amount: props.monthlyBudgetUsd, unit: "USD" },
      // Credits/refunds must not conceal new resource consumption. Include tax,
      // support and upfront charges; no service or region filters hide spend.
      costTypes: { includeCredit: false, includeRefund: false, includeTax: true,
        includeSubscription: true, includeUpfront: true, includeRecurring: true,
        includeOtherSubscription: true, includeSupport: true, includeDiscount: true,
        useBlended: false, useAmortized: false },
    };

    // Notification edits require replacement in CloudFormation. Let AWS assign
    // names so it can create the replacement before deleting the old budget.
    const actualBudget = new budgets.CfnBudget(this, "MonthlyCostBudget", {
      budget,
      notificationsWithSubscribers: [notification("ACTUAL", "ABSOLUTE_VALUE", firstSpend),
        ...actualPercentages.map(value => notification("ACTUAL", "PERCENTAGE", value))],
    });
    // AWS permits only five notifications per budget.
    const forecastBudget = new budgets.CfnBudget(this, "ForecastCostBudget", {
      budget,
      notificationsWithSubscribers: forecastPercentages.map(value => notification("FORECASTED", "PERCENTAGE", value)),
    });
    new CfnOutput(this, "ActualCostBudgetName", { value: actualBudget.ref });
    new CfnOutput(this, "ForecastCostBudgetName", { value: forecastBudget.ref });

    if (props.anomalyMonitorArn) {
      const topic = new sns.Topic(this, "CostAlertTopic", {
        topicName: "panther-cost-alerts", displayName: "Panther cost alerts",
        enforceSSL: true,
      });
      const policy = topic.addToResourcePolicy(new iam.PolicyStatement({
        principals: [new iam.ServicePrincipal("costalerts.amazonaws.com")],
        actions: ["sns:Publish"], resources: [topic.topicArn],
        conditions: { StringEquals: { "aws:SourceAccount": this.account } },
      }));
      topic.addSubscription(new subscriptions.EmailSubscription(email));
      const immediate = new ce.CfnAnomalySubscription(this, "ImmediateAnomalySubscription", {
        subscriptionName: "panther-immediate-anomalies", frequency: "IMMEDIATE",
        monitorArnList: [props.anomalyMonitorArn],
        thresholdExpression: anomalyThreshold(props.anomalyThresholdUsd ?? 1),
        subscribers: [{ type: "SNS", address: topic.topicArn }],
      });
      if (policy.policyDependable) immediate.node.addDependency(policy.policyDependable);
      new CfnOutput(this, "CostAlertTopicArn", { value: topic.topicArn,
        description: "Confirm the email subscription, then use the cost-alert runbook to test delivery" });
    }

    new CfnOutput(this, "PrivateAssetBucketName", {
      value: privateAssets.bucketName,
      description: "Upload private game assets to this bucket",
    });

    new CfnOutput(this, "PublishedAssetBucketName", {
      value: publishedAssets.bucketName,
      description: "Future origin for deliberately published assets",
    });

    new CfnOutput(this, "AssetKeyPattern", {
      value: "games/<game-id>/assets/<asset-id>/original/<filename>",
      description: "Canonical key pattern for original assets",
    });
  }

  private createAssetBucket(id: string, applicationOrigin?: string): s3.Bucket {
    return new s3.Bucket(this, id, {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      versioned: true,
      objectOwnership: s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
      removalPolicy: RemovalPolicy.RETAIN,
      autoDeleteObjects: false,
      cors: applicationOrigin
        ? [
            {
              allowedHeaders: ["*"],
              allowedMethods: [s3.HttpMethods.GET, s3.HttpMethods.HEAD],
              allowedOrigins: [applicationOrigin],
              exposedHeaders: ["ETag"],
              maxAge: Duration.hours(1).toSeconds(),
            },
          ]
        : undefined,
      lifecycleRules: [
        {
          id: "AbortIncompleteMultipartUploads",
          abortIncompleteMultipartUploadAfter: Duration.days(7),
        },
      ],
    });
  }
}
