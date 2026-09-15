import * as path from "node:path";
import { Duration, RemovalPolicy } from "aws-cdk-lib";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as events from "aws-cdk-lib/aws-events";
import * as targets from "aws-cdk-lib/aws-events-targets";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as iam from "aws-cdk-lib/aws-iam";
import * as destinations from "aws-cdk-lib/aws-lambda-destinations";
import * as logs from "aws-cdk-lib/aws-logs";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as sqs from "aws-cdk-lib/aws-sqs";
import * as apigw from "aws-cdk-lib/aws-apigatewayv2";
import * as integrations from "aws-cdk-lib/aws-apigatewayv2-integrations";
import { Construct } from "constructs";

export class AssetBrowseIndex extends Construct {
  constructor(scope: Construct, id: string, props: {
    bucket: s3.IBucket; api: apigw.HttpApi; authorizer: apigw.IHttpRouteAuthorizer;
    reader: lambda.Function; migrators: string;
  }) {
    super(scope, id);
    const table = new dynamodb.Table(this, "Catalog", {
      partitionKey: { name: "pk", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "sk", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST, removalPolicy: RemovalPolicy.RETAIN,
    });
    props.reader.addEnvironment("ASSET_BROWSE_TABLE", table.tableName);
    table.grant(props.reader, "dynamodb:Query", "dynamodb:GetItem");
    const failures = new sqs.Queue(this, "Failures", {
      retentionPeriod: Duration.days(14), enforceSSL: true,
    });
    const create = (name: string, handler: string) => {
      const fn = new lambda.Function(this, name, {
        runtime: lambda.Runtime.PYTHON_3_13, architecture: lambda.Architecture.ARM_64,
        handler, timeout: Duration.seconds(25), memorySize: 512,
        code: lambda.Code.fromAsset(path.join(__dirname, "../../lambda/media-api"), {
          exclude: ["**/__pycache__/**", "**/*.pyc"],
        }),
        logGroup: new logs.LogGroup(this, `${name}Logs`, {
          retention: logs.RetentionDays.ONE_WEEK, removalPolicy: RemovalPolicy.DESTROY,
        }),
        environment: { ASSET_BUCKET_NAME: props.bucket.bucketName,
          ASSET_BROWSE_TABLE: table.tableName, ASSET_MIGRATORS: props.migrators },
      });
      props.bucket.grantRead(fn, "games/*");
      fn.addToRolePolicy(new iam.PolicyStatement({ actions: ["s3:ListBucket"], resources: [props.bucket.bucketArn] }));
      table.grantReadWriteData(fn);
      return fn;
    };
    const writer = create("Writer", "browse_index.event_handler");
    writer.configureAsyncInvoke({ retryAttempts: 2, maxEventAge: Duration.hours(6),
      onFailure: new destinations.SqsDestination(failures) });
    const rule = new events.Rule(this, "AssetChanged", {
      eventPattern: { source: ["aws.s3"], detailType: ["Object Created"],
        detail: { bucket: { name: [props.bucket.bucketName] },
          object: { key: [{ wildcard: "games/*/content/*" }] } } },
    });
    rule.addTarget(new targets.LambdaFunction(writer, { deadLetterQueue: failures }));
    const maintenance = create("Maintenance", "browse_index.rebuild_handler");
    props.api.addRoutes({ path: "/asset-index/rebuild", methods: [apigw.HttpMethod.POST],
      integration: new integrations.HttpLambdaIntegration("IndexMaintenance", maintenance),
      authorizer: props.authorizer });
  }
}
