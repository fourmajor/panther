# Renewable laptop AWS access

Issue #147 replaces recurring browser sign-ins for infrastructure work with IAM Roles Anywhere.
This is explicitly owner-approved **administrator-equivalent** access, not a limited upload role.
An unlocked, compromised Mac or malicious authorized helper can administer the account. This is
not sandbox isolation or MFA per command. Normal CDK, PR, diff and spending gates still apply.
Game operations continue to use Panther authentication, not this administrative AWS profile.
The machine role has `AdministratorAccess`. In this account, the CDK bootstrap
CloudFormation execution role also has `AdministratorAccess` (verified through IAM on
2026-09-29). CDK may use that role, and if assuming a bootstrap role fails it may proceed
with the machine role's direct credentials. Therefore an unattended CDK deployment is
effectively account-administrative, not limited to the resources shown in one stack diff.
Diff review remains mandatory; neither CDK nor Keychain access is a spending cap.

## Design and cost

`PantherMachineAccess` owns the IAM role, certificate trust anchor and Roles Anywhere profile.
Trust is restricted to the exact anchor, account, certificate subject and issuer. The profile
permits one role and issues one-hour sessions. The AWS signing helper authenticates using an exact
certificate serial in a dedicated macOS Keychain. Its random unlock password is held as a generic
item in the user's login Keychain; the private signing key is non-extractable. The credential
process unlocks only Panther's Keychain and obtains one-hour credentials for CLI and SDK calls.
No background daemon, permanent IAM access keys, credential server/export, hosted
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
security to work around a compilation failure. Normal AWS credential refresh uses the copied
owner-only Python wrapper and pinned helper; it does not invoke Swift or compile anything.

1. Create a new mode-700 directory outside the repository, preferably in the owner's Panther
   application-support directory. From the repo root:

   ```sh
   python3 ops/aws-access/setup.py prepare --directory PRIVATE_DIRECTORY --account ACCOUNT_ID \
     --approve-unattended-administrator
   ```

   This verifies the pinned official helper's SHA-256 and code signature, generates the certificate,
   and imports the key as non-extractable into a new Panther-only Keychain. Its random password
   is stored as an owner-specific generic item in the existing login Keychain, never in Git or
   AWS. The import ACL permits the signed helper, not all applications. The Panther Keychain is
   appended to the user's Keychain search list without changing the default or earlier entries.
   Plaintext PEM keys exist only in an owner-only temporary directory during import
   and are removed afterwards; deletion is not a guarantee of forensic erasure. No secret wrapping
   signing-key password is retained as a file. macOS `security` commands briefly receive the
   dedicated Keychain password in process arguments; same-user processes may observe it.
   Native failure logs are retained privately, not forwarded to CI.
   After import, a read-only native check proves the exact certificate resolves to a
   non-extractable private key. Its signing ACL must contain only the helper, and the signing
   key must be the sole private key with its label in its specific Keychain. Only then does
   the native verifier add the signed AWS helper's developer partition to this one key.
   Unexpected identities, duplicate labels, ACLs or partitions fail closed. No other keys are
   modified. macOS asks once for the **generated Panther Keychain password**, not the Mac login
   password. `prepare` briefly copies that password to the clipboard for pasting into the dialog,
   then clears it if the clipboard is unchanged.
   If import fails, use a new directory and inspect Keychain for a partially imported identity.
   If only the access check fails after the configuration was saved, resume with:

   ```sh
   python3 ops/aws-access/setup.py keychain --directory PRIVATE_DIRECTORY --repair
   ```

   The default `keychain` command is read-only; `--repair` explicitly permits this scoped correction.
   Never grant all applications access, change a whole Keychain's partition list, or store a Mac
   login password to silence prompts. The generated password is separate from the login password.

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
   SSO/default profiles stay unchanged. To rotate an existing machine profile, also supply
   `--previous-directory OLD_PRIVATE_DIRECTORY --previous-outputs OLD_PRIVATE_OUTPUTS`.
   Rotation accepts only an exact known predecessor and saves a private config backup.
   STS verifies the identity without displaying credentials.
   Use `--profile panther-laptop-admin` for infrastructure work, not `aws sso login` for this profile.

4. Verify independently obtained sessions, IAM permission simulation and a read-only CDK diff
   through the new profile. Never display signing-helper credential output. Keep the certificate,
   AWS credentials and personal folders out of Docker and the self-hosted runner.

The official helper is signed but not notarized. Importing with `security import -T` alone can
leave the partition list absent or Apple-only, repeatedly blocking signing despite the helper ACL.
The scoped correction fixes that second gate. After OS login unlocks the user's login Keychain,
the credential process retrieves Panther's generated password and unlocks only its dedicated
Keychain on demand. It does not store or request the owner's Mac login password. This protects
against casual key export but is **not** a boundary against malware already running as the owner:
that process may retrieve the unlock secret or invoke the credential process. See the
[AWS helper documentation](https://docs.aws.amazon.com/rolesanywhere/latest/userguide/credential-helper.html).

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
