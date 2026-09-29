import assert from "node:assert/strict";
import test from "node:test";
import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { App } from "aws-cdk-lib";
import { Template, Match } from "aws-cdk-lib/assertions";
import { loadMachineAccess, validateMachineAccess, PantherMachineAccessStack } from "../lib/panther-machine-access-stack";

const directory = fs.mkdtempSync(path.join(os.tmpdir(), "panther-machine-test-"));
function openssl(...args: string[]) { execFileSync("openssl", args, { cwd: directory, stdio: "ignore" }); }
openssl("req", "-new", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256", "-days", "730",
  "-subj", "/CN=panther-example-authority", "-keyout", "ca.key", "-out", "ca.pem",
  "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign,cRLSign");
openssl("req", "-new", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=panther-example-device", "-keyout", "leaf.key", "-out", "leaf.csr");
fs.writeFileSync(path.join(directory, "extensions"), "basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\n");
openssl("x509", "-req", "-in", "leaf.csr", "-CA", "ca.pem", "-CAkey", "ca.key", "-set_serial", "12345",
  "-sha256", "-days", "365", "-extfile", "extensions", "-out", "leaf.pem");
const configuration = { schemaVersion: 1, account: "123456789012", region: "us-west-2",
  administratorAccessApproved: true, enabled: true,
  caCertificate: fs.readFileSync(path.join(directory, "ca.pem"), "utf8"),
  certificate: fs.readFileSync(path.join(directory, "leaf.pem"), "utf8") };
test.after(() => fs.rmSync(directory, { recursive: true }));
function stack(overrides = {}) {
  return new PantherMachineAccessStack(new App(), "Machine", {
    env: { account: configuration.account, region: configuration.region },
    configuration: validateMachineAccess({ ...configuration, ...overrides }, configuration.account),
  });
}

test("one-hour administration trusts only the approved device and anchor, with no paid CA or access keys", () => {
  const template = Template.fromStack(stack());
  template.resourceCountIs("AWS::IAM::Role", 1);
  template.hasResourceProperties("AWS::IAM::Role", { MaxSessionDuration: 3600,
    ManagedPolicyArns: [Match.anyValue()], AssumeRolePolicyDocument: { Statement: [{ Effect: "Allow",
      Principal: { Service: "rolesanywhere.amazonaws.com" },
      Action: ["sts:AssumeRole", "sts:TagSession", "sts:SetSourceIdentity"],
      Condition: { ArnEquals: { "aws:SourceArn": Match.anyValue() }, StringEquals: {
        "aws:SourceAccount": configuration.account, "aws:PrincipalTag/x509Subject/CN": "panther-example-device",
        "aws:PrincipalTag/x509Issuer/CN": "panther-example-authority",
      } } }] } });
  template.hasResourceProperties("AWS::RolesAnywhere::Profile", { DurationSeconds: 3600, Enabled: true,
    AcceptRoleSessionName: false, RoleArns: [Match.anyValue()], AttributeMappings: [
      { CertificateField: "x509Subject", MappingRules: [{ Specifier: "CN" }] },
      { CertificateField: "x509Issuer", MappingRules: [{ Specifier: "CN" }] },
    ] });
  template.hasResourceProperties("AWS::RolesAnywhere::TrustAnchor", { Source: {
    SourceType: "CERTIFICATE_BUNDLE", SourceData: { X509CertificateData: configuration.caCertificate },
  } });
  for (const type of ["AWS::IAM::AccessKey", "AWS::IAM::User", "AWS::ACMPCA::CertificateAuthority", "AWS::EC2::Instance", "AWS::SecretsManager::Secret"]) template.resourceCountIs(type, 0);
});

test("disable blocks new sessions and already-issued direct role sessions", () => {
  const template = Template.fromStack(stack({ enabled: false }));
  template.hasResourceProperties("AWS::RolesAnywhere::Profile", { Enabled: false });
  template.hasResourceProperties("AWS::RolesAnywhere::TrustAnchor", { Enabled: false });
  template.hasResourceProperties("AWS::IAM::Role", { Policies: [{ PolicyName: "Disabled", PolicyDocument: {
    Version: "2012-10-17", Statement: [{ Effect: "Deny", Action: "*", Resource: "*" }],
  } }] });
});

test("unapproved, expired, malformed, mismatched or broadened configuration fails closed", () => {
  for (const changes of [{ account: "000000000000" }, { region: "us-east-1" }, { schemaVersion: true },
    { administratorAccessApproved: false }, { enabled: "true" }, { unexpected: true },
    { certificate: configuration.caCertificate }, { caCertificate: configuration.certificate },
    { certificate: configuration.certificate + configuration.certificate }, { certificate: "invalid" }]) {
    assert.throws(() => validateMachineAccess({ ...configuration, ...changes }, configuration.account));
  }
  const future = Date.now() + 3 * 365 * 86400000;
  assert.throws(() => validateMachineAccess(configuration, configuration.account, future));
  assert.doesNotThrow(() => validateMachineAccess({ ...configuration, enabled: false }, configuration.account, future));
  assert.throws(() => new PantherMachineAccessStack(new App(), "WrongRegion", {
    env: { account: configuration.account, region: "us-east-1" },
    configuration: validateMachineAccess(configuration, configuration.account),
  }));
});

test("private owner-only external configuration is required, without deployable defaults", () => {
  assert.throws(() => loadMachineAccess(undefined, configuration.account));
  const file = path.join(directory, "configuration.json");
  fs.writeFileSync(file, JSON.stringify(configuration), { mode: 0o600 });
  assert.equal(loadMachineAccess(file, configuration.account).enabled, true);
  fs.chmodSync(file, 0o644);
  assert.throws(() => loadMachineAccess(file, configuration.account));
});
