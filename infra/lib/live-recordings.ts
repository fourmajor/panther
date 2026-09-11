import * as path from "node:path";
import { Duration, RemovalPolicy } from "aws-cdk-lib";
import { Construct } from "constructs";
import * as api from "aws-cdk-lib/aws-apigatewayv2";
import * as integrations from "aws-cdk-lib/aws-apigatewayv2-integrations";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as logs from "aws-cdk-lib/aws-logs";

/** Ephemeral presence/read-time preview, never source assets or editorial inputs. */
export class LiveRecordings extends Construct {
  constructor(scope: Construct, id: string, props: {
    api: api.HttpApi; authorizer: api.IHttpRouteAuthorizer; accessEnvironment: Record<string, string>;
  }) {
    super(scope, id);
    const table = new dynamodb.Table(this, "Data", {
      partitionKey: { name: "gameId", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "recordingId", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      encryption: dynamodb.TableEncryption.AWS_MANAGED,
      timeToLiveAttribute: "expiresAt",
      removalPolicy: RemovalPolicy.RETAIN,
    });
    const history = new dynamodb.Table(this, "History", {
      partitionKey: { name: "feedId", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "partIndex", type: dynamodb.AttributeType.NUMBER },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      encryption: dynamodb.TableEncryption.AWS_MANAGED,
      timeToLiveAttribute: "expiresAt",
      removalPolicy: RemovalPolicy.RETAIN,
    });
    const fn = new lambda.Function(this, "Api", {
      runtime: lambda.Runtime.PYTHON_3_13, architecture: lambda.Architecture.ARM_64,
      handler: "live_recordings.handler", memorySize: 128, timeout: Duration.seconds(10),
      code: lambda.Code.fromAsset(path.join(__dirname, "../../lambda/media-api"), {
        exclude: ["**/__pycache__/**", "**/*.pyc"],
      }),
      logGroup: new logs.LogGroup(this, "Logs", { retention: logs.RetentionDays.ONE_WEEK }),
      environment: { LIVE_RECORDINGS_TABLE: table.tableName, LIVE_HISTORY_TABLE: history.tableName,
        LIVE_RECORDING_PUBLISHERS: props.accessEnvironment.MODEL_PUBLISHERS },
    });
    fn.addToRolePolicy(new iam.PolicyStatement({
      actions: ["dynamodb:Query", "dynamodb:PutItem", "dynamodb:GetItem"], resources: [table.tableArn],
    }));
    fn.addToRolePolicy(new iam.PolicyStatement({
      actions: ["dynamodb:Query", "dynamodb:PutItem"], resources: [history.tableArn],
    }));
    const integration = new integrations.HttpLambdaIntegration("LiveRecordingIntegration", fn);
    props.api.addRoutes({ path: "/recordings/live", methods: [api.HttpMethod.GET, api.HttpMethod.POST],
      integration, authorizer: props.authorizer });
    props.api.addRoutes({ path: "/recordings/live/history", methods: [api.HttpMethod.GET, api.HttpMethod.POST],
      integration, authorizer: props.authorizer });
  }
}
