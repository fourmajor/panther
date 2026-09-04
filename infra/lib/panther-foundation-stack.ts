import {
  CfnOutput,
  Duration,
  RemovalPolicy,
  Stack,
  StackProps,
  Tags,
} from "aws-cdk-lib";
import * as budgets from "aws-cdk-lib/aws-budgets";
import * as cr from "aws-cdk-lib/custom-resources";
import * as iam from "aws-cdk-lib/aws-iam";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as sso from "aws-cdk-lib/aws-sso";
import * as ssm from "aws-cdk-lib/aws-ssm";
import { Construct } from "constructs";

export interface PantherFoundationStackProps extends StackProps {
  readonly administratorEmail: string;
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

    const privateAssetBucketParameter = new ssm.StringParameter(
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

    const identityCenter = new sso.CfnInstance(this, "IdentityCenter", {
      name: "Panther",
    });

    const administratorEmails = [
      {
        Value: props.administratorEmail,
        Type: "work",
        Primary: true,
      },
    ];
    const administratorUserParameters = {
      IdentityStoreId: identityCenter.attrIdentityStoreId,
      UserName: props.administratorEmail,
      DisplayName: "Panther Administrator",
      Emails: administratorEmails,
    };
    const administrator = new cr.AwsCustomResource(this, "AdministratorUser", {
      onCreate: {
        service: "identitystore",
        action: "createUser",
        parameters: administratorUserParameters,
        physicalResourceId: cr.PhysicalResourceId.fromResponse("UserId"),
      },
      onUpdate: {
        service: "identitystore",
        action: "createUser",
        parameters: administratorUserParameters,
        physicalResourceId: cr.PhysicalResourceId.fromResponse("UserId"),
      },
      onDelete: {
        service: "identitystore",
        action: "deleteUser",
        parameters: {
          IdentityStoreId: identityCenter.attrIdentityStoreId,
          UserId: new cr.PhysicalResourceIdReference(),
        },
      },
      policy: cr.AwsCustomResourcePolicy.fromStatements([
        new iam.PolicyStatement({
          actions: [
            "identitystore:CreateUser",
            "identitystore:DeleteUser",
          ],
          resources: ["*"],
        }),
      ]),
      installLatestAwsSdk: false,
    });

    this.createIdentityCenterAccess(
      identityCenter.attrInstanceArn,
      administrator.getResponseField("UserId"),
      privateAssets,
      privateAssetBucketParameter,
    );

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

  private createIdentityCenterAccess(
    instanceArn: string,
    principalId: string,
    privateAssets: s3.Bucket,
    privateAssetBucketParameter: ssm.StringParameter,
  ): void {
    const administrator = new sso.CfnPermissionSet(
      this,
      "AdministratorPermissionSet",
      {
        instanceArn,
        name: "PantherAdministrator",
        description: "Administrative access to the Panther AWS account",
        managedPolicies: ["arn:aws:iam::aws:policy/AdministratorAccess"],
        sessionDuration: "PT4H",
      },
    );

    new sso.CfnAssignment(this, "AdministratorAssignment", {
      instanceArn,
      permissionSetArn: administrator.attrPermissionSetArn,
      principalId,
      principalType: "USER",
      targetId: this.account,
      targetType: "AWS_ACCOUNT",
    });

    const uploaderPolicy = new iam.PolicyDocument({
      statements: [
        new iam.PolicyStatement({
          actions: ["s3:GetBucketLocation", "s3:ListBucket"],
          resources: [privateAssets.bucketArn],
          conditions: {
            StringLike: {
              "s3:prefix": ["games", "games/*"],
            },
          },
        }),
        new iam.PolicyStatement({
          actions: [
            "s3:AbortMultipartUpload",
            "s3:DeleteObject",
            "s3:GetObject",
            "s3:GetObjectTagging",
            "s3:PutObject",
            "s3:PutObjectTagging",
          ],
          resources: [privateAssets.arnForObjects("games/*")],
        }),
        new iam.PolicyStatement({
          actions: ["ssm:GetParameter"],
          resources: [privateAssetBucketParameter.parameterArn],
        }),
      ],
    });

    const assetUploader = new sso.CfnPermissionSet(
      this,
      "AssetUploaderPermissionSet",
      {
        instanceArn,
        name: "PantherAssetUploader",
        description: "Manage private Panther game assets without administrative access",
        inlinePolicy: uploaderPolicy.toJSON(),
        sessionDuration: "PT8H",
      },
    );

    new sso.CfnAssignment(this, "AssetUploaderAssignment", {
      instanceArn,
      permissionSetArn: assetUploader.attrPermissionSetArn,
      principalId,
      principalType: "USER",
      targetId: this.account,
      targetType: "AWS_ACCOUNT",
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
