import {
  CfnOutput,
  Duration,
  RemovalPolicy,
  Stack,
  StackProps,
  Tags,
} from "aws-cdk-lib";
import * as budgets from "aws-cdk-lib/aws-budgets";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as ssm from "aws-cdk-lib/aws-ssm";
import { Construct } from "constructs";

export interface PantherFoundationStackProps extends StackProps {
  readonly budgetEmail?: string;
  readonly monthlyBudgetUsd: number;
}

export class PantherFoundationStack extends Stack {
  constructor(scope: Construct, id: string, props: PantherFoundationStackProps) {
    super(scope, id, props);

    Tags.of(this).add("Project", "Panther");
    Tags.of(this).add("ManagedBy", "AWS-CDK");
    Tags.of(this).add("Environment", "production");

    const privateAssets = this.createAssetBucket("PrivateAssets");
    const publishedAssets = this.createAssetBucket("PublishedAssets");

    new ssm.StringParameter(this, "PrivateAssetBucketParameter", {
      parameterName: "/panther/foundation/private-asset-bucket",
      description: "Bucket containing private Panther originals and working assets",
      stringValue: privateAssets.bucketName,
    });

    new ssm.StringParameter(this, "PublishedAssetBucketParameter", {
      parameterName: "/panther/foundation/published-asset-bucket",
      description: "Bucket containing assets explicitly approved for publication",
      stringValue: publishedAssets.bucketName,
    });

    const notificationsWithSubscribers = props.budgetEmail
      ? [
          {
            notification: {
              comparisonOperator: "GREATER_THAN",
              notificationType: "ACTUAL",
              threshold: 80,
              thresholdType: "PERCENTAGE",
            },
            subscribers: [
              {
                address: props.budgetEmail,
                subscriptionType: "EMAIL",
              },
            ],
          },
        ]
      : undefined;

    new budgets.CfnBudget(this, "MonthlyCostBudget", {
      budget: {
        budgetName: "panther-monthly-cost",
        budgetType: "COST",
        timeUnit: "MONTHLY",
        budgetLimit: {
          amount: props.monthlyBudgetUsd,
          unit: "USD",
        },
      },
      notificationsWithSubscribers,
    });

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

  private createAssetBucket(id: string): s3.Bucket {
    return new s3.Bucket(this, id, {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      versioned: true,
      objectOwnership: s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
      removalPolicy: RemovalPolicy.RETAIN,
      autoDeleteObjects: false,
      lifecycleRules: [
        {
          id: "AbortIncompleteMultipartUploads",
          abortIncompleteMultipartUploadAfter: Duration.days(7),
        },
      ],
    });
  }
}
