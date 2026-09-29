# Renewable laptop AWS access

Issue #147 replaces recurring browser sign-ins for infrastructure work with IAM Roles Anywhere.
This is explicitly owner-approved **administrator-equivalent** access, not a limited upload role.
An unlocked, compromised Mac or malicious authorized helper can administer the account. This is
not sandbox isolation or MFA per command. Normal CDK, PR, diff and spending gates still apply.
Game operations continue to use Panther authentication, not this administrative AWS profile.

## Design and cost

`PantherMachineAccess` owns the IAM role, certificate trust anchor and Roles Anywhere profile.
Trust is restricted to the exact anchor, account, certificate subject and issuer. The profile
permits one role and issues one-hour sessions. The AWS signing helper authenticates using an exact
certificate serial in macOS Keychain. CLI calls obtain fresh credentials; supporting SDKs refresh
automatically. No background daemon, permanent IAM access keys, credential server/export, hosted
compute, Secrets Manager, or AWS Private CA is added.

[Roles Anywhere has no additional service charge](https://aws.amazon.com/about-aws/whats-new/2022/07/aws-identity-access-management-iam-roles-anywhere-workloads-outside-aws/).
Other AWS operations retain normal charges. A local one-device CA issues a one-year certificate;
its signing key is then discarded. Rotation is periodic, rather than login on every session.
Standard CloudTrail event history records sessions and administrative actions; no paid trail
is added by this stack.

## Bootstrap

Use recovery SSO for the initial deployment. Keep machine configuration, production assembly,
diff, outputs and AWS config backups outside Git in owner-only storage, never in CI artifacts.
Local native checks require matching macOS Command Line Tools and SDK versions. If `xcrun`
selects an SDK newer than the installed Swift compiler supports, set `SDKROOT` to a compatible
installed SDK for the setup command; do not change global Xcode settings or weaken Keychain
security to work around a compilation failure. Normal AWS credential refresh runs the pinned
helper directly and does not invoke Swift or compile anything.

1. Create a new mode-700 directory outside the repository, preferably in the owner's Panther
   application-support directory. From the repo root:

   ```sh
   python3 ops/aws-access/setup.py prepare --directory PRIVATE_DIRECTORY --account ACCOUNT_ID \
     --approve-unattended-administrator
   ```

   This verifies the pinned official helper's SHA-256 and code signature, generates the certificate,
   and imports the key as non-extractable into the existing default user Keychain. The import ACL
   permits the helper, not all applications. No default-Keychain or search-list changes are made.
   Plaintext PEM keys exist only in an owner-only temporary directory during import
   and are removed afterwards; deletion is not a guarantee of forensic erasure. No secret wrapping
   password is passed in argv. Native failure logs are retained privately, not forwarded to CI.
   After import, a scoped native check adds the verified AWS developer to this key's macOS
   partition list. The signing ACL must already contain only the exact helper, and the key must
   remain non-extractable. Unexpected identities, ACLs or partitions fail closed. No other keys
   are searched or modified. macOS may ask for local authorization to persist this change.
   If import fails, use a new directory and inspect Keychain for a partially imported identity.
   If only the access check fails after the configuration was saved, resume with:

   ```sh
   python3 ops/aws-access/setup.py keychain --directory PRIVATE_DIRECTORY --repair
   ```

   The default `keychain` command is read-only; `--repair` explicitly permits this scoped correction.
   Never grant all applications access, change a whole Keychain's partition list, or store a Mac
   password to silence prompts. Normal macOS authorization is retained; the tool never collects it.

2. Set `PANTHER_MACHINE_ACCESS_FILE=PRIVATE_DIRECTORY/machine-access.json` and the existing
   `PANTHER_IDENTITIES_FILE`. Build `infra`, confirm the authenticated account, then preview only
   the new stack from `infra`:

   ```sh
   npx cdk diff PantherMachineAccess --exclusively --profile panther-sso-admin \
     --context account=ACCOUNT_ID --context machineAccess=true --output PRIVATE_ASSEMBLY
   ```

   Inspect the private diff: only a new role/profile/anchor, no access keys/users or changes to
   application/SSO resources. Deploy the reviewed stack with the same flags and an additional
   `--outputs-file PRIVATE_OUTPUTS`. Every AWS resource write uses CDK/CloudFormation.

3. Run `setup.py configure --directory PRIVATE_DIRECTORY --outputs PRIVATE_OUTPUTS` from the
   repo root. It validates the output account/region/exact role, privately backs up existing AWS
   config, and adds `panther-laptop-admin`. A conflicting existing profile fails closed. Existing
   SSO/default profiles stay unchanged. STS verifies the identity without displaying credentials.
   Use `--profile panther-laptop-admin` for infrastructure work, not `aws sso login` for this profile.

4. Verify independently obtained sessions, IAM permission simulation and a read-only CDK diff
   through the new profile. Never display signing-helper credential output. Keep the certificate,
   AWS credentials and personal folders out of Docker and the self-hosted runner.

The official helper is signed but not notarized. Importing it with `security import -T` alone can
leave an Apple-only partition list that repeatedly blocks signing despite the helper-specific ACL.
The scoped correction above fixes that second gate; normal native authorization may require a
one-time local approval for the setup tool. Keychain must unlock after reboot, normally with the OS login. Do not
store the owner's login password to automate unlock. See the [AWS helper documentation](https://docs.aws.amazon.com/rolesanywhere/latest/userguide/credential-helper.html).

## Rotation and recovery

Inspect expiry with `openssl x509 -in PRIVATE_DIRECTORY/certificate.pem -enddate -noout`.
Before expiry, prepare a new private directory/identity, preserve previous config/outputs, preview
and deploy the updated anchor/subject using the working laptop profile or recovery SSO, then
back up and explicitly replace the laptop credential-process. The bootstrap intentionally refuses
conflicting profiles: do not discard working access before deployment. Verify the new identity
and rejection of the old certificate; only then remove the old Keychain identity. Never silently
extend validity or create a permanent access key as a workaround.

For a lost/compromised device, use recovery SSO from a trusted machine, set `enabled:false` in
the preserved private config, preview and deploy this stack. This disables the anchor/profile
and adds an explicit deny-all policy to the role, blocking issued direct-role sessions once IAM
changes propagate. **Sessions previously assumed into other roles are not retroactively revoked**;
they can survive until expiry. Assess/revoke those roles' sessions with CDK-managed deny policies,
inspect CloudTrail and rotate affected secrets. Administrative privilege makes incident scope
account-wide. Existing SSO identities/recovery remain unchanged. Disabled config can deploy even
after certificate expiry. Re-enabling requires valid certificates and review. If private config
was lost, retrieve the deployed template through recovery SSO into owner-only storage; never
publish it or create an ad hoc IAM user.
