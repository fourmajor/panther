import * as path from 'node:path';
import {Duration} from 'aws-cdk-lib';
import {Construct} from 'constructs';
import * as api from 'aws-cdk-lib/aws-apigatewayv2';
import * as integrations from 'aws-cdk-lib/aws-apigatewayv2-integrations';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as s3 from 'aws-cdk-lib/aws-s3';

/** Archives hide current catalog entries, retaining immutable bytes and historical links. */
export class AssetArchive extends Construct {
  static grantReferenceWrites(fn:lambda.Function,table:dynamodb.ITable){
    fn.addEnvironment('ASSET_BROWSE_TABLE',table.tableName);
    fn.addToRolePolicy(new iam.PolicyStatement({actions:['dynamodb:UpdateItem','dynamodb:PutItem'],resources:[table.tableArn],conditions:{'ForAllValues:StringLike':{'dynamodb:LeadingKeys':['asset-reference-epoch-v1#*','asset-references-v1#*']}}}));
    fn.addToRolePolicy(new iam.PolicyStatement({actions:['dynamodb:ConditionCheckItem'],resources:[table.tableArn],conditions:{'ForAllValues:StringLike':{'dynamodb:LeadingKeys':['asset-archives-v1#*']}}}));
  }
  constructor(scope:Construct,id:string,props:{api:api.HttpApi;authorizer:api.IHttpRouteAuthorizer;bucket:s3.IBucket;browseTable:dynamodb.ITable;jobTables:dynamodb.ITable[];catalogTable:dynamodb.ITable;accessEnvironment:Record<string,string>}){
    super(scope,id);
    const fn=new lambda.Function(this,'Api',{runtime:lambda.Runtime.PYTHON_3_13,architecture:lambda.Architecture.ARM_64,handler:'asset_archive.handler',code:lambda.Code.fromAsset(path.join(__dirname,'../../lambda/media-api'),{exclude:['**/__pycache__/**','**/*.pyc']}),timeout:Duration.seconds(30),memorySize:256,environment:{ASSET_BUCKET_NAME:props.bucket.bucketName,ASSET_BROWSE_TABLE:props.browseTable.tableName,MODEL_PUBLISHERS:props.accessEnvironment.MODEL_PUBLISHERS}});
    props.bucket.grantRead(fn,'games/*');props.browseTable.grant(fn,'dynamodb:GetItem','dynamodb:Query');
    for(const table of props.jobTables)table.grant(fn,'dynamodb:GetItem');
    fn.addToRolePolicy(new iam.PolicyStatement({actions:['dynamodb:PutItem','dynamodb:UpdateItem'],resources:[props.browseTable.tableArn],conditions:{'ForAllValues:StringLike':{'dynamodb:LeadingKeys':['asset-archives-v1#*','asset-archive-ops-v1#*','asset-reference-epoch-v1#*']}}}));
    fn.addToRolePolicy(new iam.PolicyStatement({actions:['dynamodb:DeleteItem'],resources:[props.browseTable.tableArn],conditions:{'ForAllValues:StringLike':{'dynamodb:LeadingKeys':['v4#*#all','v4#*#audio','v4#*#transcripts','v4#*#videos','v4#*#novels']}}}));

    const maintenance=new lambda.Function(this,'Maintenance',{runtime:lambda.Runtime.PYTHON_3_13,architecture:lambda.Architecture.ARM_64,handler:'asset_archive_migration.handler',code:lambda.Code.fromAsset(path.join(__dirname,'../../lambda/media-api'),{exclude:['**/__pycache__/**','**/*.pyc']}),timeout:Duration.seconds(60),memorySize:512,environment:{ASSET_BUCKET_NAME:props.bucket.bucketName,ASSET_BROWSE_TABLE:props.browseTable.tableName,CATALOG_TABLE:props.catalogTable.tableName,MODEL_JOBS_TABLE:props.jobTables[0].tableName,EDITORIAL_TABLE:props.jobTables[1].tableName,ASSET_GENERATION_TABLE:props.jobTables[2].tableName,ASSET_MIGRATORS:props.accessEnvironment.ASSET_MIGRATORS}});
    props.browseTable.grant(maintenance,'dynamodb:GetItem','dynamodb:Query');
    maintenance.addToRolePolicy(new iam.PolicyStatement({actions:['dynamodb:PutItem','dynamodb:UpdateItem','dynamodb:ConditionCheckItem'],resources:[props.browseTable.tableArn],conditions:{'ForAllValues:StringLike':{'dynamodb:LeadingKeys':['asset-reference-epoch-v1#*','asset-references-v1#*','asset-archives-v1#verified','asset-archives-v1#catalog']}}}));
    maintenance.addToRolePolicy(new iam.PolicyStatement({actions:['dynamodb:DeleteItem'],resources:[props.browseTable.tableArn],conditions:{'ForAllValues:StringEquals':{'dynamodb:LeadingKeys':['asset-archives-v1#verified']}}}));
    props.catalogTable.grant(maintenance,'dynamodb:GetItem','dynamodb:Query');for(const table of props.jobTables)table.grant(maintenance,'dynamodb:GetItem','dynamodb:Query');
    props.api.addRoutes({path:'/assets/archive-migration',methods:[api.HttpMethod.POST],integration:new integrations.HttpLambdaIntegration('MaintenanceIntegration',maintenance),authorizer:props.authorizer});
    props.api.addRoutes({path:'/assets/delete',methods:[api.HttpMethod.POST],integration:new integrations.HttpLambdaIntegration('Integration',fn),authorizer:props.authorizer});
  }
}
