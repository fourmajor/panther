import { App } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import test from "node:test";
import { PantherDomainStack } from "../lib/panther-domain-stack";

test("domain stack retains the public Panther hosted zone", () => {
  const app = new App();
  const stack = new PantherDomainStack(app, "TestDomain", {
    env: {
      account: "123456789012",
      region: "us-east-1",
    },
    domainName: "panther.place",
  });
  const template = Template.fromStack(stack);

  template.hasResourceProperties("AWS::Route53::HostedZone", {
    Name: "panther.place.",
    HostedZoneConfig: {
      Comment: "Public DNS for the Panther web application",
    },
  });
  template.allResources("AWS::Route53::HostedZone", {
    DeletionPolicy: "Retain",
    UpdateReplacePolicy: "Retain",
  });
  template.hasResourceProperties("AWS::CertificateManager::Certificate", {
    DomainName: "panther.place",
    ValidationMethod: "DNS",
  });
});
