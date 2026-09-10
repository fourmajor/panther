import * as path from "node:path";
import { Duration, RemovalPolicy } from "aws-cdk-lib";
import { Construct } from "constructs";
import * as api from "aws-cdk-lib/aws-apigatewayv2";
import * as integrations from "aws-cdk-lib/aws-apigatewayv2-integrations";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as logs from "aws-cdk-lib/aws-logs";
import * as s3 from "aws-cdk-lib/aws-s3";

export class GameCatalog extends Construct {
  constructor(scope: Construct, id: string, props: {
    bucket: s3.IBucket; api: api.HttpApi; authorizer: api.IHttpRouteAuthorizer;
  }) {
    super(scope, id);
    const table = new dynamodb.Table(this, "Data", {
      partitionKey: { name: "pk", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "sk", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      encryption: dynamodb.TableEncryption.AWS_MANAGED,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    const fn = new lambda.Function(this, "Api", {
      runtime: lambda.Runtime.PYTHON_3_13, architecture: lambda.Architecture.ARM_64,
      handler: "catalog.handler", memorySize: 256, timeout: Duration.seconds(30),
      code: lambda.Code.fromAsset(path.join(__dirname, "../../lambda/media-api"), {
        exclude: ["**/__pycache__/**", "**/*.pyc"],
      }),
      logGroup: new logs.LogGroup(this, "Logs", { retention: logs.RetentionDays.ONE_MONTH }),
      environment: { ASSET_BUCKET_NAME: props.bucket.bucketName,
        CATALOG_TABLE: table.tableName, CATALOG_EDITORS: "stu,other_stu" },
    });
    fn.addToRolePolicy(new iam.PolicyStatement({
      actions: ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem", "dynamodb:ConditionCheckItem"],
      resources: [table.tableArn],
    }));
    fn.addToRolePolicy(new iam.PolicyStatement({
      actions: ["dynamodb:UpdateItem"], resources: [table.tableArn],
      conditions: { "ForAllValues:StringEquals": { "dynamodb:LeadingKeys": ["GAMES"] } },
    }));
    fn.addToRolePolicy(new iam.PolicyStatement({ actions: ["s3:ListBucket"],
      resources: [props.bucket.bucketArn] }));
    fn.addToRolePolicy(new iam.PolicyStatement({ actions: ["s3:GetObject"],
      resources: [props.bucket.arnForObjects("games/*/content/*"), props.bucket.arnForObjects("games/*/catalog/assets/*")] }));
    fn.addToRolePolicy(new iam.PolicyStatement({ actions: ["s3:PutObject"],
      resources: [props.bucket.arnForObjects("games/*/characters/*/profile.json")],
      conditions: { StringEquals: { "s3:if-none-match": "*" } } }));
    const integration = new integrations.HttpLambdaIntegration("CatalogIntegration", fn);
    for (const route of ["/games", "/game", "/players"]) {
      props.api.addRoutes({ path: route, methods: [api.HttpMethod.GET], integration, authorizer: props.authorizer });
    }
    props.api.addRoutes({ path: "/games", methods: [api.HttpMethod.POST], integration, authorizer: props.authorizer });
    props.api.addRoutes({ path: "/game/ruleset", methods: [api.HttpMethod.POST], integration, authorizer: props.authorizer });
    props.api.addRoutes({ path: "/character-profile", methods: [api.HttpMethod.POST], integration, authorizer: props.authorizer });
  }
}
