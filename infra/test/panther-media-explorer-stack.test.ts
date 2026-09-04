import { App } from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import test from "node:test";
import { PantherMediaExplorerStack } from "../lib/panther-media-explorer-stack";

function mediaExplorerTemplate(): Template {
  const app = new App();
  const stack = new PantherMediaExplorerStack(app, "TestMediaExplorer", {
    env: {
      account: "123456789012",
      region: "us-west-2",
    },
    cognitoDomainPrefix: "panther-media-example",
  });
  return Template.fromStack(stack);
}

test("media explorer uses private static hosting and Cognito authentication", () => {
  const template = mediaExplorerTemplate();

  template.hasResourceProperties("AWS::S3::Bucket", {
    PublicAccessBlockConfiguration: {
      BlockPublicAcls: true,
      BlockPublicPolicy: true,
      IgnorePublicAcls: true,
      RestrictPublicBuckets: true,
    },
  });
  template.resourceCountIs("AWS::CloudFront::Distribution", 1);
  template.hasResourceProperties("AWS::CloudFront::ResponseHeadersPolicy", {
    ResponseHeadersPolicyConfig: Match.objectLike({
      SecurityHeadersConfig: Match.objectLike({
        ContentSecurityPolicy: Match.objectLike({
          ContentSecurityPolicy: Match.stringLikeRegexp("frame-ancestors 'none'"),
          Override: true,
        }),
      }),
    }),
  });
  template.hasResourceProperties("AWS::Cognito::UserPool", {
    AdminCreateUserConfig: { AllowAdminCreateUserOnly: true },
    MfaConfiguration: "OPTIONAL",
    Policies: {
      PasswordPolicy: Match.objectLike({
        MinimumLength: 16,
        RequireLowercase: true,
        RequireNumbers: true,
        RequireSymbols: true,
        RequireUppercase: true,
      }),
    },
  });
  template.hasResourceProperties("AWS::Cognito::UserPoolClient", {
    AllowedOAuthFlows: ["code"],
    AllowedOAuthFlowsUserPoolClient: true,
    GenerateSecret: false,
    PreventUserExistenceErrors: "ENABLED",
  });
});

test("media explorer provisions two users without exposing password values", () => {
  const template = mediaExplorerTemplate();

  template.resourceCountIs("Custom::PantherMediaUser", 2);
  template.hasResourceProperties("Custom::PantherMediaUser", {
    Username: "stu",
    PasswordParameterName: "/panther/media-explorer/users/stu/password",
  });
  template.hasResourceProperties("Custom::PantherMediaUser", {
    Username: "other_stu",
    PasswordParameterName: "/panther/media-explorer/users/other_stu/password",
  });
  template.hasResourceProperties("AWS::IAM::Policy", {
    PolicyDocument: Match.objectLike({
      Statement: Match.arrayWith([
        Match.objectLike({
          Action: Match.arrayWith([
            "cognito-idp:AdminCreateUser",
            "cognito-idp:AdminSetUserPassword",
          ]),
          Effect: "Allow",
        }),
        Match.objectLike({
          Action: Match.arrayWith(["ssm:GetParameter", "ssm:PutParameter"]),
          Effect: "Allow",
        }),
      ]),
    }),
  });
});

test("media API is JWT protected and can only read private assets", () => {
  const template = mediaExplorerTemplate();

  template.hasResourceProperties("AWS::ApiGatewayV2::Authorizer", {
    AuthorizerType: "JWT",
    IdentitySource: ["$request.header.Authorization"],
  });
  template.resourceCountIs("AWS::ApiGatewayV2::Route", 2);
  template.allResourcesProperties("AWS::ApiGatewayV2::Route", {
    AuthorizationType: "JWT",
  });
  template.hasResourceProperties("AWS::Lambda::Function", {
    Environment: {
      Variables: Match.objectLike({
        SIGNED_URL_TTL_SECONDS: "300",
      }),
    },
    Handler: "index.handler",
    MemorySize: 256,
    Runtime: "python3.13",
    Timeout: 10,
  });
  template.hasResourceProperties("AWS::IAM::Policy", {
    PolicyDocument: Match.objectLike({
      Statement: Match.arrayWith([
        Match.objectLike({
          Action: "s3:ListBucket",
          Condition: {
            StringLike: {
              "s3:prefix": ["games", "games/*"],
            },
          },
          Effect: "Allow",
        }),
        Match.objectLike({
          Action: "s3:GetObject",
          Effect: "Allow",
        }),
      ]),
    }),
  });
});
