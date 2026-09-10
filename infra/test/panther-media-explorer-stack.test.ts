import { App } from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import test from "node:test";
import assert from "node:assert/strict";
import { PantherMediaExplorerStack } from "../lib/panther-media-explorer-stack";

function mediaExplorerTemplate(): Template {
  const app = new App();
  const stack = new PantherMediaExplorerStack(app, "TestMediaExplorer", {
    env: {
      account: "123456789012",
      region: "us-west-2",
    },
    certificateArn:
      "arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000000",
    cognitoDomainPrefix: "panther-media-example",
    domainName: "panther.place",
    hostedZoneId: "Z1234567890",
  });
  return Template.fromStack(stack);
}

test("roster character profile initialization is authenticated and create-only", () => {
  const template = mediaExplorerTemplate();
  template.hasResourceProperties("AWS::ApiGatewayV2::Route", { RouteKey: "POST /character-profile", AuthorizationType: "JWT" });
  const policies = Object.entries(template.findResources("AWS::IAM::Policy")).filter(([id]) => id.startsWith("GameCatalog"));
  const writes = policies.flatMap(([, p]) => p.Properties.PolicyDocument.Statement).filter((s: any) => s.Action === "s3:PutObject");
  assert.equal(writes.length, 1);
  assert.equal(writes[0].Condition.StringEquals["s3:if-none-match"], "*");
  assert.match(JSON.stringify(writes[0].Resource), /characters/);
});

test("completed recording sets trigger a separate durable laptop playback workflow", () => {
  const template = mediaExplorerTemplate();
  const machines = Object.entries(template.findResources("AWS::StepFunctions::StateMachine"))
    .filter(([id]) => id.startsWith("PlaybackProcessing"));
  assert.equal(machines.length, 1);
  const definition = JSON.stringify(machines);
  assert.match(definition, /AssembleAndVerifyOnLaptop/);
  assert.match(definition, /lambda:invoke.waitForTaskToken/);
  assert.match(definition, /2592000/);
  assert.doesNotMatch(definition, /Parallel|ecs:|sagemaker:|bedrock:/);
  for (const route of ["POST /recording-sets/complete", "GET /recording-playback-jobs",
    "POST /recording-playback-jobs/claim", "POST /recording-playback-jobs/heartbeat", "POST /recording-playback-jobs/complete"]) {
    template.hasResourceProperties("AWS::ApiGatewayV2::Route", { RouteKey: route, AuthorizationType: "JWT" });
  }
  const policies = JSON.stringify(Object.entries(template.findResources("AWS::IAM::Policy"))
    .filter(([id]) => id.startsWith("PlaybackProcessing")));
  assert.doesNotMatch(policies, /s3:PutObject/);
  const buckets = JSON.stringify(template.findResources("AWS::S3::Bucket"));
  assert.doesNotMatch(buckets, /s3:ObjectCreated/);
  template.hasResourceProperties("AWS::Lambda::Function", { Handler: "playback_jobs.handler" });
});

test("asset migrations are authenticated, serialized, conditional, and retain object versions", () => {
  const template = mediaExplorerTemplate();
  template.hasResourceProperties("AWS::ApiGatewayV2::Route", {RouteKey: "POST /asset-migrations", AuthorizationType: "JWT"});
  template.hasResourceProperties("AWS::Lambda::Function", {
    Handler: "asset_migrations.handler", ReservedConcurrentExecutions: Match.absent(),
    Environment: { Variables: Match.objectLike({ MIGRATION_LOCK_TABLE: Match.anyValue() }) },
  });
  template.hasResource("AWS::DynamoDB::Table", {
    DeletionPolicy: "Retain", Properties: Match.objectLike({
      BillingMode: "PAY_PER_REQUEST", TimeToLiveSpecification: Match.absent(),
      KeySchema: [{ AttributeName: "pk", KeyType: "HASH" }],
    }),
  });
  const policies = Object.entries(template.findResources("AWS::IAM::Policy"))
    .filter(([id]) => id.startsWith("AssetMigrations"));
  assert.equal(policies.length, 1);
  const statements = policies[0][1].Properties.PolicyDocument.Statement;
  const writes = statements.filter((s: any) => JSON.stringify(s.Action).includes("s3:PutObject"));
  assert.equal(writes.length, 1);
  assert.equal(writes[0].Condition.StringEquals["s3:x-amz-metadata-directive"], "REPLACE");
  assert.ok(writes[0].Condition.StringLike["s3:x-amz-copy-source"]);
  const deletes = statements.filter((s: any) => JSON.stringify(s.Action).includes("s3:Delete"));
  assert.equal(deletes.length, 0);
  assert.doesNotMatch(JSON.stringify(writes), /\/assets\/\*/);
  assert.doesNotMatch(JSON.stringify(statements), /s3:DeleteObjectVersion|s3:\*/);
  assert.doesNotMatch(JSON.stringify(template.findResources("AWS::ApiGatewayV2::Route")), /asset-storage-migrations/);
});

test("indexed storage is consistent across readers and only permits create-only organized uploads", () => {
  const template = mediaExplorerTemplate();
  const handlers = new Set(["index.handler", "asset_migrations.handler", "editorial_jobs.handler",
    "novel.handler", "model_jobs.handler", "playback_jobs.handler", "catalog.handler"]);
  for (const fn of Object.values(template.findResources("AWS::Lambda::Function"))) {
    if (handlers.has(fn.Properties.Handler) && fn.Properties.Environment?.Variables?.ASSET_BUCKET_NAME) {
      assert.equal(fn.Properties.Environment.Variables.ASSET_STORAGE_MODE, undefined);
      handlers.delete(fn.Properties.Handler);
    }
  }
  assert.equal(handlers.size, 0);
  const policy = Object.entries(template.findResources("AWS::IAM::Policy"))
    .find(([id]) => id.startsWith("MediaApiFunction"))![1];
  const statements = policy.Properties.PolicyDocument.Statement;
  const uploads = statements.filter((s: any) => JSON.stringify(s.Resource).includes("/content/"));
  assert.equal(uploads.length, 1);
  assert.equal(uploads[0].Condition.StringEquals["s3:if-none-match"], "*");
  assert.match(JSON.stringify(uploads[0].Resource), /catalog\/assets/);
  assert.doesNotMatch(JSON.stringify(statements), /assets\/\*\/original/);
});

test("model jobs use retained on-demand state and a durable external-worker callback", () => {
  const template = mediaExplorerTemplate();
  template.hasResource("AWS::DynamoDB::Table", {
    DeletionPolicy: "Retain",
    Properties: Match.objectLike({ BillingMode: "PAY_PER_REQUEST",
      StreamSpecification: { StreamViewType: "NEW_AND_OLD_IMAGES" } }),
  });
  template.hasResourceProperties("AWS::StepFunctions::StateMachine", {
    StateMachineType: "STANDARD", DefinitionString: Match.anyValue(),
  });
  const definition = JSON.stringify(template.findResources("AWS::StepFunctions::StateMachine"));
  assert.match(definition, /lambda:invoke.waitForTaskToken/);
  assert.match(definition, /2592000/);
  template.hasResourceProperties("AWS::Lambda::EventSourceMapping", {
    StartingPosition: "TRIM_HORIZON", FunctionResponseTypes: ["ReportBatchItemFailures"],
    BisectBatchOnFunctionError: true,
  });
  template.hasResourceProperties("AWS::Lambda::Function", {
    Handler: "model_jobs.handler", Environment: { Variables: Match.objectLike({ MODEL_WORKERS: "stu" }) },
  });
  template.resourceCountIs("AWS::EC2::NatGateway", 0);
  template.resourceCountIs("AWS::EC2::Instance", 0);
});

test("editorial workflow has separate review stages, parallel adaptations, and no video execution", () => {
  const template = mediaExplorerTemplate();
  const machines = Object.entries(template.findResources("AWS::StepFunctions::StateMachine"))
    .filter(([id]) => id.startsWith("EditorialProcessing"));
  assert.equal(machines.length, 1);
  const definition = JSON.stringify(machines);
  for (const stage of ["corrected-transcript", "novel-developmental-edit", "novel-continuity",
    "video-storyboards", "video-generation-packets", "video-preflight", "VideoGenerationNotAuthorized"]) {
    assert.ok(definition.includes(stage), stage);
  }
  assert.match(definition, /Parallel/);
  assert.match(definition, /lambda:invoke.waitForTaskToken/);
  assert.doesNotMatch(definition, /bedrock:|sagemaker:|ecs:|GenerateVideo/);
  const policies = JSON.stringify(Object.entries(template.findResources("AWS::IAM::Policy"))
    .filter(([id]) => id.startsWith("EditorialProcessing")));
  assert.doesNotMatch(policies, /s3:PutObject|bedrock:|sagemaker:/);
  template.hasResourceProperties("AWS::ApiGatewayV2::Route", {
    RouteKey: "POST /editorial-jobs", AuthorizationType: "JWT",
  });
});

test("structured game catalog is retained, on-demand and cannot mutate artwork", () => {
  const template = mediaExplorerTemplate();
  template.hasResourceProperties("AWS::Lambda::Function", {
    Handler: "catalog.handler", Environment: { Variables: Match.objectLike({ CATALOG_EDITORS: "stu,other_stu" }) },
  });
  const policies = Object.entries(template.findResources("AWS::IAM::Policy"))
    .filter(([id]) => id.startsWith("GameCatalog"));
  assert.equal(policies.length, 1);
  const policy = JSON.stringify(policies);
  assert.match(policy, /dynamodb:PutItem/);
  assert.doesNotMatch(policy, /s3:DeleteObject|dynamodb:DeleteItem/);
  assert.match(policy, /dynamodb:UpdateItem/);
  assert.match(policy, /dynamodb:LeadingKeys/);
  template.hasResourceProperties("AWS::ApiGatewayV2::Route", {
    RouteKey: "POST /game/ruleset", AuthorizationType: "JWT",
  });
});

test("novel reader is authenticated and has only read permissions", () => {
  const template = mediaExplorerTemplate();
  for (const route of ["GET /novel", "GET /novel-chapter"]) {
    template.hasResourceProperties("AWS::ApiGatewayV2::Route", { RouteKey: route, AuthorizationType: "JWT" });
  }
  template.hasResourceProperties("AWS::Lambda::Function", { Handler: "novel.handler" });
  const policies = Object.entries(template.findResources("AWS::IAM::Policy"))
    .filter(([id]) => id.startsWith("EditorialProcessingNovelReader"));
  assert.equal(policies.length, 1);
  const serialized = JSON.stringify(policies);
  assert.match(serialized, /dynamodb:Query/);
  assert.match(serialized, /s3:GetObject/);
  assert.doesNotMatch(serialized, /PutItem|UpdateItem|DeleteItem|PutObject|states:|InvokeFunction/);
});

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
  template.hasResourceProperties("AWS::CloudFront::Distribution", {
    DistributionConfig: Match.objectLike({
      Aliases: ["panther.place"],
      ViewerCertificate: Match.objectLike({
        AcmCertificateArn:
          "arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000000",
        MinimumProtocolVersion: "TLSv1.2_2021",
      }),
    }),
  });
  template.resourceCountIs("AWS::Route53::RecordSet", 2);
  template.hasResourceProperties("AWS::Route53::RecordSet", {
    Name: "panther.place.",
    Type: "A",
  });
  template.hasResourceProperties("AWS::Route53::RecordSet", {
    Name: "panther.place.",
    Type: "AAAA",
  });
  template.hasResourceProperties("AWS::CloudFront::ResponseHeadersPolicy", {
    ResponseHeadersPolicyConfig: Match.objectLike({
      SecurityHeadersConfig: Match.objectLike({
        ContentSecurityPolicy: Match.objectLike({
          ContentSecurityPolicy: Match.stringLikeRegexp(
            "frame-ancestors 'none'.*script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'sha256-F7kvx28zBT3UUQL/hTOYst\\+55RSmqyCY3muSCYmt6A4='",
          ),
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
    CallbackURLs: ["https://panther.place/"],
    GenerateSecret: false,
    LogoutURLs: ["https://panther.place/"],
    PreventUserExistenceErrors: "ENABLED",
  });
  template.hasResourceProperties("AWS::ApiGatewayV2::Api", {
    CorsConfiguration: Match.objectLike({
      AllowOrigins: ["https://panther.place"],
    }),
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

test("media API is JWT protected with limited conditional upload permissions", () => {
  const template = mediaExplorerTemplate();

  template.hasResourceProperties("AWS::ApiGatewayV2::Authorizer", {
    AuthorizerType: "JWT",
    IdentitySource: ["$request.header.Authorization"],
  });
  template.resourceCountIs("AWS::ApiGatewayV2::Route", 39);
  for (const route of ["GET /assets", "GET /asset-document"]) {
    template.hasResourceProperties("AWS::ApiGatewayV2::Route", {RouteKey: route, AuthorizationType: "JWT"});
  }
  for (const resource of Object.values(template.findResources("AWS::ApiGatewayV2::Route"))) {
    const route = resource.Properties.RouteKey;
    assert.equal(resource.Properties.AuthorizationType,
      ["POST /auth/session", "POST /auth/refresh", "POST /auth/logout"].includes(route) ? "NONE" : "JWT");
  }
  template.hasResourceProperties("AWS::Lambda::Function", {
    Environment: {
      Variables: Match.objectLike({
        SIGNED_URL_TTL_SECONDS: "300",
        MODEL_PUBLISHERS: "stu,other_stu",
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
        Match.objectLike({
          Action: "s3:PutObject",
          Resource: Match.anyValue(),
          Condition: { StringEquals: { "s3:if-none-match": "*" } },
          Effect: "Allow",
        }),
        Match.objectLike({
          Action: "s3:PutObject",
          Resource: { "Fn::Join": ["", Match.arrayWith(["/games/*/characters/*/history/*.json"])] },
          Condition: { StringEquals: { "s3:if-none-match": "*" } },
        }),
        Match.objectLike({
          Action: "s3:PutObject",
          Resource: { "Fn::Join": ["", Match.arrayWith(["/games/*/characters/*/profile.json"])] },
          Condition: { Null: { "s3:if-match": "false" } },
        }),
      ]),
    }),
  });
  template.hasResourceProperties("AWS::Cognito::UserPoolClient", {
    ClientName: "panther-cli",
    GenerateSecret: false,
    ExplicitAuthFlows: ["ALLOW_USER_PASSWORD_AUTH"],
  });
});

test("remembered sign-in uses maximum rotating refresh sessions and an uncached first-party cookie path", () => {
  const template = mediaExplorerTemplate();
  template.allResourcesProperties("AWS::Cognito::UserPoolClient", {
    AccessTokenValidity: 60, IdTokenValidity: 60, RefreshTokenValidity: 3650 * 24 * 60,
    TokenValidityUnits: { AccessToken: "minutes", IdToken: "minutes", RefreshToken: "minutes" },
    RefreshTokenRotation: { Feature: "ENABLED", RetryGracePeriodSeconds: 60 },
    EnableTokenRevocation: true,
  });
  for (const resource of Object.values(template.findResources("AWS::Cognito::UserPoolClient"))) {
    assert.ok(!resource.Properties.ExplicitAuthFlows?.includes("ALLOW_REFRESH_TOKEN_AUTH"));
  }
  template.hasResourceProperties("AWS::CloudFront::Distribution", {
    DistributionConfig: Match.objectLike({ CacheBehaviors: Match.arrayWith([Match.objectLike({
      PathPattern: "/auth/*", ViewerProtocolPolicy: "https-only",
      CachePolicyId: "4135ea2d-6df8-44a3-9df3-4b5a84be39ad",
      OriginRequestPolicyId: "b689b0a8-53d0-40ab-baf2-68738e2966ac",
      AllowedMethods: Match.arrayWith(["POST"]),
    })]) }),
  });
  template.hasResourceProperties("AWS::Lambda::Function", {
    Environment: { Variables: Match.objectLike({ SITE_ORIGIN: "https://panther.place", WEB_CLIENT_ID: Match.anyValue() }) },
    Timeout: 15, MemorySize: 128,
  });
});
