#!/usr/bin/env node

import * as cdk from "aws-cdk-lib";
import { PantherFoundationStack } from "../lib/panther-foundation-stack";

const app = new cdk.App();

const region =
  app.node.tryGetContext("region") ?? process.env.PANTHER_AWS_REGION ?? "us-west-2";
const budgetEmail = app.node.tryGetContext("budgetEmail");
const monthlyBudgetUsd = Number(app.node.tryGetContext("monthlyBudgetUsd") ?? 10);

if (!Number.isFinite(monthlyBudgetUsd) || monthlyBudgetUsd <= 0) {
  throw new Error("monthlyBudgetUsd must be a positive number");
}

new PantherFoundationStack(app, "PantherFoundation", {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region,
  },
  budgetEmail,
  monthlyBudgetUsd,
  description: "Near-zero-idle foundation for Panther application and game assets",
});
