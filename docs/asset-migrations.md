# Asset standards and migrations

A standards change is not complete until producers, validators and existing data agree. Inventory
every affected game, preserve evidence, implement a repeatable migration, dry-run it, apply it,
verify every record, and remove obsolete runtime compatibility. Keep a private report of unresolved
facts. Unknown is a valid explicit state, not permission to fabricate metadata or exempt a record.
Repository instructions apply this policy to future schema and organizational changes as well.

The initial physical S3 reorganization is documented in [asset-storage.md](asset-storage.md).
It applied current metadata during the verified copy/cutover/retirement process. Its temporary command
and endpoint are retired; all assets now use the location catalog. Future physical moves require a
new versioned migration. Do not run metadata edits against an outstanding storage plan: they would
change its expected source versions.

## Metadata migration v1

`panther assets catalog --game GAME_ID` gives the complete catalog. `panther info KEY` returns the
current S3 `versionId`, ETag, metadata and original uploader without exposing a signed URL. Use these
to prepare a private plan containing `schemaVersion: 1` and `migrations: [...]`. Each entry contains:

- `schemaVersion: 1`, `key`, exact `expectedVersionId`, `kind`, and a factual `reason`.
- Complete `metadata`: `schemaVersion: 1`, a meaningful `title`, existing supported `category`,
  explicit `characterIds`, `tags`, `sourceKeys`, and `extra.relationshipRole` (`finished` or `intermediate`).
- Existing metadata, including generator/checksum/review details and all compact source keys.
  Large exact provenance remains in its structured document. Do not substitute guessed source links.

```sh
panther assets migrate /private/path/plan.json --report /private/path/dry-run.jsonl
panther assets migrate /private/path/plan.json --apply --report /private/path/applied.jsonl
```

Plans/reports contain private game information and stay out of Git. Reports are create-only,
owner-readable and flushed durably after each response. Upload the final report as an intermediate
private migration-report asset for recoverable cloud evidence. Inspect every result and re-inventory
after application. An uncertain request must reuse the exact plan; its durable migration ID makes
retrying an already-applied entry harmless. A conflict stops the batch; never replace the expected
version automatically. No content or workflow generation occurs during metadata migration.

The owner-only Cognito endpoint runs in a dedicated CDK Lambda with a retained, on-demand DynamoDB
mutex. Conditional acquisition serializes version checks and copies without reserved concurrency
(which cannot be configured within this account's initial concurrency quota). It is the sole
metadata writer. Ordinary upload permissions remain
create-only. It rejects unversioned objects, accepts no replacement bytes, preserves existing compact
lineage, checks source existence, and copies the exact source VersionId back to its key with new
metadata. Existing file bytes, references, original uploader, tags and content headers are preserved.
Only organized `content/` payloads can be copied. Location-catalog creation and old-prefix deletion
permissions are no longer granted to this endpoint. Routing-changing metadata edits are rejected.
Previous S3 versions are retained without an expiration lifecycle; the new version records the actor,
time, previous version and migration ID. This requires storage for retained versions, plus small
request/Lambda costs while running, but no always-on compute. Current bucket encryption is SSE-S3.
File creation/publication time is preserved separately from S3's metadata-copy timestamp; novel
ordering and editorial evidence cutoffs must not advance merely because metadata was backfilled.

New uploads receive explicit empty association/tag/source lists where none are supplied and a stored
relationship role. An empty list means no associations recorded, not proof that none exist. Known
technical kinds are intermediate; finished audio manifests represent their recording. These are
current type defaults, not old-record exceptions. The migration does not guess canon or identities.

This endpoint is deliberately metadata-only. Content-envelope upgrades need a separate migration
that publishes a new immutable content version, updates current publication references atomically,
and verifies downstream pins. Do not rewrite an old raw transcript, erase a failed candidate,
change a workflow's checksum reference, or relabel an adaptation as evidence to force compliance.
Report content-level blockers explicitly until that migration has actually completed.
