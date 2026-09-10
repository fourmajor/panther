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

/** A completed set is the durable outbox event; individual uploads never start assembly. */
export class PlaybackProcessing extends Construct {
  constructor(scope: Construct, id: string, props: {
    bucket: s3.IBucket; api: api.HttpApi; authorizer: api.IHttpRouteAuthorizer;
  }) {
    super(scope, id);
    const table = new dynamodb.Table(this, "Sets", {
      partitionKey: { name: "pk", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "sk", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      stream: dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,
      encryption: dynamodb.TableEncryption.AWS_MANAGED, removalPolicy: RemovalPolicy.RETAIN,
    });
    const code = lambda.Code.fromAsset(path.join(__dirname, "../../lambda/media-api"), {
      exclude: ["**/__pycache__/**", "**/*.pyc"],
    });
    const environment = { ASSET_BUCKET_NAME: props.bucket.bucketName, PLAYBACK_TABLE: table.tableName };
    const broker = new lambda.Function(this, "Broker", {
      runtime: lambda.Runtime.PYTHON_3_13, architecture: lambda.Architecture.ARM_64,
      handler: "playback_jobs.handler", code, environment,
      memorySize: 256, timeout: Duration.seconds(60),
      logGroup: new logs.LogGroup(this, "Logs", { retention: logs.RetentionDays.ONE_MONTH }),
    });
    table.grantReadWriteData(broker);
    props.bucket.grantRead(broker, "games/*");
    const failure = new tasks.LambdaInvoke(this, "RecordFailure", {
      lambdaFunction: broker, payload: sfn.TaskInput.fromObject({ operation: "fail", "jobId.$": "$.jobId" }),
      resultPath: sfn.JsonPath.DISCARD,
    }).next(new sfn.Fail(this, "PlaybackFailed"));
    const assemble = new tasks.LambdaInvoke(this, "AssembleAndVerifyOnLaptop", {
      lambdaFunction: broker, integrationPattern: sfn.IntegrationPattern.WAIT_FOR_TASK_TOKEN,
      payload: sfn.TaskInput.fromObject({ operation: "dispatch", "jobId.$": "$.jobId", taskToken: sfn.JsonPath.taskToken }),
      taskTimeout: sfn.Timeout.duration(Duration.days(30)), resultPath: "$.outcome",
    });
    assemble.addCatch(failure, { resultPath: "$.failure" });
    const gate = new sfn.Choice(this, "VerifiedPlaybackPublished")
      .when(sfn.Condition.stringEquals("$.outcome.status", "DONE"), new sfn.Succeed(this, "PlaybackReady"))
      .otherwise(failure);
    const machine = new sfn.StateMachine(this, "Workflow", {
      definitionBody: sfn.DefinitionBody.fromChainable(assemble.next(gate)),
      stateMachineType: sfn.StateMachineType.STANDARD, timeout: Duration.days(31),
    });
    const trigger = new lambda.Function(this, "Trigger", {
      runtime: lambda.Runtime.PYTHON_3_13, architecture: lambda.Architecture.ARM_64,
      handler: "playback_jobs.stream", code, memorySize: 128, timeout: Duration.seconds(30),
      environment: { ...environment, STATE_MACHINE_ARN: machine.stateMachineArn },
      logGroup: new logs.LogGroup(this, "TriggerLogs", { retention: logs.RetentionDays.ONE_MONTH }),
    });
    machine.grantStartExecution(trigger);
    trigger.addToRolePolicy(new iam.PolicyStatement({ actions: ["states:SendTaskSuccess"], resources: ["*"] }));
    trigger.addEventSource(new sources.DynamoEventSource(table, {
      startingPosition: lambda.StartingPosition.TRIM_HORIZON, batchSize: 10,
      bisectBatchOnError: true, reportBatchItemFailures: true, retryAttempts: -1,
    }));
    const integration = new integrations.HttpLambdaIntegration("PlaybackIntegration", broker);
    for (const route of ["/recording-sets/complete", "/recording-playback-jobs/claim",
      "/recording-playback-jobs/heartbeat", "/recording-playback-jobs/complete"]) {
      props.api.addRoutes({ path: route, methods: [api.HttpMethod.POST], integration, authorizer: props.authorizer });
    }
    props.api.addRoutes({ path: "/recording-playback-jobs", methods: [api.HttpMethod.GET], integration, authorizer: props.authorizer });
  }
}
