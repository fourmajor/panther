import { CfnOutput, RemovalPolicy, Stack, StackProps, Tags } from "aws-cdk-lib";
import * as acm from "aws-cdk-lib/aws-certificatemanager";
import * as route53 from "aws-cdk-lib/aws-route53";
import { Construct } from "constructs";

export interface PantherDomainStackProps extends StackProps {
  readonly domainName: string;
}

export class PantherDomainStack extends Stack {
  public readonly certificate: acm.Certificate;
  public readonly hostedZone: route53.PublicHostedZone;

  constructor(scope: Construct, id: string, props: PantherDomainStackProps) {
    super(scope, id, props);

    Tags.of(this).add("Project", "Panther");
    Tags.of(this).add("ManagedBy", "AWS-CDK");
    Tags.of(this).add("Environment", "production");

    this.hostedZone = new route53.PublicHostedZone(this, "HostedZone", {
      zoneName: props.domainName,
      comment: "Public DNS for the Panther web application",
    });
    this.hostedZone.applyRemovalPolicy(RemovalPolicy.RETAIN);

    this.certificate = new acm.Certificate(this, "Certificate", {
      domainName: props.domainName,
      validation: acm.CertificateValidation.fromDns(this.hostedZone),
    });

    new CfnOutput(this, "HostedZoneId", {
      value: this.hostedZone.hostedZoneId,
      description: "Route 53 public hosted zone managed by CDK",
    });
    new CfnOutput(this, "DomainName", {
      value: props.domainName,
      description: "Primary Panther application domain",
    });
    new CfnOutput(this, "CertificateArn", {
      value: this.certificate.certificateArn,
      description: "ACM certificate for the Panther CloudFront distribution",
    });
  }
}
