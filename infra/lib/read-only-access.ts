import * as path from "node:path";
import { ArnFormat, CustomResource, Duration, RemovalPolicy, Stack } from "aws-cdk-lib";
import { Construct } from "constructs";
import * as cognito from "aws-cdk-lib/aws-cognito";
import * as cr from "aws-cdk-lib/custom-resources";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as logs from "aws-cdk-lib/aws-logs";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";

/** Synthetic catalog reader. Not a person, publisher, worker, or migration admin. */
export const VIEWER_USERNAME = "penelope-viewer";
export const VIEWER_SECRET_NAME = "panther/viewer-credentials";
export const GRAFANA_USERNAME = "panther-grafana-readonly";
export const GRAFANA_SECRET_NAME = "panther/grafana-cloudwatch-readonly";

export function catalogReaders(users: readonly string[], elevated: {
  publishers: readonly string[];
  workers: readonly string[];
  migrationAdmins: readonly string[];
}): string[] {
  for (const list of [elevated.publishers, elevated.workers, elevated.migrationAdmins]) {
    if (list.includes(VIEWER_USERNAME)) {
      throw new Error(`${VIEWER_USERNAME} must stay off publisher, worker, and migration admin lists`);
    }
  }
  return [...new Set([...users, VIEWER_USERNAME])];
}

export function grafanaPolicyStatements(): iam.PolicyStatementProps[] {
  return [
    {
      sid: "CloudWatchMetricsRead",
      actions: [
        "cloudwatch:DescribeAlarms",
        "cloudwatch:DescribeAlarmsForMetric",
        "cloudwatch:GetMetricData",
        "cloudwatch:GetMetricStatistics",
        "cloudwatch:ListMetrics",
      ],
      resources: ["*"],
    },
    {
      sid: "RegionsAndTags",
      actions: ["ec2:DescribeRegions", "ec2:DescribeTags", "tag:GetResources"],
      resources: ["*"],
    },
  ];
}

/** Reader sign-in and the Grafana CloudWatch key. Values stay in Secrets Manager. */
export class ReadOnlyAccess extends Construct {
  readonly viewerSecret: secretsmanager.Secret;
  readonly grafanaSecretArn: string;
  readonly grafanaUser: iam.User;

  constructor(scope: Construct, id: string, props: {userPool: cognito.IUserPool}) {
    super(scope, id);
    const code = lambda.Code.fromAsset(path.join(__dirname, "../../lambda/read-only-access"), {
      exclude: ["**/__pycache__/**", "**/*.pyc"],
    });
    const viewerSecret = this.viewerSecret = new secretsmanager.Secret(this, "ViewerCredentials", {
      secretName: VIEWER_SECRET_NAME,
      description: "Synthetic Panther catalog reader. Username and password only.",
      removalPolicy: RemovalPolicy.RETAIN,
      generateSecretString: {
        secretStringTemplate: JSON.stringify({username: VIEWER_USERNAME}),
        generateStringKey: "password",
        passwordLength: 32,
        requireEachIncludedType: true,
        excludePunctuation: false,
        includeSpace: false,
        excludeCharacters: "\"'\\ @",
      },
    });
    const viewerFn = new lambda.Function(this, "Viewer", {
      runtime: lambda.Runtime.PYTHON_3_13,
      architecture: lambda.Architecture.ARM_64,
      handler: "viewer.handler",
      code,
      timeout: Duration.seconds(30),
      memorySize: 128,
      logGroup: new logs.LogGroup(this, "ViewerLogs", {
        retention: logs.RetentionDays.ONE_MONTH, removalPolicy: RemovalPolicy.DESTROY,
      }),
    });
    viewerSecret.grantRead(viewerFn);
    viewerFn.addToRolePolicy(new iam.PolicyStatement({
      actions: ["cognito-idp:AdminGetUser", "cognito-idp:AdminCreateUser", "cognito-idp:AdminSetUserPassword"],
      resources: [props.userPool.userPoolArn],
    }));
    const viewerProvider = new cr.Provider(this, "ViewerProvider", {
      onEventHandler: viewerFn,
      logGroup: new logs.LogGroup(this, "ViewerProviderLogs", {
        retention: logs.RetentionDays.ONE_WEEK, removalPolicy: RemovalPolicy.DESTROY,
      }),
    });
    const viewer = new CustomResource(this, "ViewerAccount", {
      serviceToken: viewerProvider.serviceToken,
      resourceType: "Custom::PantherViewer",
      properties: {
        UserPoolId: props.userPool.userPoolId,
        Username: VIEWER_USERNAME,
        SecretId: VIEWER_SECRET_NAME,
      },
    });
    viewer.node.addDependency(viewerSecret);
    viewer.applyRemovalPolicy(RemovalPolicy.RETAIN);

    const grafanaUser = this.grafanaUser = new iam.User(this, "GrafanaUser", {
      userName: GRAFANA_USERNAME,
    });
    grafanaUser.applyRemovalPolicy(RemovalPolicy.RETAIN);
    for (const statement of grafanaPolicyStatements()) grafanaUser.addToPolicy(new iam.PolicyStatement(statement));
    const grafanaFn = new lambda.Function(this, "GrafanaKey", {
      runtime: lambda.Runtime.PYTHON_3_13,
      architecture: lambda.Architecture.ARM_64,
      handler: "grafana_key.handler",
      code,
      timeout: Duration.seconds(30),
      memorySize: 128,
      logGroup: new logs.LogGroup(this, "GrafanaKeyLogs", {
        retention: logs.RetentionDays.ONE_MONTH, removalPolicy: RemovalPolicy.DESTROY,
      }),
    });
    const stack = Stack.of(this);
    const userArn = stack.formatArn({service: "iam", region: "", resource: "user", resourceName: GRAFANA_USERNAME});
    grafanaFn.addToRolePolicy(new iam.PolicyStatement({
      actions: ["iam:CreateAccessKey", "iam:DeleteAccessKey"],
      resources: [userArn],
    }));
    grafanaFn.addToRolePolicy(new iam.PolicyStatement({
      actions: ["secretsmanager:CreateSecret", "secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"],
      resources: [stack.formatArn({
        service: "secretsmanager",
        resource: "secret",
        resourceName: `${GRAFANA_SECRET_NAME}-*`,
        arnFormat: ArnFormat.COLON_RESOURCE_NAME,
      })],
    }));
    const grafanaProvider = new cr.Provider(this, "GrafanaProvider", {
      onEventHandler: grafanaFn,
      logGroup: new logs.LogGroup(this, "GrafanaProviderLogs", {
        retention: logs.RetentionDays.ONE_WEEK, removalPolicy: RemovalPolicy.DESTROY,
      }),
    });
    const grafanaKey = new CustomResource(this, "GrafanaCredential", {
      serviceToken: grafanaProvider.serviceToken,
      resourceType: "Custom::PantherGrafanaKey",
      properties: {UserName: GRAFANA_USERNAME},
    });
    grafanaKey.node.addDependency(grafanaUser);
    grafanaKey.applyRemovalPolicy(RemovalPolicy.RETAIN);
    this.grafanaSecretArn = grafanaKey.getAttString("SecretArn");

    const watchdog = iam.Role.fromRoleArn(this, "WatchdogRole", stack.formatArn({
      service: "iam", region: "", resource: "role", resourceName: "PantherWatchdogReadOnly",
    }), {mutable: true});
    for (const secretArn of [viewerSecret.secretArn, this.grafanaSecretArn]) {
      watchdog.addToPrincipalPolicy(new iam.PolicyStatement({
        actions: ["secretsmanager:GetSecretValue"],
        resources: [secretArn],
      }));
    }
  }
}
