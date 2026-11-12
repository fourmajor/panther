import * as path from "node:path";
import { Duration } from "aws-cdk-lib";
import { Construct } from "constructs";
import * as api from "aws-cdk-lib/aws-apigatewayv2";
import * as integrations from "aws-cdk-lib/aws-apigatewayv2-integrations";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as events from "aws-cdk-lib/aws-events";
import * as targets from "aws-cdk-lib/aws-events-targets";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as logs from "aws-cdk-lib/aws-logs";
import * as sns from "aws-cdk-lib/aws-sns";

/** Notices only. This does not claim work, refresh a login, or start paid generation.
 * It lives in the existing notifications nested stack so the parent stays deployable. */
export class PipelineWatch extends Construct {
  constructor(scope: Construct, id: string, props: {
    api: api.IHttpApi;
    authorizer: api.IHttpRouteAuthorizer;
    workshopTable: dynamodb.ITable;
    jobs: Record<string, dynamodb.ITable>;
    routes: { id: string; path: string; fn: lambda.IFunction }[];
  }) {
    super(scope, id);
    const topic = new sns.Topic(this, "Alerts");
    // Match every state-machine failure in this account. Naming the machines here would
    // cycle the nested stack with the executions that publish into its log group.
    new events.Rule(this, "ExecutionAlert", {
      eventPattern: {
        source: ["aws.states"],
        detailType: ["Step Functions Execution Status Change"],
        detail: { status: ["FAILED", "TIMED_OUT", "ABORTED"] },
      },
      targets: [new targets.SnsTopic(topic)],
    });
    const fn = new lambda.Function(this, "Watch", {
      runtime: lambda.Runtime.PYTHON_3_13,
      architecture: lambda.Architecture.ARM_64,
      handler: "pipeline_watch.handler",
      code: lambda.Code.fromAsset(path.join(__dirname, "../../lambda/media-api"), {
        exclude: ["**/__pycache__/**", "**/*.pyc"],
      }),
      timeout: Duration.seconds(60),
      memorySize: 256,
      logGroup: new logs.LogGroup(this, "Logs", { retention: logs.RetentionDays.ONE_MONTH }),
      environment: {
        WORKSHOP_TABLE: props.workshopTable.tableName,
        TOPIC_ARN: topic.topicArn,
        STALE_SECONDS: "1200",
        JOB_TABLES: JSON.stringify(Object.fromEntries(
          Object.entries(props.jobs).map(([kind, table]) => [kind, table.tableName]))),
      },
    });
    props.workshopTable.grantReadWriteData(fn);
    for (const table of Object.values(props.jobs)) table.grantReadData(fn);
    topic.grantPublish(fn);
    new events.Rule(this, "Schedule", {
      schedule: events.Schedule.rate(Duration.minutes(10)),
      targets: [new targets.LambdaFunction(fn)],
    });
    for (const route of props.routes) {
      new api.HttpRoute(this, route.id, {
        httpApi: props.api,
        routeKey: api.HttpRouteKey.with(route.path, api.HttpMethod.POST),
        authorizer: props.authorizer,
        integration: new integrations.HttpLambdaIntegration(route.id + "Integration", route.fn),
      });
    }
  }
}
