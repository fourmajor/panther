import { App } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import assert from "node:assert/strict";
import test from "node:test";
import { PantherAccessStack } from "../lib/panther-access-stack";
import { PantherGitHubDeployStack } from "../lib/panther-github-deploy-stack";

test("github deploy role trusts only this repo's main branch", () => {
  const app = new App();
  const stack = new PantherGitHubDeployStack(app, "GitHub", {
    env: { account: "223663280572", region: "us-west-2" },
    repository: "fourmajor/panther",
  });
  const template = Template.fromStack(stack);
  const body = JSON.stringify(template.toJSON());
  template.resourceCountIs("Custom::AWSCDKOpenIdConnectProvider", 1);
  template.hasResourceProperties("Custom::AWSCDKOpenIdConnectProvider", {
    Url: "https://token.actions.githubusercontent.com",
    ClientIDList: ["sts.amazonaws.com"],
  });
  template.hasResourceProperties("AWS::IAM::Role", {
    RoleName: "PantherGitHubDeploy",
    MaxSessionDuration: 7200,
  });
  assert.match(body, /repo:fourmajor\/panther:ref:refs\/heads\/main/);
  assert.match(body, /AdministratorAccess/);
  assert.doesNotMatch(body, /pull_request/);
  assert.doesNotMatch(body, /refs\/heads\/\*/);
});

test("an existing GitHub OIDC provider can be reused", () => {
  const app = new App();
  const stack = new PantherGitHubDeployStack(app, "GitHub", {
    env: { account: "223663280572", region: "us-west-2" },
    repository: "fourmajor/panther",
    providerArn: "arn:aws:iam::223663280572:oidc-provider/token.actions.githubusercontent.com",
  });
  const template = Template.fromStack(stack);
  template.resourceCountIs("AWS::IAM::OIDCProvider", 0);
  template.resourceCountIs("Custom::AWSCDKOpenIdConnectProvider", 0);
});

test("permission set sessions stay at 12 hours", () => {
  const app = new App();
  const stack = new PantherAccessStack(app, "Access", {
    env: { account: "123456789012", region: "us-west-2" },
    administratorEmail: "admin@example.com",
    identityCenterInstanceArn: "arn:aws:sso:::instance/ssoins-1234567890abcdef",
    identityStoreId: "d-1234567890",
  });
  const template = Template.fromStack(stack);
  template.resourceCountIs("AWS::SSO::PermissionSet", 2);
  template.allResourcesProperties("AWS::SSO::PermissionSet", { SessionDuration: "PT12H" });
});
