# Organized asset storage (layout version 2)

Status: layout 2 is active and unconditional. All 90 pre-existing assets across both games were
migrated and verified on 2026-09-10. Old physical entries have recoverable delete markers; original
versions remain retained. New assets use the same catalog and path builder.

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

The small S3 catalog needs no database for lookups. A separate, tiny on-demand DynamoDB table holds
the migration safety lock only; it has no provisioned capacity or automatic expiration.
There is no NAT gateway, provisioned concurrency,
daemon or always-on cloud worker. Lookups incur S3 requests during use. Retained original versions and
the organized copies temporarily/permanently add storage; preservation is deliberate, not free storage.

## Completed rollout and evidence

The initial rollout froze ordinary uploads, waited for old signed upload links to expire, inventoried
every game, and pinned all 90 source versions. Its private plan applied current structured metadata
while copying exact original bytes. Every destination and catalog entry was checked against full-file
SHA-256, original size, headers, tags, uploader, creation time and compact provenance. The original
profile/history records and workflow checksum pins remained unchanged.

After the indexed-reader cutover, all 90 files were downloaded through Panther and their checksums
compared with the original downloads. Live checks covered character model/portrait delivery, continuous
audio, raw/corrected transcripts, novel chapters, videos, and finished-asset connections. Only then
were the former physical entries hidden with conditional delete markers. A second complete S3 audit
confirmed no current payloads remained under the old prefix and every original VersionId survived.

Private plans, per-operation reports, downloaded-byte checksums and audit results stay outside Git.
Final game-specific reports are intermediate `migration-report` assets, not ordinary reading material.
The initial engine and its synthetic tests remain under `ops/migrations/layout-v2/` for auditability.
Its temporary CLI command/API route, old-prefix write/delete permissions, and original/prepare modes
are retired, not supported alternatives. CDK rejects the old `assetStorageMode` context.

## Future organization changes and recovery

Use a new versioned Panther migration and reviewed CDK rollout for a future physical layout change.
Keep dry runs, exact version pins, conflict guards, durable reports, complete all-game backfills,
verified reader cutover and removal of temporary permissions. Do not restore the historical modes,
rewrite immutable evidence, or edit a completed workflow's checksum references to make an audit pass.
Metadata-only edits through `panther assets migrate` cannot silently change an asset's folder.

The API uses [version-pinned S3 copies and SHA-256](https://docs.aws.amazon.com/AmazonS3/latest/API/API_CopyObject.html).
Checksums are not inferred from ETags. For sources without a stored checksum, verify actual downloaded
bytes. Retained versions and their exact original location/version pins provide recovery evidence.
Do not switch readers back to the old prefix: its current entries are delete markers. Recovery needs
an explicitly reviewed Panther/CDK migration, not guessed reuploads or irreversible version deletion.

The metadata-migration mutex is released after a completed request (including validation failures),
but retained after a timeout, unexpected exception or ambiguous service failure. Never automatically
expire or steal it: an outstanding S3 copy can outlive its caller. If locked, stop the plan and inspect
Lambda logs, the lock's start time and exact source/destination versions/checksums. Only after confirming
there are no outstanding writes may an explicitly reviewed recovery operation conditionally remove
that exact owner's lock. Do not delete the table, discard reports or blindly retry with new version pins.
