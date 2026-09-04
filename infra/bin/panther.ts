#!/usr/bin/env node

import * as cdk from "aws-cdk-lib";
import { PantherFoundationStack } from "../lib/panther-foundation-stack";

const app = new cdk.App();

const region =
  app.node.tryGetContext("region") ?? process.env.PANTHER_AWS_REGION ?? "us-west-2";
const account =
  app.node.tryGetContext("account") ?? process.env.PANTHER_AWS_ACCOUNT_ID;
const budgetEmail = app.node.tryGetContext("budgetEmail");
const administratorEmail = app.node.tryGetContext("administratorEmail");
const monthlyBudgetUsd = Number(app.node.tryGetContext("monthlyBudgetUsd") ?? 10);

if (!administratorEmail) {
  throw new Error("administratorEmail CDK context is required");
}

if (!account || !/^\d{12}$/.test(account)) {
  throw new Error("account CDK context must be the 12-digit Panther AWS account ID");
}

if (!Number.isFinite(monthlyBudgetUsd) || monthlyBudgetUsd <= 0) {
  throw new Error("monthlyBudgetUsd must be a positive number");
}

new PantherFoundationStack(app, "PantherFoundation", {
  administratorEmail,
  env: {
    account,
    region,
  },
  budgetEmail,
  monthlyBudgetUsd,
  description: "Near-zero-idle foundation for Panther application and game assets",
});
