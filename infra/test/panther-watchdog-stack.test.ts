import { App } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import assert from "node:assert/strict";
import test from "node:test";
import { PantherWatchdogStack } from "../lib/panther-watchdog-stack";

test("watchdog user can only assume the read-only role", () => {
  const app = new App();
  const stack = new PantherWatchdogStack(app, "Watchdog", {
    env: { account: "223663280572", region: "us-west-2" },
  });
  const template = Template.fromStack(stack);
  const body = JSON.stringify(template.toJSON());

  template.resourceCountIs("AWS::IAM::User", 1);
  template.resourceCountIs("AWS::IAM::Role", 1);
  template.resourceCountIs("AWS::IAM::AccessKey", 0);
  template.hasResourceProperties("AWS::IAM::User", { UserName: "panther-watchdog" });
  template.hasResourceProperties("AWS::IAM::Role", {
    RoleName: "PantherWatchdogReadOnly",
    MaxSessionDuration: 3600,
  });

  assert.match(body, /states:List\*/);
  assert.match(body, /states:Describe\*/);
  assert.match(body, /states:GetExecutionHistory/);
  assert.match(body, /s3:ListBucket/);
  assert.match(body, /s3:GetObject/);
  assert.match(body, /cloudwatch:Get\*/);
  assert.match(body, /DenyMutations/);
  assert.match(body, /sts:AssumeRole/);
  assert.doesNotMatch(body, /AWS::IAM::AccessKey/);
  assert.doesNotMatch(body, /s3:PutObject/);
  assert.doesNotMatch(body, /states:StartExecution/);
  assert.doesNotMatch(body, /AdministratorAccess/);
});
