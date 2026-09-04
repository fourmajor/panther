import * as fs from "node:fs";
import * as path from "node:path";
import {
  CfnOutput,
  CustomResource,
  Duration,
  RemovalPolicy,
  Stack,
  StackProps,
  Tags,
} from "aws-cdk-lib";
import * as apigwv2 from "aws-cdk-lib/aws-apigatewayv2";
import * as apigwv2Authorizers from "aws-cdk-lib/aws-apigatewayv2-authorizers";
import * as apigwv2Integrations from "aws-cdk-lib/aws-apigatewayv2-integrations";
import * as cloudfront from "aws-cdk-lib/aws-cloudfront";
import * as origins from "aws-cdk-lib/aws-cloudfront-origins";
import * as acm from "aws-cdk-lib/aws-certificatemanager";
import * as cognito from "aws-cdk-lib/aws-cognito";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as logs from "aws-cdk-lib/aws-logs";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as s3deploy from "aws-cdk-lib/aws-s3-deployment";
import * as ssm from "aws-cdk-lib/aws-ssm";
import * as route53 from "aws-cdk-lib/aws-route53";
import * as route53Targets from "aws-cdk-lib/aws-route53-targets";
import * as cr from "aws-cdk-lib/custom-resources";
import { Construct } from "constructs";

const MEDIA_USERS = ["stu", "other_stu"] as const;

// The module build has bare Three.js imports; static hosting needs this
// self-contained browser distribution instead.
export const MODEL_VIEWER_BUNDLE_PATH = path.join(
  __dirname,
  "../../node_modules/@google/model-viewer/dist/model-viewer.min.js",
);

export interface PantherMediaExplorerStackProps extends StackProps {
  readonly certificateArn: string;
  readonly cognitoDomainPrefix: string;
  readonly domainName: string;
  readonly hostedZoneId: string;
}

export class PantherMediaExplorerStack extends Stack {
  constructor(scope: Construct, id: string, props: PantherMediaExplorerStackProps) {
    super(scope, id, props);

    const certificate = acm.Certificate.fromCertificateArn(
      this,
      "DomainCertificate",
      props.certificateArn,
    );
    const hostedZone = route53.HostedZone.fromHostedZoneAttributes(this, "HostedZone", {
      hostedZoneId: props.hostedZoneId,
      zoneName: props.domainName,
    });

    Tags.of(this).add("Project", "Panther");
    Tags.of(this).add("ManagedBy", "AWS-CDK");
    Tags.of(this).add("Environment", "production");

    const privateAssetBucketName = ssm.StringParameter.valueForStringParameter(
      this,
      "/panther/foundation/private-asset-bucket",
    );
    const privateAssets = s3.Bucket.fromBucketName(
      this,
      "PrivateAssets",
      privateAssetBucketName,
    );

    const siteBucket = new s3.Bucket(this, "SiteBucket", {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      objectOwnership: s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
      removalPolicy: RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });

    const responseHeadersPolicy = new cloudfront.ResponseHeadersPolicy(
      this,
      "ResponseHeadersPolicy",
      {
        responseHeadersPolicyName: "panther-media-explorer-security",
        securityHeadersBehavior: {
          contentSecurityPolicy: {
            contentSecurityPolicy: [
              "default-src 'self'",
              "base-uri 'self'",
              "connect-src 'self' https://*.amazonaws.com https://*.amazoncognito.com",
              "frame-ancestors 'none'",
              "frame-src https://*.amazonaws.com",
              "img-src 'self' data: https://*.amazonaws.com",
              "media-src https://*.amazonaws.com",
              "object-src 'none'",
              // Model-viewer's bundled decoder initializes WebAssembly; this
              // permits WASM without enabling JavaScript eval.
              "script-src 'self' 'wasm-unsafe-eval'",
              // Exact hash of model-viewer 4.3.1's injected style element.
              "style-src 'self' 'sha256-F7kvx28zBT3UUQL/hTOYst+55RSmqyCY3muSCYmt6A4='",
              "worker-src 'self' blob:",
            ].join("; "),
            override: true,
          },
          contentTypeOptions: { override: true },
          frameOptions: {
            frameOption: cloudfront.HeadersFrameOption.DENY,
            override: true,
          },
          referrerPolicy: {
            referrerPolicy: cloudfront.HeadersReferrerPolicy.NO_REFERRER,
            override: true,
          },
          strictTransportSecurity: {
            accessControlMaxAge: Duration.days(365),
            includeSubdomains: true,
            override: true,
          },
        },
        customHeadersBehavior: {
          customHeaders: [
            {
              header: "Permissions-Policy",
              value: "camera=(), geolocation=(), microphone=()",
              override: true,
            },
          ],
        },
      },
    );

    const distribution = new cloudfront.Distribution(this, "Distribution", {
      certificate,
      defaultBehavior: {
        origin: origins.S3BucketOrigin.withOriginAccessControl(siteBucket),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        responseHeadersPolicy,
      },
      defaultRootObject: "index.html",
      errorResponses: [
        {
          httpStatus: 403,
          responseHttpStatus: 200,
          responsePagePath: "/index.html",
          ttl: Duration.minutes(1),
        },
        {
          httpStatus: 404,
          responseHttpStatus: 200,
          responsePagePath: "/index.html",
          ttl: Duration.minutes(1),
        },
      ],
      domainNames: [props.domainName],
      minimumProtocolVersion: cloudfront.SecurityPolicyProtocol.TLS_V1_2_2021,
      priceClass: cloudfront.PriceClass.PRICE_CLASS_100,
    });
    const siteUrl = `https://${props.domainName}`;

    const distributionAlias = route53.RecordTarget.fromAlias(
      new route53Targets.CloudFrontTarget(distribution),
    );
    new route53.ARecord(this, "IPv4Alias", {
      zone: hostedZone,
      recordName: props.domainName,
      target: distributionAlias,
    });
    new route53.AaaaRecord(this, "IPv6Alias", {
      zone: hostedZone,
      recordName: props.domainName,
      target: distributionAlias,
    });

    const userPool = new cognito.UserPool(this, "UserPool", {
      userPoolName: "panther-media-explorer",
      selfSignUpEnabled: false,
      signInAliases: { username: true, email: false },
      accountRecovery: cognito.AccountRecovery.NONE,
      mfa: cognito.Mfa.OPTIONAL,
      mfaSecondFactor: { otp: true, sms: false },
      passwordPolicy: {
        minLength: 16,
        requireDigits: true,
        requireLowercase: true,
        requireSymbols: true,
        requireUppercase: true,
        tempPasswordValidity: Duration.days(7),
      },
      removalPolicy: RemovalPolicy.DESTROY,
    });

    const userPoolDomain = userPool.addDomain("Domain", {
      cognitoDomain: {
        domainPrefix: props.cognitoDomainPrefix,
      },
    });

    const userPoolClient = userPool.addClient("WebClient", {
      userPoolClientName: "panther-media-explorer-web",
      generateSecret: false,
      preventUserExistenceErrors: true,
      enableTokenRevocation: true,
      authSessionValidity: Duration.minutes(3),
      accessTokenValidity: Duration.hours(1),
      idTokenValidity: Duration.hours(1),
      refreshTokenValidity: Duration.days(7),
      oAuth: {
        flows: { authorizationCodeGrant: true },
        scopes: [cognito.OAuthScope.OPENID, cognito.OAuthScope.PROFILE],
        callbackUrls: [`${siteUrl}/`],
        logoutUrls: [`${siteUrl}/`],
      },
    });

    const mediaApiLogGroup = new logs.LogGroup(this, "MediaApiLogGroup", {
      retention: logs.RetentionDays.ONE_MONTH,
      removalPolicy: RemovalPolicy.DESTROY,
    });
    const cliClient = userPool.addClient("CliClient", {
      userPoolClientName: "panther-cli",
      generateSecret: false,
      authFlows: { userPassword: true },
      preventUserExistenceErrors: true,
      enableTokenRevocation: true,
      accessTokenValidity: Duration.hours(1),
      idTokenValidity: Duration.hours(1),
      refreshTokenValidity: Duration.days(7),
    });
    const mediaApiFunction = new lambda.Function(this, "MediaApiFunction", {
      runtime: lambda.Runtime.PYTHON_3_13,
      architecture: lambda.Architecture.ARM_64,
      handler: "index.handler",
      code: lambda.Code.fromAsset(path.join(__dirname, "../../lambda/media-api"), {
        exclude: ["**/__pycache__/**", "**/*.pyc"],
      }),
      timeout: Duration.seconds(10),
      memorySize: 256,
      logGroup: mediaApiLogGroup,
      environment: {
        ASSET_BUCKET_NAME: privateAssets.bucketName,
        SIGNED_URL_TTL_SECONDS: "300",
      },
    });
    mediaApiFunction.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["s3:ListBucket"],
        resources: [privateAssets.bucketArn],
        conditions: {
          StringLike: {
            "s3:prefix": ["games", "games/*"],
          },
        },
      }),
    );
    mediaApiFunction.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["s3:GetObject"],
        resources: [privateAssets.arnForObjects("games/*")],
      }),
    );
    mediaApiFunction.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["s3:PutObject"],
        resources: [privateAssets.arnForObjects("games/*/assets/*/original/*")],
        conditions: { StringEquals: { "s3:if-none-match": "*" } },
      }),
    );

    const authorizer = new apigwv2Authorizers.HttpJwtAuthorizer(
      "CognitoAuthorizer",
      `https://cognito-idp.${this.region}.${this.urlSuffix}/${userPool.userPoolId}`,
      {
        jwtAudience: [userPoolClient.userPoolClientId, cliClient.userPoolClientId],
      },
    );
    const mediaApi = new apigwv2.HttpApi(this, "MediaApi", {
      apiName: "panther-media-explorer",
      corsPreflight: {
        allowHeaders: ["authorization", "content-type"],
        allowMethods: [apigwv2.CorsHttpMethod.GET],
        allowOrigins: [siteUrl],
        maxAge: Duration.days(1),
      },
    });
    const mediaIntegration = new apigwv2Integrations.HttpLambdaIntegration(
      "MediaIntegration",
      mediaApiFunction,
    );
    for (const route of ["/objects", "/object-url", "/characters", "/character"]) {
      mediaApi.addRoutes({
        path: route,
        methods: [apigwv2.HttpMethod.GET],
        integration: mediaIntegration,
        authorizer,
      });
    }
    mediaApi.addRoutes({
      path: "/uploads",
      methods: [apigwv2.HttpMethod.POST],
      integration: mediaIntegration,
      authorizer,
    });

    const passwordParameterPrefix = "/panther/media-explorer/users";
    const provisionerLogGroup = new logs.LogGroup(this, "UserProvisionerLogGroup", {
      retention: logs.RetentionDays.ONE_MONTH,
      removalPolicy: RemovalPolicy.DESTROY,
    });
    const provisionerFunction = new lambda.Function(this, "UserProvisionerFunction", {
      runtime: lambda.Runtime.PYTHON_3_13,
      architecture: lambda.Architecture.ARM_64,
      handler: "index.handler",
      code: lambda.Code.fromAsset(path.join(__dirname, "../../lambda/user-provisioner")),
      timeout: Duration.seconds(30),
      memorySize: 128,
      logGroup: provisionerLogGroup,
    });
    provisionerFunction.addToRolePolicy(
      new iam.PolicyStatement({
        actions: [
          "cognito-idp:AdminCreateUser",
          "cognito-idp:AdminDeleteUser",
          "cognito-idp:AdminGetUser",
          "cognito-idp:AdminSetUserPassword",
        ],
        resources: [userPool.userPoolArn],
      }),
    );
    provisionerFunction.addToRolePolicy(
      new iam.PolicyStatement({
        actions: [
          "ssm:AddTagsToResource",
          "ssm:DeleteParameter",
          "ssm:GetParameter",
          "ssm:PutParameter",
        ],
        resources: [
          this.formatArn({
            service: "ssm",
            resource: "parameter",
            resourceName: "panther/media-explorer/users/*",
          }),
        ],
      }),
    );

    const providerLogGroup = new logs.LogGroup(this, "UserProviderLogGroup", {
      retention: logs.RetentionDays.ONE_MONTH,
      removalPolicy: RemovalPolicy.DESTROY,
    });
    const userProvider = new cr.Provider(this, "UserProvider", {
      onEventHandler: provisionerFunction,
      logGroup: providerLogGroup,
    });

    for (const username of MEDIA_USERS) {
      new CustomResource(this, `User-${username}`, {
        serviceToken: userProvider.serviceToken,
        resourceType: "Custom::PantherMediaUser",
        properties: {
          UserPoolId: userPool.userPoolId,
          Username: username,
          PasswordParameterName: `${passwordParameterPrefix}/${username}/password`,
        },
      });
    }

    new s3deploy.BucketDeployment(this, "SiteDeployment", {
      destinationBucket: siteBucket,
      sources: [
        s3deploy.Source.asset(path.join(__dirname, "../../../web/media-explorer")),
        s3deploy.Source.data("cli-config.json", JSON.stringify({
          apiUrl: mediaApi.apiEndpoint,
          clientId: cliClient.userPoolClientId,
          region: this.region,
          maxUploadBytes: 1024 * 1024 * 1024,
        })),
        s3deploy.Source.data(
          "config.js",
          [
            "window.PANTHER_CONFIG = ",
            JSON.stringify({
              apiUrl: mediaApi.apiEndpoint,
              clientId: userPoolClient.userPoolClientId,
              cognitoDomain: userPoolDomain.baseUrl(),
              redirectUri: `${siteUrl}/`,
            }),
            ";\n",
          ].join(""),
        ),
        s3deploy.Source.data(
          "vendor/model-viewer.min.js",
          fs.readFileSync(MODEL_VIEWER_BUNDLE_PATH, "utf8"),
        ),
      ],
      distribution,
      distributionPaths: ["/*"],
      prune: true,
    });

    new CfnOutput(this, "MediaExplorerUrl", {
      value: siteUrl,
      description: "Password-protected Panther media explorer",
    });
    new CfnOutput(this, "UserPoolId", {
      value: userPool.userPoolId,
      description: "Cognito user pool for the media explorer",
    });
    new CfnOutput(this, "WebClientId", {
      value: userPoolClient.userPoolClientId,
      description: "Public OAuth client ID used by the media explorer",
    });
    new CfnOutput(this, "PasswordParameterPrefix", {
      value: passwordParameterPrefix,
      description: "SecureString parameters holding the generated user passwords",
    });
  }
}
