import * as fs from "node:fs";
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

/** Each editorial discipline is a durable callback stage, not a Lambda-hosted AI call. */
export class EditorialProcessing extends Construct {
  constructor(scope: Construct, id: string, props: {
    bucket: s3.IBucket; api: api.HttpApi; authorizer: api.IHttpRouteAuthorizer; accessEnvironment: Record<string, string>;
  }) {
    super(scope, id);
    const plan = JSON.parse(fs.readFileSync(path.join(__dirname,
      "../../../src/panther_journal/editorial-plan.json"), "utf8"));
    const table = new dynamodb.Table(this, "Jobs", {
      partitionKey: { name: "pk", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "sk", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      stream: dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,
      encryption: dynamodb.TableEncryption.AWS_MANAGED, removalPolicy: RemovalPolicy.RETAIN,
    });
    const code = lambda.Code.fromAsset(path.join(__dirname, "../../lambda/media-api"), {
      exclude: ["**/__pycache__/**", "**/*.pyc"],
    });
    const environment = { ASSET_BUCKET_NAME: props.bucket.bucketName,
      MODEL_PUBLISHERS: props.accessEnvironment.MODEL_PUBLISHERS, MODEL_WORKERS: props.accessEnvironment.MODEL_WORKERS,
      EDITORIAL_TABLE: table.tableName, EDITORIAL_PLAN: JSON.stringify(plan) };
    const fn = new lambda.Function(this, "Broker", {
      runtime: lambda.Runtime.PYTHON_3_13, architecture: lambda.Architecture.ARM_64,
      handler: "editorial_jobs.handler", code, environment,
      memorySize: 256, timeout: Duration.seconds(60),
      logGroup: new logs.LogGroup(this, "Logs", { retention: logs.RetentionDays.ONE_MONTH }),
    });
    table.grantReadWriteData(fn);
    props.bucket.grantRead(fn, "games/*");
    const failed = new tasks.LambdaInvoke(this, "RecordFailure", {
      lambdaFunction: fn, payload: sfn.TaskInput.fromObject({ operation: "fail", "jobId.$": "$.jobId" }),
      resultPath: sfn.JsonPath.DISCARD,
    }).next(new sfn.Fail(this, "EditorialFailed"));
    const stage = (name: string): sfn.Chain => {
      const wait = new tasks.LambdaInvoke(this, name, {
        lambdaFunction: fn, integrationPattern: sfn.IntegrationPattern.WAIT_FOR_TASK_TOKEN,
        payload: sfn.TaskInput.fromObject({ operation: "dispatch", stage: name,
          "jobId.$": "$.jobId", taskToken: sfn.JsonPath.taskToken }),
        taskTimeout: sfn.Timeout.duration(Duration.days(30)), resultPath: "$.outcome",
      });
      const gate = new sfn.Choice(this, `${name}-gate`)
        .when(sfn.Condition.stringEquals("$.outcome.status", "DONE"), new sfn.Pass(this, `${name}-accepted`))
        .otherwise(new sfn.Fail(this, `${name}-rejected`));
      return wait.next(gate.afterwards());
    };
    const sequence = (names: string[]): sfn.Chain => names.slice(1).reduce(
      (chain, name) => chain.next(stage(name)), stage(names[0]));
    const branches = new sfn.Parallel(this, "Adaptations", { resultPath: sfn.JsonPath.DISCARD })
      .branch(sequence(plan.novel), sequence(plan.video));
    const pipeline = new sfn.Parallel(this, "ProtectedPipeline", { resultPath: sfn.JsonPath.DISCARD })
      .branch(sequence(plan.correction).next(branches));
    pipeline.addCatch(failed, { resultPath: "$.failure" });
    const finish = new tasks.LambdaInvoke(this, "ReadyForVideoDiscussion", {
      lambdaFunction: fn, payload: sfn.TaskInput.fromObject({ operation: "finish", "jobId.$": "$.jobId" }),
      resultPath: sfn.JsonPath.DISCARD,
    });
    const machine = new sfn.StateMachine(this, "Workflow", {
      definitionBody: sfn.DefinitionBody.fromChainable(pipeline.next(finish)
        .next(new sfn.Succeed(this, "VideoGenerationNotAuthorized"))),
      stateMachineType: sfn.StateMachineType.STANDARD, timeout: Duration.days(31),
    });
    const trigger = new lambda.Function(this, "Trigger", {
      runtime: lambda.Runtime.PYTHON_3_13, architecture: lambda.Architecture.ARM_64,
      handler: "editorial_jobs.stream", code, memorySize: 128, timeout: Duration.seconds(30),
      environment: { ...environment, STATE_MACHINE_ARN: machine.stateMachineArn },
      logGroup: new logs.LogGroup(this, "TriggerLogs", { retention: logs.RetentionDays.ONE_MONTH }),
    });
    table.grantReadData(trigger);
    machine.grantStartExecution(trigger);
    trigger.addToRolePolicy(new iam.PolicyStatement({ actions: ["states:SendTaskSuccess"], resources: ["*"] }));
    trigger.addEventSource(new sources.DynamoEventSource(table, {
      startingPosition: lambda.StartingPosition.TRIM_HORIZON, batchSize: 10,
      bisectBatchOnError: true, reportBatchItemFailures: true, retryAttempts: -1,
    }));
    const integration = new integrations.HttpLambdaIntegration("EditorialIntegration", fn);
    for (const route of ["/editorial-jobs", "/editorial-jobs/claim", "/editorial-jobs/heartbeat",
      "/editorial-jobs/defer", "/editorial-jobs/complete"]) {
      props.api.addRoutes({ path: route, methods: [api.HttpMethod.POST], integration, authorizer: props.authorizer });
    }
    for (const route of ["/editorial-jobs", "/editorial-context"]) {
      props.api.addRoutes({ path: route, methods: [api.HttpMethod.GET], integration, authorizer: props.authorizer });
    }
    // Reading a novel never needs the broker's write or workflow permissions.
    const reader = new lambda.Function(this, "NovelReader", {
      runtime: lambda.Runtime.PYTHON_3_13, architecture: lambda.Architecture.ARM_64,
      handler: "novel.handler", code, environment,
      memorySize: 256, timeout: Duration.seconds(30),
      logGroup: new logs.LogGroup(this, "NovelReaderLogs", { retention: logs.RetentionDays.ONE_MONTH }),
    });
    table.grantReadData(reader);
    props.bucket.grantRead(reader, "games/*");
    const novelIntegration = new integrations.HttpLambdaIntegration("NovelIntegration", reader);
    for (const route of ["/novel", "/novel-chapter"]) {
      props.api.addRoutes({ path: route, methods: [api.HttpMethod.GET], integration: novelIntegration, authorizer: props.authorizer });
    }
    // Review decisions cannot dispatch jobs or spend. Retain immutable revision-specific audit rows.
    const reviews = new dynamodb.Table(this, "MovieReviews", {
      partitionKey: { name: "pk", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "sk", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      encryption: dynamodb.TableEncryption.AWS_MANAGED, removalPolicy: RemovalPolicy.RETAIN,
    });
    const movieReview = new lambda.Function(this, "MovieReview", {
      runtime: lambda.Runtime.PYTHON_3_13, architecture: lambda.Architecture.ARM_64,
      handler: "movie_review.handler", code,
      environment: { ASSET_BUCKET_NAME: props.bucket.bucketName,
        MODEL_PUBLISHERS: props.accessEnvironment.MODEL_PUBLISHERS,
        MODEL_WORKERS: props.accessEnvironment.MODEL_WORKERS, MOVIE_REVIEW_TABLE: reviews.tableName },
      memorySize: 256, timeout: Duration.seconds(30),
      logGroup: new logs.LogGroup(this, "MovieReviewLogs", { retention: logs.RetentionDays.ONE_MONTH }),
    });
    movieReview.addToRolePolicy(new iam.PolicyStatement({
      actions: ["dynamodb:GetItem", "dynamodb:PutItem"], resources: [reviews.tableArn],
    }));
    props.bucket.grantRead(movieReview, "games/*");
    const reviewIntegration = new integrations.HttpLambdaIntegration("MovieReviewIntegration", movieReview);
    props.api.addRoutes({ path: "/movie-review", methods: [api.HttpMethod.GET, api.HttpMethod.POST],
      integration: reviewIntegration, authorizer: props.authorizer });
  }
}
