import * as fs from "node:fs";
import * as path from "node:path";
import { X509Certificate } from "node:crypto";
import { CfnOutput, Stack, StackProps } from "aws-cdk-lib";
import { CfnRole } from "aws-cdk-lib/aws-iam";
import { CfnProfile, CfnTrustAnchor } from "aws-cdk-lib/aws-rolesanywhere";
import { Construct } from "constructs";

export interface MachineAccessConfiguration {
  schemaVersion: 1;
  account: string;
  region: "us-west-2";
  administratorAccessApproved: true;
  enabled: boolean;
  caCertificate: string;
  certificate: string;
}

/** Deliberately private deployment input; certificates identify a particular machine. */
export function validateMachineAccess(value: unknown, account: string, now = Date.now()): MachineAccessConfiguration {
  const v = value as MachineAccessConfiguration;
  const keys = ["schemaVersion", "account", "region", "administratorAccessApproved", "enabled", "caCertificate", "certificate"];
  if (!v || typeof v !== "object" || Array.isArray(v) || Object.keys(v).length !== keys.length ||
      keys.some(k => !(k in v)) || v.schemaVersion !== 1 || v.account !== account || !/^\d{12}$/.test(account) ||
      v.region !== "us-west-2" || v.administratorAccessApproved !== true || typeof v.enabled !== "boolean") {
    throw new Error("Invalid private machine access configuration or missing administrator approval");
  }
  try {
    const certificates = [v.caCertificate, v.certificate].map(pem => {
      if (typeof pem !== "string" || !/^-----BEGIN CERTIFICATE-----\n[\s\S]+\n-----END CERTIFICATE-----\n?$/.test(pem) ||
          (pem.match(/BEGIN CERTIFICATE/g) ?? []).length !== 1) throw new Error();
      const cert = new X509Certificate(pem);
      if (!/^CN=panther-[a-z0-9-]{8,48}$/.test(cert.subject) ||
          cert.publicKey.asymmetricKeyType !== "rsa" || (cert.publicKey.asymmetricKeyDetails?.modulusLength ?? 0) < 2048) throw new Error();
      return cert;
    });
    const [ca, leaf] = certificates;
    if (!ca.ca || leaf.ca || ca.subject !== ca.issuer || !ca.verify(ca.publicKey) ||
        leaf.issuer !== ca.subject || !leaf.checkIssued(ca) || !leaf.verify(ca.publicKey) || leaf.subject === ca.subject ||
        Date.parse(leaf.validTo) - Date.parse(leaf.validFrom) > 366 * 86400000 ||
        Date.parse(leaf.validTo) > Date.parse(ca.validTo)) throw new Error();
    // Disabled access can still be deployed after expiry, to support emergency revocation.
    if (v.enabled && certificates.some(cert => Date.parse(cert.validFrom) > now || Date.parse(cert.validTo) <= now)) throw new Error();
  } catch {
    throw new Error("Invalid, expired, or mismatched private machine certificates");
  }
  return v;
}

export function loadMachineAccess(file: string | undefined, account: string): MachineAccessConfiguration {
  if (!file) throw new Error("Set PANTHER_MACHINE_ACCESS_FILE to an owner-only file outside the repository");
  const resolved = fs.realpathSync(file);
  const relative = path.relative(fs.realpathSync(path.resolve(__dirname, "../../..")), resolved);
  if (relative === "" || (!relative.startsWith(`..${path.sep}`) && relative !== ".." && !path.isAbsolute(relative))) {
    throw new Error("Machine access configuration must be outside the repository");
  }
  const stat = fs.statSync(resolved);
  if (!stat.isFile() || stat.size > 16000 || (stat.mode & 0o077) || stat.uid !== process.getuid?.()) {
    throw new Error("Machine access configuration must be a small owner-owned file (chmod 600)");
  }
  return validateMachineAccess(JSON.parse(fs.readFileSync(resolved, "utf8")), account);
}

export class PantherMachineAccessStack extends Stack {
  constructor(scope: Construct, id: string, props: StackProps & { configuration: MachineAccessConfiguration }) {
    super(scope, id, props);
    if (this.region !== "us-west-2") throw new Error("Machine access must use us-west-2");
    const c = validateMachineAccess(props.configuration, this.account);
    const ca = new X509Certificate(c.caCertificate);
    const leaf = new X509Certificate(c.certificate);
    const anchor = new CfnTrustAnchor(this, "TrustAnchor", {
      name: "panther-laptop", enabled: c.enabled,
      source: { sourceType: "CERTIFICATE_BUNDLE", sourceData: { x509CertificateData: c.caCertificate } },
    });
    const role = new CfnRole(this, "Administrator", {
      roleName: "PantherLaptopAdministrator", maxSessionDuration: 3600,
      description: "Explicitly owner-approved unattended laptop administration; not a limited game upload role",
      managedPolicyArns: [`arn:${this.partition}:iam::aws:policy/AdministratorAccess`],
      assumeRolePolicyDocument: { Version: "2012-10-17", Statement: [{ Effect: "Allow",
        Principal: { Service: "rolesanywhere.amazonaws.com" },
        Action: ["sts:AssumeRole", "sts:TagSession", "sts:SetSourceIdentity"],
        Condition: { ArnEquals: { "aws:SourceArn": anchor.attrTrustAnchorArn },
          StringEquals: { "aws:SourceAccount": this.account,
            "aws:PrincipalTag/x509Subject/CN": leaf.subject.slice(3),
            "aws:PrincipalTag/x509Issuer/CN": ca.subject.slice(3) } } }] },
      // Unlike disabling just the profile, this also blocks already-issued sessions on this role.
      policies: c.enabled ? [] : [{ policyName: "Disabled", policyDocument: {
        Version: "2012-10-17", Statement: [{ Effect: "Deny", Action: "*", Resource: "*" }],
      } }],
    });
    const profile = new CfnProfile(this, "Profile", {
      name: "panther-laptop-administrator", enabled: c.enabled, durationSeconds: 3600,
      acceptRoleSessionName: false, roleArns: [role.attrArn],
      attributeMappings: ["x509Subject", "x509Issuer"].map(certificateField => ({
        certificateField, mappingRules: [{ specifier: "CN" }],
      })),
    });
    new CfnOutput(this, "TrustAnchorArn", { value: anchor.attrTrustAnchorArn });
    new CfnOutput(this, "ProfileArn", { value: profile.attrProfileArn });
    new CfnOutput(this, "RoleArn", { value: role.attrArn });
  }
}
