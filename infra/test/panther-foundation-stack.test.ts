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
