# Temporary indexed relocation v1

Use this only for a reviewed physical reorganization of existing indexed assets, not normal uploads
or a new reader/storage mode. The stable reference, semantic version and file bytes remain unchanged.
Original object and locator versions are retained. `storage_layout.py` computes every destination.

The default deployment has **no relocation route or permissions**. CDK context
`assetRelocationPlan=/absolute/private/hashes.json` enables a dedicated owner-authenticated
`POST /asset-relocations-v1` Lambda for 1–20 exact reviewed request SHA-256 hashes. No arbitrary
destination, file bytes or historical-version deletion is accepted. Use private production assemblies
and reviewed diffs; no account roster or migration inventory belongs in Git.

Plans have the existing metadata migration schema: `schemaVersion:1`, `migrations[]`, with exact
`key`, `expectedVersionId`, `kind`, current `metadata`, and `reason`. The SHA-256 is computed over
each entry's sorted Python JSON encoding, excluding `dryRun` and `action` (see
`asset_relocation.identity`). Changing any pinned evidence requires a newly reviewed deployment.

1. Inventory **every game**, inspect exact source versions, and split physical moves from ordinary
   metadata-only edits. Prepare the immutable private plan and its hash list.
2. Run local regression tests and required self-hosted browser checks, review/merge the PR, then
   deploy the temporary capability through CDK. Confirm account/region and that existing users,
   permissions and reader modes are unchanged.
3. `panther assets relocate PLAN --report NEW_REPORT` dry-runs the moves. Inspect the report.
   Repeat with `--apply` to copy exact source versions. A create-only destination copy verifies
   SHA-256, size and tags, then conditionally changes the current locator. Headers and original
   actor/creation time are preserved. The retained locator records source/destination versions,
   actor, time, reason and request hash. Interrupted copies reuse the same plan, not fresh pins.
4. Run `--action verify`, download each relocated file through Panther and compare its SHA-256
   against the pinned source. Apply the remaining metadata-only plan. Rebuild/verify the all-game
   materialized browsing index and verify affected browser/model/source relationships. Browsing
   never falls back to a storage scan or the former physical path.
5. Only after those checks, dry-run then apply `--action retire`. This rechecks the selected
   destination and the original exact source version; it adds a conditional **recoverable delete
   marker**, never deletes an original version. Repeat verify and all-game auditing.
6. Remove the context and redeploy. Confirm the temporary route, Lambda and extra permissions
   are gone. The rollout is incomplete until this final removal and all-game verification succeed.

Copies use destination [conditional writes](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html)
and retirement uses [conditional delete markers](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-deletes.html).
Do not run ad hoc S3 mutations from the laptop. Ambiguous failures retain the shared migration mutex;
inspect exact source, destination and locator versions and pending writes before any separately reviewed
lock recovery. Validation failures release the lock. Do not steal/expire it automatically.

After cleanup, the CLI command and source/tests remain as audited tooling, but there is no deployed
write capability. Reusing it needs a fresh explicit CDK plan rollout. Recovery likewise requires a
reviewed migration; never add a legacy path fallback or silently replace immutable evidence.
