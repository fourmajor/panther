# Private account configuration

Real usernames, emails and per-account permissions do not belong in the public repository. Cognito
stores the actual login accounts. CDK owns the infrastructure and reusable provisioning logic; actual
provisioning inputs are private data supplied separately. This does not introduce a new permissions
model or grant existing members additional access. Member/admin roles remain tracked in issue #83.

Set `PANTHER_IDENTITIES_FILE` to an absolute path outside every checkout, worktree and CI workspace.
On the owner's laptop the private file is under the Panther application-support `deploy` directory.
Use an owner-only directory (700) and file (600). Do not put passwords in it. Keep a private backup;
the existing AWS CloudFormation template also retains deployed provisioning values for recovery.

The schema contains `schemaVersion: 1` and four explicit lists: `users`, `publishers`, `workers`,
and `migrationAdmins`. Capability lists must reference configured users. A fictional example:

```json
{
  "schemaVersion": 1,
  "users": ["example-operator", "example-editor", "example-member"],
  "publishers": ["example-operator", "example-editor"],
  "workers": ["example-operator"],
  "migrationAdmins": ["example-operator"]
}
```

```sh
export PANTHER_IDENTITIES_FILE=/private/absolute/path/identities.json
cd infra
AWS_PROFILE=panther-sso-admin npm run diff -- PantherMediaExplorer --context account=ACCOUNT_ID --exclusively
AWS_PROFILE=panther-sso-admin npm run deploy -- PantherMediaExplorer --context account=ACCOUNT_ID --exclusively
```

Production synthesis refuses missing, malformed, in-repository or broadly readable configuration.
Only the non-deployable `000000000000` account permits synthetic CI defaults. Tests pass fictional
configuration explicitly. Never give the CI runner the production file or publish production synth
output/diffs as GitHub artifacts. CDK's local ignored `cdk.out` contains private resolved values;
keep it local and treat it as deployment data, not something to commit or attach to a PR.

## Safe cutover and future updates

The initial cutover copies the existing account list and exact capability assignments to the private
file. Preserve the `User-USERNAME` construct identities and generated-password parameter paths so
CloudFormation neither recreates users nor resets their passwords. Review a private CDK diff before
deploying: this cutover must not delete/replace account resources, change provisioning properties,
or expand permissions. Inspect real accounts and a signed-in API read afterward without publishing
the roster, credentials or private content. No game asset schema changes are involved.

Adding an account changes this private file, not GitHub source. Adding it to `users` alone does not
grant publisher, worker or migration access, create a Player record, or infer an administrator role.
Infrastructure definitions remain reviewed through PRs; private account inputs remain outside them.
Missing configuration is an error, not an empty list or a reason to deploy default accounts.

Removing names from current source does **not** erase earlier commits, PR diffs/comments, issues,
clones or caches. A historical-data cleanup requires a separately approved scope and cannot promise
removal from third-party clones. Do not force-push/rewrite shared history as part of routine cleanup.
