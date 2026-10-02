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
import * as sqs from "aws-cdk-lib/aws-sqs";
import * as secrets from "aws-cdk-lib/aws-secretsmanager";

/** Optional, explicitly configured API transcription; no key or provider token reaches browsers. */
export class BrowserRecordings extends Construct {
  readonly table: dynamodb.Table;
  constructor(scope: Construct, id: string, props: {
    bucket:s3.IBucket; api:api.HttpApi; authorizer:api.IHttpRouteAuthorizer;
    accessEnvironment:Record<string,string>; playbackTable:dynamodb.ITable;
    secretArn?:string;
  }) {
    super(scope,id);
    if (props.secretArn && !/^arn:aws:secretsmanager:us-west-2:[0-9]{12}:secret:[A-Za-z0-9/_+=.@-]+$/.test(props.secretArn)) throw new Error("Browser transcription requires a us-west-2 Secrets Manager ARN");
    const table = this.table = new dynamodb.Table(this,"Jobs",{
      partitionKey:{name:"pk",type:dynamodb.AttributeType.STRING},sortKey:{name:"sk",type:dynamodb.AttributeType.STRING},
      billingMode:dynamodb.BillingMode.PAY_PER_REQUEST,stream:dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,
      encryption:dynamodb.TableEncryption.AWS_MANAGED,removalPolicy:RemovalPolicy.RETAIN,
    });
    const dead = new sqs.Queue(this,"Failures",{retentionPeriod:Duration.days(14)});
    const queue = new sqs.Queue(this,"Queue",{visibilityTimeout:Duration.minutes(31),retentionPeriod:Duration.days(4),deadLetterQueue:{queue:dead,maxReceiveCount:4}});
    const code=lambda.Code.fromAsset(path.join(__dirname,"../../lambda/media-api"),{exclude:["**/__pycache__/**","**/*.pyc"]});
    const environment={...props.accessEnvironment,ASSET_BUCKET_NAME:props.bucket.bucketName,
      PLAYBACK_TABLE:props.playbackTable.tableName,BROWSER_TRANSCRIPTION_TABLE:table.tableName,
      OPENAI_TRANSCRIPTION_SECRET_ARN:props.secretArn || "",BROWSER_TRANSCRIPTION_QUEUE:queue.queueUrl};
    const create=(name:string,handler:string,timeout:number,memorySize:number)=>new lambda.Function(this,name,{
      runtime:lambda.Runtime.PYTHON_3_13,architecture:lambda.Architecture.ARM_64,handler,code,environment,memorySize,
      timeout:Duration.seconds(timeout),logGroup:new logs.LogGroup(this,name+"Logs",{retention:logs.RetentionDays.ONE_MONTH}),
    });
    const broker=create("Api","browser_transcription.handler",60,256);
    table.grantReadWriteData(broker); props.playbackTable.grantReadData(broker); broker.addToRolePolicy(new iam.PolicyStatement({actions:["dynamodb:PutItem"],resources:[props.playbackTable.tableArn],conditions:{"ForAllValues:StringEquals":{"dynamodb:LeadingKeys":["SETS"]}}})); props.bucket.grantRead(broker,"games/*");
    const outbox=create("Outbox","browser_transcription.enqueue",30,128);
    outbox.addEventSource(new sources.DynamoEventSource(table,{startingPosition:lambda.StartingPosition.TRIM_HORIZON,batchSize:10,bisectBatchOnError:true,reportBatchItemFailures:true,retryAttempts:-1}));
    queue.grantSendMessages(outbox);
    const worker=create("Worker","browser_transcription.work",300,512);
    table.grantReadWriteData(worker); props.bucket.grantRead(worker,"games/*");
    worker.addToRolePolicy(new iam.PolicyStatement({actions:["s3:PutObject"],resources:[props.bucket.arnForObjects("games/*/catalog/assets/browser-asr-*/*"),props.bucket.arnForObjects("games/*/content/*/browser-asr-*/*")],conditions:{Null:{"s3:if-none-match":"false"}}}));
    if(props.secretArn) secrets.Secret.fromSecretCompleteArn(this,"OpenAI",props.secretArn).grantRead(worker);
    worker.addEventSource(new sources.SqsEventSource(queue,{batchSize:1,reportBatchItemFailures:true,maxConcurrency:2}));
    const integration=new integrations.HttpLambdaIntegration("BrowserRecordingIntegration",broker);
    props.api.addRoutes({path:"/browser-recording/capabilities",methods:[api.HttpMethod.GET],integration,authorizer:props.authorizer});
    props.api.addRoutes({path:"/browser-recording/complete",methods:[api.HttpMethod.POST],integration,authorizer:props.authorizer});
    props.api.addRoutes({path:"/browser-transcriptions",methods:[api.HttpMethod.GET,api.HttpMethod.POST],integration,authorizer:props.authorizer});
  }
}
