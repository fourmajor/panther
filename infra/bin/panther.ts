#!/usr/bin/env node

import * as cdk from "aws-cdk-lib";
import { PantherAccessStack } from "../lib/panther-access-stack";
import { PantherFoundationStack } from "../lib/panther-foundation-stack";

const app = new cdk.App();

const region =
  app.node.tryGetContext("region") ?? process.env.PANTHER_AWS_REGION ?? "us-west-2";
const account =
  app.node.tryGetContext("account") ?? process.env.PANTHER_AWS_ACCOUNT_ID;
const budgetEmail = app.node.tryGetContext("budgetEmail");
const administratorEmail = app.node.tryGetContext("administratorEmail");
const identityCenterInstanceArn = app.node.tryGetContext("identityCenterInstanceArn");
const identityStoreId = app.node.tryGetContext("identityStoreId");
const monthlyBudgetUsd = Number(app.node.tryGetContext("monthlyBudgetUsd") ?? 10);

if (!account || !/^\d{12}$/.test(account)) {
  throw new Error("account CDK context must be the 12-digit Panther AWS account ID");
}

if (!Number.isFinite(monthlyBudgetUsd) || monthlyBudgetUsd <= 0) {
  throw new Error("monthlyBudgetUsd must be a positive number");
}

new PantherFoundationStack(app, "PantherFoundation", {
  env: {
    account,
    region,
  },
  budgetEmail,
  monthlyBudgetUsd,
  description: "Near-zero-idle foundation for Panther application and game assets",
});

const accessContext = [
  administratorEmail,
  identityCenterInstanceArn,
  identityStoreId,
];
if (accessContext.some(Boolean) && !accessContext.every(Boolean)) {
  throw new Error(
    "administratorEmail, identityCenterInstanceArn, and identityStoreId must be provided together",
  );
}

if (administratorEmail && identityCenterInstanceArn && identityStoreId) {
  new PantherAccessStack(app, "PantherAccess", {
    env: {
      account,
      region,
    },
    administratorEmail,
    identityCenterInstanceArn,
    identityStoreId,
    description: "Short-lived administrative and asset-upload access for Panther",
  });
}
