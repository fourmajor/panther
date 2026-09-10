# Organized asset storage (layout version 2)

Status: implemented for a staged migration; **not activated merely by merging this code**.
The production rollout must inventory every game, backfill every asset, verify readers, and retire
the former physical keys before this change is complete. Do not leave a second supported layout.

## File organization

The private asset bucket separates file contents, structured records and the location catalog:

```text
games/<game-id>/
  content/
    characters/<character-id>/
      portraits/<asset-id>/<filename>
      reference-images/<asset-id>/<filename>
      models/<asset-id>/<filename>
    sessions/<session-id>/
      audio/source/<asset-id>/<filename>
      audio/playback/<asset-id>/<filename>
      audio/manifests/<asset-id>/<filename>
      audio/checkpoints/<asset-id>/<filename>
      transcripts/raw/<asset-id>/<filename>
      transcripts/corrected/<asset-id>/<filename>
      novel/chapters/<asset-id>/<filename>
      videos/comparisons/<asset-id>/<filename>
      workflows/<job-id>/<stage-kind>/<asset-id>/<filename>
    library/
      documents/<asset-id>/<filename>
      maps/<asset-id>/<filename>
      music/<asset-id>/<filename>
      stories/<asset-id>/<filename>
      media/<new-kind>/<asset-id>/<filename>
      processing/<new-kind>/<asset-id>/<filename>
  catalog/assets/<asset-id>/<reference-namespace>/<filename>.json
  characters/<character-id>/profile.json
  characters/<character-id>/history/<revision>.json
```

This is an illustration, not an exhaustive list of kinds. `storage_layout.py` is the single
authoritative path builder for uploads and migrations. A portrait/reference/model for exactly one
explicitly associated character belongs to that character, even if it also has a session association.
Otherwise a known session takes priority; non-session or unknown-session assets belong to the shared
game library. Multiple-character media is stored once and links to all its characters via metadata.
Never fabricate a session, character, recording date, relationship or canon status to pick a folder.

Workflow intermediates with an explicit job ID live under that scope's `workflows/` tree, grouped by
job, stage and immutable attempt asset. Published chapters/transcripts/videos live in their respective
media collections, not among plans and review reports. Audio sources, listening copies, manifests,
checkpoints, setup and diagnostics have distinct collections. Their shared asset/chunk-set identity
still groups them together in the application. Existing explicit representation namespaces (such as
`derived/web` or `metadata`) remain distinct subfolders so same-named files cannot collide.

Unknown/new finished kinds use `media/<kind>`; new technical kinds use `processing/<kind>`. Introducing
a medium requires structured kind/role metadata, not new arbitrary top-level folders. `category`
expresses canon/adaptation/reference status, **not physical location**. Titles, tags and character
appearances are associations, not a reason to duplicate bytes into several folders.

## Stable identity, movable storage

The API's `key`/`sourceKeys` values are stable **asset references**, not instructions for constructing
an S3 URL. Their existing `games/<game>/assets/<asset>/original/<filename>` namespace stays valid for
both current and future clients; `original` here is an identity namespace, not a physical folder or
claim of authenticity. Actual payloads no longer live under that prefix after migration.

Every asset, new or migrated, has the same small versioned S3 catalog entry with `assetRef`,
`storageKey`, layout version, size, SHA-256 and original creation time. The API resolves that identity
before reading, signing a URL or checking a workflow's exact byte pin. There is **no fallback** from
a missing locator to an old object. All published source references, character selections and completed
workflow evidence retain their original values and exact bytes; no creative jobs are regenerated.
`panther info` exposes both the stable `key` and physical `storageKey`.

The regular upload API computes the location on the server. Callers cannot supply an arbitrary S3
destination. It reserves an immutable catalog entry and signs a checksum-protected, create-only
upload to that location. Different content or organization cannot reuse the same identity. Interrupted
uploads leave retryable reservations; a reservation with no payload is not listed as a published asset.
Metadata-only edits that would change location are rejected; those require another versioned storage
migration, not a silently stale folder. Ordinary metadata edits and content revisions keep their
existing authorization and no-overwrite guards.

The small S3 catalog avoids an additional database. There is no NAT gateway, provisioned concurrency,
daemon or always-on cloud worker. Lookups incur S3 requests during use. Retained original versions and
the organized copies temporarily/permanently add storage; preservation is deliberate, not free storage.

## Safe production rollout

This rollout is controlled through CDK's temporary `assetStorageMode` context: `original`, `prepare`,
then `indexed`. The default remains `original` only until the complete migration is verified.
All asset-reading Lambdas receive the same mode, including novel, character/model, editorial, audio,
catalog and metadata endpoints. Never switch individual readers independently.

1. Review/merge the PR after local tests and self-hosted Playwright. Confirm no active local workflow
   stage is uploading. Keep all local files and worker state; do not regenerate outputs or spend money.
2. Confirm account/region, preview and deploy **only** `PantherMediaExplorer` through CDK with
   `--context assetStorageMode=prepare`. This freezes ordinary uploads and metadata edits, but continues
   reading originals. Wait out the 300-second maximum previously issued upload URL lifetime, then take
   a fresh inventory. Do not cut over with an in-flight copy or unaccounted newly uploaded file.
3. Inventory every game with `panther assets catalog`; pin `panther info` versions. Use one private
   schemaVersion-1 plan in the metadata-migration format. Include complete current metadata, exact
   existing provenance and factual reasons. Unknown facts stay explicitly unknown. Validate all target
   keys for collisions with the shared path builder. Keep game plans/evidence outside Git.
4. Dry-run `panther assets reorganize PLAN --report NEW_REPORT.jsonl`, then apply that exact plan with
   `--apply`. The serialized owner-only endpoint copies an exact source VersionId, preserves content
   headers/uploader/tags/date, verifies destination size/checksum, then publishes its locator. It never
   overwrites an unrelated destination. Retrying the exact plan resumes without a second copy. The old
   current object remains throughout this phase. Inventory/copy all assets, including technical files,
   older models and failed editorial candidates—not just currently featured media.
5. Verify a bijection between the inventory and catalog entries, all target bytes/checksums/metadata,
   all source references and profile/workflow pins. Then preview and deploy the same stack with
   `--context assetStorageMode=indexed`. Verify authenticated catalogs, actual downloads and browser
   character models, continuous audio, raw/corrected transcripts, novel and video readers. Existing
   local worker releases need no key rewrite: they already use stable references through Panther.
6. Dry-run the same plan with `--retire`, then `--retire --apply` only after those checks pass. This
   adds conditional [S3 delete markers](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-deletes.html)
   at the old physical keys; it **never deletes a source VersionId**. The catalog retains that exact
   historical source version for recovery. Re-inventory S3: no current payloads may remain in the old
   asset prefix. Verify the entire live catalog again and preserve private cloud migration reports.
7. Remove `original`/`prepare` rollout code and old-prefix copy/retirement permissions in a follow-up
   PR, make indexed storage unconditional, and update this status/runbook. This is a required completion
   step, not optional cleanup. Do not report the reorganization complete before this and all backfills.

The API uses [version-pinned S3 copies and SHA-256](https://docs.aws.amazon.com/AmazonS3/latest/API/API_CopyObject.html).
For sources without a stored SHA-256, S3 calculates it on that exact version's copy; preserve the
original version pin and verify downloaded bytes in the rollout audit. Checksums are not inferred from
ETags. A copy failure retains the original; a conflicting locator/version stops the plan for inspection.
Never replace expected versions automatically. No file content is accepted by this migration endpoint.

Before retirement, rollback is a CDK switch to original readers; stop new indexed uploads first and
account for them before rollback. After retirement, do not just switch modes: retained versions need
an explicit, reviewed recovery migration. Never recreate missing files with guessed metadata, overwrite
immutable raw transcripts or edit an old Step Functions execution to make an audit pass.
