import { App, Stack } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import * as cognito from "aws-cdk-lib/aws-cognito";
import assert from "node:assert/strict";
import test from "node:test";
import { catalogReaders, GRAFANA_USERNAME, ReadOnlyAccess, recordingStarters, VIEWER_USERNAME } from "../lib/read-only-access";

test("the synthetic reader is only added to the catalog reader list", () => {
  const readers = catalogReaders(
    ["example-operator", "example-member"],
    {publishers: ["example-operator"], workers: ["example-operator"], migrationAdmins: ["example-operator"]},
  );
  assert.deepEqual(readers, ["example-operator", "example-member", VIEWER_USERNAME]);
  assert.throws(() => catalogReaders(["example-operator"], {
    publishers: [VIEWER_USERNAME], workers: [], migrationAdmins: [],
  }));
});

test("recording starters are the human accounts, not the viewer or a headless worker", () => {
  assert.deepEqual(recordingStarters({
    users: ["example-operator", "example-member", "example-worker", VIEWER_USERNAME],
    passwordBootstrap: ["example-worker"],
  }), ["example-operator", "example-member"]);
  assert.ok(!recordingStarters({users: ["example-operator"], passwordBootstrap: []}).includes(VIEWER_USERNAME));
});

test("grafana and viewer credentials are stored, not emitted as access keys", () => {
  const app = new App();
  const stack = new Stack(app, "ReadOnly", {env: {account: "223663280572", region: "us-west-2"}});
  new ReadOnlyAccess(stack, "Access", {userPool: new cognito.UserPool(stack, "Pool")});
  const template = Template.fromStack(stack);
  const body = JSON.stringify(template.toJSON());
  template.resourceCountIs("AWS::IAM::User", 1);
  template.resourceCountIs("AWS::IAM::AccessKey", 0);
  template.hasResourceProperties("AWS::IAM::User", {UserName: GRAFANA_USERNAME});
  template.hasResourceProperties("AWS::SecretsManager::Secret", {Name: "panther/viewer-credentials"});
  assert.match(body, /cloudwatch:GetMetricData/);
  assert.match(body, /cloudwatch:GetMetricStatistics/);
  assert.match(body, /cloudwatch:ListMetrics/);
  assert.match(body, /cloudwatch:DescribeAlarms/);
  assert.match(body, /ec2:DescribeRegions/);
  assert.match(body, /tag:GetResources/);
  assert.match(body, /logs:DescribeLogGroups/);
  assert.match(body, /secretsmanager:GetSecretValue/);
  assert.match(body, /PantherWatchdogReadOnly/);
  assert.match(body, /penelope-viewer/);
  assert.doesNotMatch(body, /AWS::IAM::AccessKey/);
  assert.doesNotMatch(body, /logs:GetLogEvents/);
  assert.doesNotMatch(body, /states:StartExecution/);
  assert.doesNotMatch(body, /s3:GetObject/);
  assert.doesNotMatch(body, /SecretAccessKey/);
  assert.doesNotMatch(body, /AdminDeleteUser/);
});
