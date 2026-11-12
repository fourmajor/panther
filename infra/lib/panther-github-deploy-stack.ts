import { Duration, Stack, StackProps, Tags } from "aws-cdk-lib";
import * as iam from "aws-cdk-lib/aws-iam";
import { Construct } from "constructs";

export interface PantherGitHubDeployStackProps extends StackProps {
  /** GitHub repository allowed to deploy, for example fourmajor/panther. */
  readonly repository: string;
  /** Use this when the account already has the GitHub OIDC provider. */
  readonly providerArn?: string;
}

/** GitHub Actions on this repo's main branch can deploy. Nothing else can assume the role. */
export class PantherGitHubDeployStack extends Stack {
  constructor(scope: Construct, id: string, props: PantherGitHubDeployStackProps) {
    super(scope, id, props);
    if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(props.repository)) {
      throw new Error("repository must be owner/name");
    }

    Tags.of(this).add("Project", "Panther");
    Tags.of(this).add("ManagedBy", "AWS-CDK");
    Tags.of(this).add("Environment", "production");

    const provider = props.providerArn
      ? iam.OpenIdConnectProvider.fromOpenIdConnectProviderArn(this, "GitHub", props.providerArn)
      : new iam.OpenIdConnectProvider(this, "GitHub", {
          url: "https://token.actions.githubusercontent.com",
          clientIds: ["sts.amazonaws.com"],
        });
    const subject = `repo:${props.repository}:ref:refs/heads/main`;
    new iam.Role(this, "Deploy", {
      roleName: "PantherGitHubDeploy",
      description: `GitHub Actions deploy for ${subject}`,
      maxSessionDuration: Duration.hours(2),
      assumedBy: new iam.WebIdentityPrincipal(provider.openIdConnectProviderArn, {
        StringEquals: {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
          "token.actions.githubusercontent.com:sub": subject,
        },
      }),
      // CDK deploy of this app creates IAM, CloudFront, Cognito, and Lambda.
      // The trust policy above is the scope: only this repo's main branch.
      managedPolicies: [iam.ManagedPolicy.fromAwsManagedPolicyName("AdministratorAccess")],
    });
  }
}
