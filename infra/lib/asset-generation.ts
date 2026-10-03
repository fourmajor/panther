import * as path from "node:path";
import { Duration, RemovalPolicy } from "aws-cdk-lib";
import { Construct } from "constructs";
import * as api from "aws-cdk-lib/aws-apigatewayv2";
import * as integrations from "aws-cdk-lib/aws-apigatewayv2-integrations";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as logs from "aws-cdk-lib/aws-logs";

/** AWS stores requests; subscription-backed image inference runs only on the laptop. */
export class AssetGeneration extends Construct {
  constructor(scope: Construct, id: string, props: {api: api.HttpApi; authorizer: api.IHttpRouteAuthorizer;
    bucket:s3.IBucket; catalogTable: dynamodb.ITable; accessEnvironment: Record<string,string>}) {
    super(scope,id);
    const jobs = new dynamodb.Table(this,"Jobs",{partitionKey:{name:"pk",type:dynamodb.AttributeType.STRING},
      sortKey:{name:"sk",type:dynamodb.AttributeType.STRING},billingMode:dynamodb.BillingMode.PAY_PER_REQUEST,
      encryption:dynamodb.TableEncryption.AWS_MANAGED,removalPolicy:RemovalPolicy.RETAIN});
    jobs.addGlobalSecondaryIndex({indexName:"StatusIndex",partitionKey:{name:"status",type:dynamodb.AttributeType.STRING},
      sortKey:{name:"createdAt",type:dynamodb.AttributeType.NUMBER},projectionType:dynamodb.ProjectionType.ALL});
    jobs.addGlobalSecondaryIndex({indexName:"GameIndex",partitionKey:{name:"gameId",type:dynamodb.AttributeType.STRING},
      sortKey:{name:"createdAt",type:dynamodb.AttributeType.NUMBER},projectionType:dynamodb.ProjectionType.ALL});
    const fn = new lambda.Function(this,"Api",{runtime:lambda.Runtime.PYTHON_3_13,architecture:lambda.Architecture.ARM_64,
      handler:"asset_generation.handler",code:lambda.Code.fromAsset(path.join(__dirname,"../../lambda/media-api"),{exclude:["**/__pycache__/**","**/*.pyc"]}),
      environment:{ASSET_BUCKET_NAME:props.bucket.bucketName,ASSET_GENERATION_TABLE:jobs.tableName,CATALOG_TABLE:props.catalogTable.tableName,
        CATALOG_READERS:props.accessEnvironment.CATALOG_READERS,MODEL_PUBLISHERS:props.accessEnvironment.MODEL_PUBLISHERS,MODEL_WORKERS:props.accessEnvironment.MODEL_WORKERS},
      memorySize:128,timeout:Duration.seconds(30),logGroup:new logs.LogGroup(this,"Logs",{retention:logs.RetentionDays.ONE_MONTH})});
    jobs.grantReadWriteData(fn);
    props.bucket.grantRead(fn,"games/*");
    props.catalogTable.grant(fn,"dynamodb:GetItem");
    const integration = new integrations.HttpLambdaIntegration("Integration",fn);
    props.api.addRoutes({path:"/asset-generation",methods:[api.HttpMethod.GET,api.HttpMethod.POST],integration,authorizer:props.authorizer});
    for(const action of ["claim","heartbeat","defer","complete","resume"])props.api.addRoutes({path:`/asset-generation/${action}`,
      methods:[api.HttpMethod.POST],integration,authorizer:props.authorizer});
  }
}
