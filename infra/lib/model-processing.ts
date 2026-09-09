import * as path from "node:path";
import { Duration, RemovalPolicy } from "aws-cdk-lib";
import { Construct } from "constructs";
import * as api from "aws-cdk-lib/aws-apigatewayv2";
import * as integrations from "aws-cdk-lib/aws-apigatewayv2-integrations";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as sources from "aws-cdk-lib/aws-lambda-event-sources";
import * as logs from "aws-cdk-lib/aws-logs";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as sfn from "aws-cdk-lib/aws-stepfunctions";
import * as tasks from "aws-cdk-lib/aws-stepfunctions-tasks";

/** Private application jobs, not CI. No AI service, inbound laptop connection, or idle compute. */
export class ModelProcessing extends Construct {
  constructor(scope: Construct, id: string, props: {
    bucket: s3.IBucket; api: api.HttpApi; authorizer: api.IHttpRouteAuthorizer;
  }) {
    super(scope, id);
    const table = new dynamodb.Table(this, "Jobs", {
      partitionKey: { name: "pk", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "sk", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      stream: dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,
      encryption: dynamodb.TableEncryption.AWS_MANAGED,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    const logGroup = new logs.LogGroup(this, "Logs", {
      retention: logs.RetentionDays.ONE_MONTH, removalPolicy: RemovalPolicy.DESTROY,
    });
    const code = lambda.Code.fromAsset(path.join(__dirname, "../../lambda/media-api"), {
      exclude: ["**/__pycache__/**", "**/*.pyc"],
    });
    const fn = new lambda.Function(this, "Broker", {
      runtime: lambda.Runtime.PYTHON_3_13, architecture: lambda.Architecture.ARM_64,
      handler: "model_jobs.handler",
      code,
      memorySize: 256, timeout: Duration.seconds(60), logGroup,
      environment: { ASSET_BUCKET_NAME: props.bucket.bucketName, JOB_TABLE: table.tableName,
        MODEL_PUBLISHERS: "stu,other_stu", MODEL_WORKERS: "stu" },
    });
    table.grantReadWriteData(fn);
    props.bucket.grantRead(fn, "games/*");
    fn.addToRolePolicy(new iam.PolicyStatement({ actions: ["s3:PutObject"],
      resources: [props.bucket.arnForObjects("games/*/characters/*/history/*.json")],
      conditions: { StringEquals: { "s3:if-none-match": "*" } } }));
    fn.addToRolePolicy(new iam.PolicyStatement({ actions: ["s3:PutObject"],
      resources: [props.bucket.arnForObjects("games/*/characters/*/profile.json")],
      conditions: { Null: { "s3:if-match": "false" } } }));
    const wait = new tasks.LambdaInvoke(this, "WaitForLaptop", {
      lambdaFunction: fn, integrationPattern: sfn.IntegrationPattern.WAIT_FOR_TASK_TOKEN,
      payload: sfn.TaskInput.fromObject({ operation: "dispatch", "jobId.$": "$.jobId",
        taskToken: sfn.JsonPath.taskToken }),
      taskTimeout: sfn.Timeout.duration(Duration.days(30)), resultPath: "$.outcome",
    });
    const expire = new tasks.LambdaInvoke(this, "ExpireJob", {
      lambdaFunction: fn,
      payload: sfn.TaskInput.fromObject({ operation: "expire", "jobId.$": "$.jobId" }),
      resultPath: sfn.JsonPath.DISCARD,
    });
    wait.addCatch(expire.next(new sfn.Fail(this, "Expired")), { resultPath: "$.failure" });
    const machine = new sfn.StateMachine(this, "Workflow", {
      definitionBody: sfn.DefinitionBody.fromChainable(wait.next(new sfn.Choice(this, "Published")
        .when(sfn.Condition.stringEquals("$.outcome.status", "PUBLISHED"), new sfn.Succeed(this, "Finished"))
        .otherwise(new sfn.Fail(this, "NotPublished", { cause: "Inspect the Panther job for failure, conflict, or supersession" })))),
      stateMachineType: sfn.StateMachineType.STANDARD,
      timeout: Duration.days(31),
    });
    // Separate stream consumer avoids a role/function/state-machine dependency cycle.
    const trigger = new lambda.Function(this, "Trigger", {
      runtime: lambda.Runtime.PYTHON_3_13, architecture: lambda.Architecture.ARM_64,
      handler: "model_jobs.stream", code,
      memorySize: 128, timeout: Duration.seconds(30), logGroup,
      environment: { ASSET_BUCKET_NAME: props.bucket.bucketName, JOB_TABLE: table.tableName,
        STATE_MACHINE_ARN: machine.stateMachineArn },
    });
    table.grantReadData(trigger);
    machine.grantStartExecution(trigger);
    trigger.addToRolePolicy(new iam.PolicyStatement({ actions: ["states:SendTaskSuccess"], resources: ["*"] }));
    trigger.addEventSource(new sources.DynamoEventSource(table, {
      startingPosition: lambda.StartingPosition.TRIM_HORIZON, batchSize: 10,
      bisectBatchOnError: true, reportBatchItemFailures: true,
      // Retain/retry failed outbox records for the stream's 24-hour lifetime.
      retryAttempts: -1,
    }));
    const integration = new integrations.HttpLambdaIntegration("ModelJobsIntegration", fn);
    for (const route of ["/model-reference-sets", "/model-jobs/claim", "/model-jobs/heartbeat",
      "/model-jobs/defer", "/model-jobs/complete"]) {
      props.api.addRoutes({ path: route, methods: [api.HttpMethod.POST], integration, authorizer: props.authorizer });
    }
    props.api.addRoutes({ path: "/model-jobs", methods: [api.HttpMethod.GET], integration, authorizer: props.authorizer });
  }
}
