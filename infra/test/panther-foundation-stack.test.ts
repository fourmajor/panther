import { App } from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import test from "node:test";
import { PantherFoundationStack } from "../lib/panther-foundation-stack";

test("foundation retains two encrypted and private asset buckets", () => {
  const app = new App();
  const stack = new PantherFoundationStack(app, "TestFoundation", {
    monthlyBudgetUsd: 10,
  });
  const template = Template.fromStack(stack);

  template.resourceCountIs("AWS::S3::Bucket", 2);
  template.allResourcesProperties("AWS::S3::Bucket", {
    BucketEncryption: {
      ServerSideEncryptionConfiguration: [
        {
          ServerSideEncryptionByDefault: {
            SSEAlgorithm: "AES256",
          },
        },
      ],
    },
    OwnershipControls: {
      Rules: [{ ObjectOwnership: "BucketOwnerEnforced" }],
    },
    PublicAccessBlockConfiguration: {
      BlockPublicAcls: true,
      BlockPublicPolicy: true,
      IgnorePublicAcls: true,
      RestrictPublicBuckets: true,
    },
    VersioningConfiguration: {
      Status: "Enabled",
    },
  });
  template.allResources("AWS::S3::Bucket", {
    DeletionPolicy: "Retain",
    UpdateReplacePolicy: "Retain",
  });
});

test("foundation records bucket names and creates an account budget", () => {
  const app = new App();
  const stack = new PantherFoundationStack(app, "TestFoundation", {
    budgetEmail: "alerts@example.com",
    monthlyBudgetUsd: 10,
  });
  const template = Template.fromStack(stack);

  template.resourceCountIs("AWS::SSM::Parameter", 2);
  template.hasResourceProperties("AWS::Budgets::Budget", {
    Budget: {
      BudgetName: "panther-monthly-cost",
      BudgetLimit: {
        Amount: 10,
        Unit: "USD",
      },
      BudgetType: "COST",
      TimeUnit: "MONTHLY",
    },
    NotificationsWithSubscribers: Match.arrayWith([
      Match.objectLike({
        Subscribers: [
          {
            Address: "alerts@example.com",
            SubscriptionType: "EMAIL",
          },
        ],
      }),
    ]),
  });
});

test("foundation assigns administrator and asset-uploader access", () => {
  const app = new App();
  const stack = new PantherFoundationStack(app, "TestFoundation", {
    env: {
      account: "123456789012",
      region: "us-west-2",
    },
    administratorPrincipalId: "1234567890-12345678-1234-1234-1234-123456789012",
    identityCenterInstanceArn: "arn:aws:sso:::instance/ssoins-1234567890abcdef",
    monthlyBudgetUsd: 10,
  });
  const template = Template.fromStack(stack);

  template.resourceCountIs("AWS::SSO::PermissionSet", 2);
  template.resourceCountIs("AWS::SSO::Assignment", 2);
  template.hasResourceProperties("AWS::SSO::PermissionSet", {
    Name: "PantherAdministrator",
    ManagedPolicies: ["arn:aws:iam::aws:policy/AdministratorAccess"],
  });
  template.hasResourceProperties("AWS::SSO::PermissionSet", {
    Name: "PantherAssetUploader",
    InlinePolicy: Match.objectLike({
      Statement: Match.arrayWith([
        Match.objectLike({
          Action: Match.arrayWith(["s3:PutObject"]),
          Effect: "Allow",
        }),
        Match.objectLike({
          Action: "ssm:GetParameter",
          Effect: "Allow",
        }),
      ]),
    }),
  });
});
