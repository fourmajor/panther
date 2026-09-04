import { Duration, RemovalPolicy, Stack, StackProps, Tags } from "aws-cdk-lib";
import * as cr from "aws-cdk-lib/custom-resources";
import * as iam from "aws-cdk-lib/aws-iam";
import * as logs from "aws-cdk-lib/aws-logs";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as sso from "aws-cdk-lib/aws-sso";
import * as ssm from "aws-cdk-lib/aws-ssm";
import { Construct } from "constructs";

export interface PantherAccessStackProps extends StackProps {
  readonly administratorEmail: string;
  readonly identityCenterInstanceArn: string;
  readonly identityStoreId: string;
}

export class PantherAccessStack extends Stack {
  constructor(scope: Construct, id: string, props: PantherAccessStackProps) {
    super(scope, id, props);

    Tags.of(this).add("Project", "Panther");
    Tags.of(this).add("ManagedBy", "AWS-CDK");
    Tags.of(this).add("Environment", "production");

    const privateAssetBucketName = ssm.StringParameter.valueForStringParameter(
      this,
      "/panther/foundation/private-asset-bucket",
    );
    const privateAssets = s3.Bucket.fromBucketName(
      this,
      "PrivateAssets",
      privateAssetBucketName,
    );

    const administratorEmails = [
      {
        Value: props.administratorEmail,
        Type: "work",
        Primary: true,
      },
    ];
    const administratorUserParameters = {
      IdentityStoreId: props.identityStoreId,
      UserName: props.administratorEmail,
      DisplayName: "Panther Administrator",
      Name: {
        GivenName: "Panther",
        FamilyName: "Administrator",
      },
      Emails: administratorEmails,
    };
    const administratorUserLogGroup = new logs.LogGroup(
      this,
      "AdministratorUserLogGroup",
      {
        retention: logs.RetentionDays.ONE_MONTH,
        removalPolicy: RemovalPolicy.DESTROY,
      },
    );
    const administrator = new cr.AwsCustomResource(this, "AdministratorUser", {
      onCreate: {
        service: "identitystore",
        action: "createUser",
        parameters: administratorUserParameters,
        physicalResourceId: cr.PhysicalResourceId.fromResponse("UserId"),
      },
      onUpdate: {
        service: "identitystore",
        action: "createUser",
        parameters: administratorUserParameters,
        physicalResourceId: cr.PhysicalResourceId.fromResponse("UserId"),
      },
      onDelete: {
        service: "identitystore",
        action: "deleteUser",
        parameters: {
          IdentityStoreId: props.identityStoreId,
          UserId: new cr.PhysicalResourceIdReference(),
        },
        ignoreErrorCodesMatching: "ResourceNotFoundException|ValidationException",
      },
      policy: cr.AwsCustomResourcePolicy.fromStatements([
        new iam.PolicyStatement({
          actions: [
            "identitystore:CreateUser",
            "identitystore:DeleteUser",
          ],
          resources: ["*"],
        }),
      ]),
      installLatestAwsSdk: false,
      logGroup: administratorUserLogGroup,
      timeout: Duration.minutes(1),
    });

    const administratorPermissionSet = new sso.CfnPermissionSet(
      this,
      "AdministratorPermissionSet",
      {
        instanceArn: props.identityCenterInstanceArn,
        name: "PantherAdministrator",
        description: "Administrative access to the Panther AWS account",
        managedPolicies: ["arn:aws:iam::aws:policy/AdministratorAccess"],
        sessionDuration: "PT4H",
      },
    );

    new sso.CfnAssignment(this, "AdministratorAssignment", {
      instanceArn: props.identityCenterInstanceArn,
      permissionSetArn: administratorPermissionSet.attrPermissionSetArn,
      principalId: administrator.getResponseField("UserId"),
      principalType: "USER",
      targetId: this.account,
      targetType: "AWS_ACCOUNT",
    });

    const uploaderPolicy = new iam.PolicyDocument({
      statements: [
        new iam.PolicyStatement({
          actions: ["s3:GetBucketLocation", "s3:ListBucket"],
          resources: [privateAssets.bucketArn],
          conditions: {
            StringLike: {
              "s3:prefix": ["games", "games/*"],
            },
          },
        }),
        new iam.PolicyStatement({
          actions: [
            "s3:AbortMultipartUpload",
            "s3:DeleteObject",
            "s3:GetObject",
            "s3:GetObjectTagging",
            "s3:PutObject",
            "s3:PutObjectTagging",
          ],
          resources: [privateAssets.arnForObjects("games/*")],
        }),
        new iam.PolicyStatement({
          actions: ["ssm:GetParameter"],
          resources: [
            this.formatArn({
              service: "ssm",
              resource: "parameter",
              resourceName: "panther/foundation/private-asset-bucket",
            }),
          ],
        }),
      ],
    });

    const assetUploaderPermissionSet = new sso.CfnPermissionSet(
      this,
      "AssetUploaderPermissionSet",
      {
        instanceArn: props.identityCenterInstanceArn,
        name: "PantherAssetUploader",
        description: "Manage private Panther game assets without administrative access",
        inlinePolicy: uploaderPolicy.toJSON(),
        sessionDuration: "PT8H",
      },
    );

    new sso.CfnAssignment(this, "AssetUploaderAssignment", {
      instanceArn: props.identityCenterInstanceArn,
      permissionSetArn: assetUploaderPermissionSet.attrPermissionSetArn,
      principalId: administrator.getResponseField("UserId"),
      principalType: "USER",
      targetId: this.account,
      targetType: "AWS_ACCOUNT",
    });
  }
}
