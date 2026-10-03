# Logical asset archives (v1)

Deleting an asset archives its immutable reference. Original bytes, locators, metadata,
semantic versions and historical inputs remain intact. Current Assets and file-browser
listings exclude archived files. An exact historical link remains readable.

A current portrait, active appearance, scene map or selected scene output must be deselected
before archival. Editorial, model and image processing pins also block archival. The v1 archive API refuses
recording, audio and transcript deletion until playback/transcription/summary producers join
the same reference transaction contract; it never assumes those inputs are unused. JSON
files receive a bounded, version-pinned semantic classification before deletion, so unknown
metadata cannot disguise a recording manifest or structured transcript as ordinary context. New selections and requests
atomically check tombstone absence and increment a shared per-game reference epoch alongside
the owning record. Archival verifies a bounded current-reference projection and CAS guards
that same epoch; concurrent new references cancel deletion rather than disappearing.

No archive operation writes or deletes S3 objects. Tombstones and operation audit records live
in retained DynamoDB partitions. Projection refresh and all-game index verification respect
tombstones, so delayed source events cannot resurrect an archived asset.

## Rollout

Deploy the producer guards and archive endpoints with CDK first. The archive API fails closed
until every game's existing current profiles, appearances, scenes and processing pins have
been backfilled and verified. Use Panther authentication; no direct S3 mutation or AWS account
inventory belongs in the repository.

```sh
panther assets archive-migrate --all-games --mode dry-run
panther assets archive-migrate --all-games --mode apply
panther assets archive-migrate --all-games --mode verify
panther assets archive-migrate --all-games --mode activate
```

The migration preserves bytes and all source/history records. It inventories only explicit
stored references, checks the game epoch across the snapshot and commits with optimistic
conditions. Concurrent changes fail rather than rewriting newer selections. Retry the affected
game's apply/verify after resolving conflicts. Oversized or ambiguous inventories block
activation; extend the bounded migration instead of silently truncating it. Keep any detailed
private operational reports outside Git.

For a deliberate single-asset archive, obtain the exact base64 SHA-256 through the asset's
existing inspection operation, then run:

```sh
panther assets archive --game example --key games/example/assets/map/original/map.png --sha256 BASE64_SHA256
```

An operation identity may be retained with `--operation-id` for exact retries. Reusing it with
different arguments fails. A successful response acknowledges logical archival, never physical
erasure. There is no historical deletion or automatic restoration in this contract.
