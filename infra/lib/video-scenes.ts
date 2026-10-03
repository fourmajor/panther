import {AssetArchive} from "./asset-archive";
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

export class VideoScenes extends Construct {
  constructor(scope: Construct, id: string, props: {api: api.HttpApi; authorizer: api.IHttpRouteAuthorizer;
    bucket: s3.IBucket; browseTable: dynamodb.ITable; catalogTable: dynamodb.ITable; accessEnvironment: Record<string,string>}) {
    super(scope,id);
    const fn = new lambda.Function(this,"Api",{runtime:lambda.Runtime.PYTHON_3_13,architecture:lambda.Architecture.ARM_64,
      handler:"video_scenes.handler",code:lambda.Code.fromAsset(path.join(__dirname,"../../lambda/media-api"),{exclude:["**/__pycache__/**","**/*.pyc"]}),
      environment:{ASSET_BUCKET_NAME:props.bucket.bucketName,ASSET_BROWSE_TABLE:props.browseTable.tableName,CATALOG_TABLE:props.catalogTable.tableName,
        CATALOG_READERS:props.accessEnvironment.CATALOG_READERS,MODEL_PUBLISHERS:props.accessEnvironment.MODEL_PUBLISHERS,ASSET_MIGRATORS:props.accessEnvironment.ASSET_MIGRATORS},
      memorySize:128,timeout:Duration.seconds(30),logGroup:new logs.LogGroup(this,"Logs",{retention:logs.RetentionDays.ONE_MONTH})});
    AssetArchive.grantReferenceWrites(fn,props.browseTable);
    props.browseTable.grant(fn,"dynamodb:GetItem","dynamodb:Query");
    fn.addToRolePolicy(new iam.PolicyStatement({actions:["dynamodb:PutItem"],resources:[props.browseTable.tableArn],conditions:{"ForAllValues:StringLike":{"dynamodb:LeadingKeys":["episode-scenes-v1#*","episode-scenes-v1-history#*","episode-scenes-v1-ops#*","episode-scenes-migration-v1#*"]}}}));
    fn.addToRolePolicy(new iam.PolicyStatement({actions:["dynamodb:ConditionCheckItem"],resources:[props.browseTable.tableArn],conditions:{"ForAllValues:StringLike":{"dynamodb:LeadingKeys":["episode-scenes-v1#episode#*","episode-scenes-v1#scene#*","v4#*#all","tv-library#episode#*"]}}}));
    fn.addToRolePolicy(new iam.PolicyStatement({actions:["dynamodb:GetItem","dynamodb:Query"],resources:[props.catalogTable.tableArn],conditions:{"ForAllValues:StringEquals":{"dynamodb:LeadingKeys":["GAMES"]}}}));
    fn.addToRolePolicy(new iam.PolicyStatement({actions:["dynamodb:GetItem"],resources:[props.catalogTable.tableArn],conditions:{"ForAllValues:StringLike":{"dynamodb:LeadingKeys":["GAME#*"]}}}));
    const integration = new integrations.HttpLambdaIntegration("Integration",fn);
    props.api.addRoutes({path:"/video-workspace/migrate",methods:[api.HttpMethod.POST],integration,authorizer:props.authorizer});
    props.api.addRoutes({path:"/episode-composition",methods:[api.HttpMethod.GET],integration,authorizer:props.authorizer});
    for(const route of ["/episodes","/scenes"])props.api.addRoutes({path:route,methods:[api.HttpMethod.GET,api.HttpMethod.POST],integration,authorizer:props.authorizer});
  }
}
