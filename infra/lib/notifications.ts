import * as path from "node:path";
import {Duration,NestedStack,RemovalPolicy} from "aws-cdk-lib";
import {Construct} from "constructs";
import * as api from "aws-cdk-lib/aws-apigatewayv2";
import * as integrations from "aws-cdk-lib/aws-apigatewayv2-integrations";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as sources from "aws-cdk-lib/aws-lambda-event-sources";
import * as logs from "aws-cdk-lib/aws-logs";

export class Notifications extends NestedStack {
 constructor(scope:Construct,id:string,props:{api:api.HttpApi;authorizer:api.IHttpRouteAuthorizer;environment:Record<string,string>;index:dynamodb.Table}){
  super(scope,id);
  const table=new dynamodb.Table(this,"History",{partitionKey:{name:"pk",type:dynamodb.AttributeType.STRING},sortKey:{name:"sk",type:dynamodb.AttributeType.STRING},billingMode:dynamodb.BillingMode.PAY_PER_REQUEST,encryption:dynamodb.TableEncryption.AWS_MANAGED,removalPolicy:RemovalPolicy.RETAIN});
  const code=lambda.Code.fromAsset(path.join(__dirname,"../../lambda/media-api"),{exclude:["**/__pycache__/**","**/*.pyc"]});
  const create=(name:string,handler:string)=>new lambda.Function(this,name,{runtime:lambda.Runtime.PYTHON_3_13,architecture:lambda.Architecture.ARM_64,code,handler,environment:{...props.environment,NOTIFICATIONS_TABLE:table.tableName},timeout:Duration.seconds(60),memorySize:256,logGroup:new logs.LogGroup(this,name+"Logs",{retention:logs.RetentionDays.ONE_MONTH})});
  const reader=create("Api","notifications.handler"),writer=create("Projection","notifications.project_handler");
  table.grant(reader,"dynamodb:GetItem","dynamodb:Query","dynamodb:UpdateItem","dynamodb:DeleteItem");
  table.grant(writer,"dynamodb:GetItem","dynamodb:PutItem");
  props.index.grant(writer,"dynamodb:Scan","dynamodb:GetItem");
  writer.addEventSource(new sources.DynamoEventSource(props.index,{startingPosition:lambda.StartingPosition.TRIM_HORIZON,batchSize:10,bisectBatchOnError:true,reportBatchItemFailures:true,retryAttempts:-1}));
  const view=new integrations.HttpLambdaIntegration("Notifications",reader),backfill=new integrations.HttpLambdaIntegration("NotificationBackfill",writer);
  for(const [name,url,method,integration]of [["List","/notifications",api.HttpMethod.GET,view],["Read","/notifications/read",api.HttpMethod.POST,view],["Rebuild","/notifications/rebuild",api.HttpMethod.POST,backfill]]as const){
   new api.HttpRoute(this,name,{httpApi:props.api,routeKey:api.HttpRouteKey.with(url,method),authorizer:props.authorizer,integration});
  }
 }
}
