# Indexed asset browsing (v1)

S3 stores immutable files and their location records. DynamoDB stores a regenerable browsing
projection: titles, type, metadata, explicit source links, recording/playback summaries and warnings.
Reading `/assets` never lists S3 or opens source documents. `/asset-document` still reads a single
selected source; metadata and JSON reads use the same S3 version when available.

The old implementation listed 25 location records, sequentially resolved each and checked its
payload, then resolved/read the metadata and JSON again. Every section awaited all pages. Its
latency and S3 request count grew with the whole game, including hidden workflow artifacts.

The new API uses retained, pay-per-request DynamoDB partitions for each game and section (`all`,
`audio`, `transcripts`, `videos`). It queries at most 100 entries/1 MiB, returning a scoped cursor.
Audio/Transcripts/Videos render one page and load more only on request. Video plans are included
in Videos. Standard lossless recording chunks and listening derivatives stay in the complete
catalog and recording reader, not as separate Audio cards. Matching transcript Markdown exports
are suppressed using a bounded indexed lookup, including across page boundaries.

Opening a media file still obtains a short-lived authenticated URL. Full relationship graphs and
novel reference enrichment can page through the complete **metadata index**, not source S3 files;
their existing 5,000-entry limit remains explicit. That graph work is not needed to list Videos.
There is no claim that arbitrary-size relationship graphs are constant-time or that cold starts
and network latency disappear. The file-tree browser is a separate physical-folder view.

## Maintaining the projection

CDK enables native S3 → EventBridge notifications on the private bucket. Only `Object Created`
events under `games/*/content/*` reach the indexing Lambda. This includes successful uploads,
multipart completion and metadata-only copies, not reservations or failed/interrupted uploads.
It resolves the existing immutable locator, reads the current source, and transactionally replaces
all section memberships. Delayed/duplicate events read current data, not historical event bytes.
An optimistic revision condition rejects concurrent stale commits; retries reread the source.
Source bytes, locators, identity, provenance and source version history are never modified.
Index records above 350 KB fail explicitly; no links are silently truncated.

Updates are eventually visible after event processing; refresh after uploading. EventBridge target
delivery and asynchronous Lambda failures go to the CDK-created 14-day failure queue. Inspect
failures/logs after migration and when an upload fails to appear; use the authenticated rebuild
command to reconcile. This queue is not a notification subscription or an automatic replay worker.
No user-facing deletion exists; future deletion support must explicitly update this projection.

## Rollout and all-game verification

1. Run local checks and the self-hosted Playwright gate. Review/merge the PR.
2. Inspect the CDK diffs for Foundation and MediaExplorer in the established account/us-west-2,
   preserving existing budgets, account identities, permissions and buckets. Supply private identity
   configuration and the existing budget email outside Git. Deploy the foundation event setting
   and media stack through CDK. There are no manual AWS resource writes.
3. Run `panther assets rebuild-index --mode dry-run --report /private/path/new-dry-run.jsonl`.
4. Inspect that report, then run the same command with `--mode apply` and a new private report.
5. Run `--mode verify` with another new report. Every published source is independently re-projected
   and compared with every section membership, across every discovered game. Unfinished upload
   reservations are explicitly reported, not counted as published files. Any mismatch blocks CLI
   activation. Successful full verification activates indexed browsing; the server also checks
   verification markers for all S3 game prefixes. Before initial activation, readers return an
   upgrade-in-progress error, never a falsely empty or partial library. Future new games use the
   same event-maintained index without a separate activation.
6. Check the failure queue, compare source/index inventories and time authenticated catalog reads.
   Verify the website on both screen sizes. Keep private reports outside Git. Do not call the
   rollout complete until this all-game backfill and production verification finish.

Requests process 20 source reservations at a time with eight workers. A failed/interrupted run can
be repeated with a fresh report: source data is untouched and writes are conditional/idempotent.
Do not activate a partial migration manually. The projection schema is versioned (`v1` keys);
future schema changes require another full migration. There is no old S3-scan read fallback.

At rest this adds index storage, not provisioned compute. DynamoDB, Lambda, events and the failure
queue are usage-based; no EC2, NAT gateway, VPC, provisioned concurrency or idle polling was added.
Writes duplicate small summaries into relevant sections, not media bytes or whole manuscripts.

References: [S3 EventBridge events](https://docs.aws.amazon.com/AmazonS3/latest/userguide/EventBridge.html),
[event structure](https://docs.aws.amazon.com/AmazonS3/latest/userguide/ev-events.html).
