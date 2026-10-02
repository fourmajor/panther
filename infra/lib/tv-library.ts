import * as path from "node:path";
import { Duration } from "aws-cdk-lib";
import { Construct } from "constructs";
import * as api from "aws-cdk-lib/aws-apigatewayv2";
import * as integrations from "aws-cdk-lib/aws-apigatewayv2-integrations";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as logs from "aws-cdk-lib/aws-logs";
import * as s3 from "aws-cdk-lib/aws-s3";

export class TVLibrary extends Construct {
  constructor(scope:Construct,id:string,props:{api:api.HttpApi;authorizer:api.IHttpRouteAuthorizer;
    bucket:s3.IBucket;browseTable:dynamodb.ITable;catalogTable:dynamodb.ITable;publishers:string}){
    super(scope,id);
    const fn=new lambda.Function(this,"Api",{runtime:lambda.Runtime.PYTHON_3_13,architecture:lambda.Architecture.ARM_64,
      handler:"tv_library.handler",code:lambda.Code.fromAsset(path.join(__dirname,"../../lambda/media-api"),{exclude:["**/__pycache__/**","**/*.pyc"]}),
      environment:{ASSET_BUCKET_NAME:props.bucket.bucketName,ASSET_BROWSE_TABLE:props.browseTable.tableName,
        CATALOG_TABLE:props.catalogTable.tableName,MODEL_PUBLISHERS:props.publishers},memorySize:256,timeout:Duration.seconds(30),
      logGroup:new logs.LogGroup(this,"Logs",{retention:logs.RetentionDays.ONE_MONTH})});
    props.browseTable.grant(fn,"dynamodb:GetItem","dynamodb:Query","dynamodb:BatchGetItem");
    fn.addToRolePolicy(new iam.PolicyStatement({actions:["dynamodb:GetItem"],resources:[props.catalogTable.tableArn],
      conditions:{"ForAllValues:StringEquals":{"dynamodb:LeadingKeys":["GAMES"]}}}));
    const integration=new integrations.HttpLambdaIntegration("Integration",fn);
    for(const route of ["/tv-series","/tv-episodes"])props.api.addRoutes({path:route,methods:[api.HttpMethod.GET],integration,authorizer:props.authorizer});
  }
}
