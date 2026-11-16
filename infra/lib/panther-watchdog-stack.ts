import { CfnOutput, Duration, Stack, StackProps, Tags } from "aws-cdk-lib";
import * as iam from "aws-cdk-lib/aws-iam";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as ssm from "aws-cdk-lib/aws-ssm";
import { Construct } from "constructs";

/** Read-only IAM user and role for unattended pipeline watchdog checks.
 * Access keys are created out of band so the secret never enters CloudFormation. */
export class PantherWatchdogStack extends Stack {
  constructor(scope: Construct, id: string, props?: StackProps) {
    super(scope, id, props);

    Tags.of(this).add("Project", "Panther");
    Tags.of(this).add("ManagedBy", "AWS-CDK");
    Tags.of(this).add("Environment", "production");

    const privateAssets = s3.Bucket.fromBucketName(
      this,
      "PrivateAssets",
      ssm.StringParameter.valueForStringParameter(this, "/panther/foundation/private-asset-bucket"),
    );
    const publishedAssets = s3.Bucket.fromBucketName(
      this,
      "PublishedAssets",
      ssm.StringParameter.valueForStringParameter(this, "/panther/foundation/published-asset-bucket"),
    );
    const buckets = [privateAssets, publishedAssets];

    const user = new iam.User(this, "User", {
      userName: "panther-watchdog",
    });

    const role = new iam.Role(this, "Role", {
      roleName: "PantherWatchdogReadOnly",
      description: "Read-only Panther pipeline watchdog: Step Functions, asset buckets, logs, and CloudWatch",
      maxSessionDuration: Duration.hours(1),
      assumedBy: new iam.ArnPrincipal(user.userArn),
    });

    role.addToPolicy(new iam.PolicyStatement({
      sid: "StateMachinesRead",
      actions: ["states:List*", "states:Describe*", "states:GetExecutionHistory"],
      resources: ["*"],
    }));
    role.addToPolicy(new iam.PolicyStatement({
      sid: "AssetBucketsList",
      actions: ["s3:GetBucketLocation", "s3:ListBucket"],
      resources: buckets.map((bucket) => bucket.bucketArn),
    }));
    role.addToPolicy(new iam.PolicyStatement({
      sid: "AssetObjectsRead",
      actions: ["s3:GetObject"],
      resources: buckets.map((bucket) => bucket.arnForObjects("*")),
    }));
    role.addToPolicy(new iam.PolicyStatement({
      sid: "LogGroupsDescribe",
      actions: ["logs:DescribeLogGroups", "logs:DescribeQueries", "logs:DescribeQueryDefinitions"],
      resources: ["*"],
    }));
    role.addToPolicy(new iam.PolicyStatement({
      sid: "PipelineLogsRead",
      actions: [
        "logs:DescribeLogStreams",
        "logs:GetLogEvents",
        "logs:FilterLogEvents",
        "logs:StartQuery",
        "logs:StopQuery",
        "logs:GetQueryResults",
      ],
      resources: [
        `arn:${this.partition}:logs:${this.region}:${this.account}:log-group:Panther*`,
        `arn:${this.partition}:logs:${this.region}:${this.account}:log-group:Panther*:log-stream:*`,
        `arn:${this.partition}:logs:${this.region}:${this.account}:log-group:/aws/lambda/Panther*`,
        `arn:${this.partition}:logs:${this.region}:${this.account}:log-group:/aws/lambda/Panther*:log-stream:*`,
      ],
    }));
    role.addToPolicy(new iam.PolicyStatement({
      sid: "CloudWatchRead",
      actions: ["cloudwatch:Describe*", "cloudwatch:Get*", "cloudwatch:List*"],
      resources: ["*"],
    }));
    role.addToPolicy(new iam.PolicyStatement({
      sid: "DenyMutations",
      effect: iam.Effect.DENY,
      actions: [
        "states:Create*",
        "states:Update*",
        "states:Delete*",
        "states:Start*",
        "states:Stop*",
        "states:Redrive*",
        "states:SendTask*",
        "states:TestState",
        "s3:Abort*",
        "s3:Create*",
        "s3:Delete*",
        "s3:Put*",
        "s3:Replicate*",
        "s3:RestoreObject",
        "logs:AssociateKmsKey",
        "logs:Create*",
        "logs:Delete*",
        "logs:DisassociateKmsKey",
        "logs:Put*",
        "logs:Tag*",
        "logs:Untag*",
        "cloudwatch:Delete*",
        "cloudwatch:Put*",
        "cloudwatch:Set*",
        "cloudwatch:Tag*",
        "cloudwatch:Untag*",
      ],
      resources: ["*"],
    }));

    user.addToPolicy(new iam.PolicyStatement({
      sid: "AssumeWatchdogRoleOnly",
      actions: ["sts:AssumeRole"],
      resources: [role.roleArn],
    }));

    new CfnOutput(this, "UserArn", { value: user.userArn });
    new CfnOutput(this, "RoleArn", { value: role.roleArn });
  }
}
