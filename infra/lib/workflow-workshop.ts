import * as fs from "node:fs";
import * as path from "node:path";
import {Duration, RemovalPolicy} from "aws-cdk-lib";
import {Construct} from "constructs";
import * as api from "aws-cdk-lib/aws-apigatewayv2";
import * as integrations from "aws-cdk-lib/aws-apigatewayv2-integrations";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as sources from "aws-cdk-lib/aws-lambda-event-sources";
import * as logs from "aws-cdk-lib/aws-logs";

/** Read-time views never enumerate source storage or invoke a worker. */
export class WorkflowWorkshop extends Construct {
  constructor(scope:Construct,id:string,props:{api:api.HttpApi;authorizer:api.IHttpRouteAuthorizer;accessEnvironment:Record<string,string>;tables:Record<string,dynamodb.Table>}) {
    super(scope,id);
    const index=new dynamodb.Table(this,"Index",{
      partitionKey:{name:"pk",type:dynamodb.AttributeType.STRING},sortKey:{name:"sk",type:dynamodb.AttributeType.STRING},
      billingMode:dynamodb.BillingMode.PAY_PER_REQUEST,encryption:dynamodb.TableEncryption.AWS_MANAGED,removalPolicy:RemovalPolicy.RETAIN,
    });
    const environment={...props.accessEnvironment,WORKSHOP_TABLE:index.tableName,
      WORKSHOP_SOURCES:JSON.stringify(Object.fromEntries(Object.entries(props.tables).map(([kind,table])=>[kind,{name:table.tableName,arn:table.tableArn}]))),
      WORKSHOP_PLAN:fs.readFileSync(path.join(__dirname,"../../../src/panther_journal/editorial-plan.json"),"utf8")};
    const code=lambda.Code.fromAsset(path.join(__dirname,"../../lambda/media-api"),{exclude:["**/__pycache__/**","**/*.pyc"]});
    const create=(name:string,handler:string)=>new lambda.Function(this,name,{runtime:lambda.Runtime.PYTHON_3_13,architecture:lambda.Architecture.ARM_64,code,handler,environment,timeout:Duration.seconds(60),memorySize:256,logGroup:new logs.LogGroup(this,name+"Logs",{retention:logs.RetentionDays.ONE_MONTH})});
    const reader=create("Reader","workflow_workshop.handler");
    index.grant(reader,"dynamodb:GetItem","dynamodb:Query","dynamodb:PutItem");
    const writer=create("Projection","workflow_workshop.project_handler");
    index.grantReadWriteData(writer);
    for(const table of Object.values(props.tables)) {
      table.grant(writer,"dynamodb:GetItem","dynamodb:Query","dynamodb:Scan");
      writer.addEventSource(new sources.DynamoEventSource(table,{startingPosition:lambda.StartingPosition.TRIM_HORIZON,batchSize:10,bisectBatchOnError:true,reportBatchItemFailures:true,retryAttempts:-1}));
    }
    const view=new integrations.HttpLambdaIntegration("WorkshopView",reader);
    props.api.addRoutes({path:"/workflows",methods:[api.HttpMethod.GET],authorizer:props.authorizer,integration:view});
    props.api.addRoutes({path:"/workflow-progress",methods:[api.HttpMethod.POST],authorizer:props.authorizer,integration:view});
    props.api.addRoutes({path:"/workflows/rebuild",methods:[api.HttpMethod.POST],authorizer:props.authorizer,integration:new integrations.HttpLambdaIntegration("WorkshopRebuild",writer)});
  }
}
