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

/** Versioned private appearance metadata, never an inference service or idle worker. */
export class CharacterAppearances extends Construct {
  static grantProducer(fn: lambda.Function, browse: dynamodb.ITable, catalog: dynamodb.ITable) {
    fn.addEnvironment("ASSET_BROWSE_TABLE",browse.tableName);
    fn.addEnvironment("CATALOG_TABLE",catalog.tableName);
    browse.grant(fn,"dynamodb:GetItem","dynamodb:Query","dynamodb:BatchGetItem");
    fn.addToRolePolicy(new iam.PolicyStatement({actions:["dynamodb:PutItem"],resources:[browse.tableArn],
      conditions:{"ForAllValues:StringLike":{"dynamodb:LeadingKeys":["character-looks#*","character-looks-history#*","character-looks-ops#*","character-looks-migration#*"]}}}));
    fn.addToRolePolicy(new iam.PolicyStatement({actions:["dynamodb:ConditionCheckItem"],resources:[browse.tableArn],
      conditions:{"ForAllValues:StringLike":{"dynamodb:LeadingKeys":["character-looks#*","character-looks-migration#*","v3#*#all"]}}}));
    fn.addToRolePolicy(new iam.PolicyStatement({actions:["dynamodb:GetItem","dynamodb:ConditionCheckItem"],resources:[catalog.tableArn],
      conditions:{"ForAllValues:StringLike":{"dynamodb:LeadingKeys":["GAME#*"]}}}));
  }
  constructor(scope: Construct, id: string, props: {
    api: api.HttpApi; authorizer: api.IHttpRouteAuthorizer; bucket: s3.IBucket;
    browseTable: dynamodb.ITable; catalogTable: dynamodb.ITable;
    accessEnvironment: Record<string,string>;
  }) {
    super(scope,id);
    const fn = new lambda.Function(this,"Api",{
      runtime:lambda.Runtime.PYTHON_3_13, architecture:lambda.Architecture.ARM_64,
      handler:"character_appearances.handler", memorySize:256, timeout:Duration.seconds(30),
      code:lambda.Code.fromAsset(path.join(__dirname,"../../lambda/media-api"),{exclude:["**/__pycache__/**","**/*.pyc"]}),
      logGroup:new logs.LogGroup(this,"Logs",{retention:logs.RetentionDays.ONE_MONTH}),
      environment:{ASSET_BUCKET_NAME:props.bucket.bucketName, ASSET_BROWSE_TABLE:props.browseTable.tableName,
        CATALOG_TABLE:props.catalogTable.tableName, MODEL_PUBLISHERS:props.accessEnvironment.MODEL_PUBLISHERS,
        ASSET_MIGRATORS:props.accessEnvironment.ASSET_MIGRATORS},
    });
    props.browseTable.grant(fn,"dynamodb:GetItem","dynamodb:Query","dynamodb:BatchGetItem");
    props.bucket.grantRead(fn,"games/*");
    fn.addToRolePolicy(new iam.PolicyStatement({actions:["dynamodb:PutItem"],resources:[props.browseTable.tableArn],
      conditions:{"ForAllValues:StringLike":{"dynamodb:LeadingKeys":["character-looks#*","character-looks-history#*","character-looks-ops#*","character-looks-migration#*"]}}}));
    fn.addToRolePolicy(new iam.PolicyStatement({actions:["dynamodb:ConditionCheckItem"],resources:[props.browseTable.tableArn],
      conditions:{"ForAllValues:StringLike":{"dynamodb:LeadingKeys":["character-looks#*","character-looks-migration#*","v3#*#all"]}}}));
    fn.addToRolePolicy(new iam.PolicyStatement({actions:["dynamodb:GetItem","dynamodb:ConditionCheckItem"],resources:[props.catalogTable.tableArn],
      conditions:{"ForAllValues:StringLike":{"dynamodb:LeadingKeys":["GAME#*"]}}}));
    fn.addToRolePolicy(new iam.PolicyStatement({actions:["dynamodb:GetItem"],resources:[props.catalogTable.tableArn],
      conditions:{"ForAllValues:StringEquals":{"dynamodb:LeadingKeys":["GAMES"]}}}));
    const integration=new integrations.HttpLambdaIntegration("Integration",fn);
    for(const route of ["/character-appearances","/character-appearance-assets","/character-selections","/character-appearance-current"])
      props.api.addRoutes({path:route,methods:[api.HttpMethod.GET,api.HttpMethod.POST],integration,authorizer:props.authorizer});
    props.api.addRoutes({path:"/character-appearance-view",methods:[api.HttpMethod.GET],integration,authorizer:props.authorizer});
    for(const operation of ["inventory","game-inventory"])
      props.api.addRoutes({path:`/character-appearance-migration/${operation}`,methods:[api.HttpMethod.GET],integration,authorizer:props.authorizer});
    for(const operation of ["prepare","apply","verify","finalize"])
      props.api.addRoutes({path:`/character-appearance-migration/${operation}`,methods:[api.HttpMethod.POST],integration,authorizer:props.authorizer});
  }
}
