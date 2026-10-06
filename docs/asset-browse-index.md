# Indexed asset browsing (v4)

S3 stores immutable files and their location records. DynamoDB stores a regenerable browsing
projection: titles, type, metadata, explicit source links, recording/playback summaries and warnings.
Version 2 also projects structured transcript summaries: observed player IDs/names, segment counts,
unassigned segments and source-reported review/publication status. A roster is not attendance;
unknown names/statuses remain unknown. Unreadable/nonstructured documents report unavailable,
not a fabricated empty transcript. The projection contains no speech text.
Version 3 also projects observed novel titles, session/workflow identity and source review status,
without manuscript text. `/novel` queries this bounded catalog and batch-checks the exact completed
workflow outputs. It does not open every manuscript or scan all workflow runs. Reading an individual
chapter still validates its source checksum and envelope. Source AI review acceptance is not an
owner-approved book selection or a declaration of canon.
Version 4 adds explicit recording names, capture dates and summed source-part audio duration.
Missing part durations remain unknown. Sessions combines recording/playback and transcript assets
with the same explicit session identity or source lineage into one card; generated speech/music
remain in Assets. Audio controls point to an actual listening derivative, never a fabricated file.
Short summary excerpts load through the existing source-pinned summary API and expand inline; reading does not generate summaries. Previously published source bytes,
metadata, capture warnings and original parts remain unchanged.
Reading `/assets` never lists S3 or opens source documents. `/asset-document` still reads a single
selected source; metadata and JSON reads use the same S3 version when available.

The old implementation listed 25 location records, sequentially resolved each and checked its
payload, then resolved/read the metadata and JSON again. Every section awaited all pages. Its
latency and S3 request count grew with the whole game, including hidden workflow artifacts.

The new API uses retained, pay-per-request DynamoDB partitions for each game and section (`all`,
`audio`, `transcripts`, `videos`, `novels`). It queries at most 100 entries/1 MiB, returning a scoped cursor.
Sessions/Videos render one page and load more only on request. Video plans are included
in Videos. Sessions is a logical union of audio and transcript assets from the existing
`all` partition: each request remains bounded, its cursor is scoped to Sessions, and a sparse
filtered page can offer Load more. The v4 all-game rebuild enriches immutable recording facts and updates Sessions membership; it creates no separate Sessions partition.
Standard lossless recording chunks and listening derivatives stay in the complete
catalog and recording reader, not as separate Sessions cards. Matching transcript Markdown exports
are suppressed using a bounded indexed lookup, including across page boundaries.

Opening a media file still obtains a short-lived authenticated URL. Lists request `view=cards&limit=24` and never drain cursors automatically. Optional `characterId`
and `mediaType` filters apply to each bounded catalog page; a sparse page can still offer More.
Cursors bind the filters and page size. Card responses exclude full generation requests and lineage.
`keys` reads at most 60 exact same-game metadata records. `relatedKey` returns only the connected
lineage component, with a 2 MiB response ceiling. Reverse-link discovery still reads the server's
bounded metadata index (5,000 records maximum); it does not transfer that inventory to the browser. That graph work is not needed to list Videos.
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

Updates are eventually visible after event processing; the application invalidates its cached queries after uploads. EventBridge target
delivery and asynchronous Lambda failures go to the CDK-created 14-day failure queue. Inspect
failures/logs after migration and when an upload fails to appear; use the authenticated rebuild
command to reconcile. This queue is not a notification subscription or an automatic replay worker.
Logical asset removal retains original bytes and history, and excludes archived assets from browse pages.

## Rollout and all-game verification

Catalog v4 uses separate partitions and fails closed until this all-game rebuild is verified and activated.
No v3 fallback is used by readers; preserve the old projection until cutover verification succeeds.

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
Maintenance retries a concurrent index/transaction guard at most four times with short jittered
backoff. Each attempt rereads current source data and the index revision; stale transactions are
never replayed. Exhausted contention still fails the page and blocks activation.
Do not activate a partial migration manually. The projection schema is versioned (`v3` keys);
future schema changes require another full migration. There is no old S3-scan read fallback.
The v1/v2 readiness/verification markers cannot authorize v3. Repeat the full dry-run/apply/verify
sequence for this upgrade; old projection rows may remain as unused history, never a read fallback.

At rest this adds index storage, not provisioned compute. DynamoDB, Lambda, events and the failure
queue are usage-based; no EC2, NAT gateway, VPC, provisioned concurrency or idle polling was added.
Writes duplicate small summaries into relevant sections, not media bytes or whole manuscripts.

References: [S3 EventBridge events](https://docs.aws.amazon.com/AmazonS3/latest/userguide/EventBridge.html),
[event structure](https://docs.aws.amazon.com/AmazonS3/latest/userguide/ev-events.html).

## Dashboard recent summaries

Session grouping resolves each immutable lineage node once per request using an
iterative graph walk. Shared derivations must not cause repeated recursive expansion.
Cycles are explicit data errors, not invented session identities or partial totals.

`GET /dashboard-recent?gameId=...` is a catalog-reader operation. It returns five recent
characters, transcripts, finished videos and chapter editions plus complete category counts
in one browser request. Paired transcript Markdown/JSON exports count once. Every category
is selected after reading the complete game's materialized metadata partition; it never
labels the first page's locally sorted rows as the game's recent inventory.

There is currently no event-maintained recency sort index. This operation reads metadata
in bounded DynamoDB pages and sorts it in memory: initial backend work is O(N), not O(5).
The frontend query cache reuses this result for 60 seconds. It never reads S3 payloads,
downloads asset documents, signs images or silently falls back to a storage scan. The
complete-summary bound is 5,000 indexed rows, 16 MiB of serialized metadata, 200 pages,
and 500 registered characters. Exceeding a bound or an unprepared catalog returns an
explicit unavailable response; no partial groups or counts are returned.

Asset ordering uses recorded `lastModified` values. Character ordering uses actual catalog
update/creation dates or the current immutable details revision's recorded history date.
Unknown timestamps stay null and sort after dated items, with stable identity ordering;
neither a zero timestamp nor a name is used to invent creation history. History actors
and full character details are omitted from dashboard summaries. This read-time projection
needs no asset rewrite or historical-date migration. A future indexed recency projection
would require its own versioned all-game rebuild and verification before replacing this
complete metadata traversal.

## User tag vocabulary and chapter reviews

The `tags-v1#<game>` projection stores the user tag vocabulary separately from asset rows.
Tag names are case-insensitive identities, with the first stored spelling retained; existing
asset tags remain unchanged. Source indexing transactionally adds each asset's observed tags
alongside section updates. A tag remains available when no current asset uses it. `GET /tags`
reads this bounded complete vocabulary; `POST /tags` creates a user tag without rewriting assets.
Neither operation scans S3. A vocabulary above 1,000 names reports unavailable rather than
silently returning a partial selector.

Deploy this projection with the scoped metadata Lambda, then repeat the authenticated all-game
`panther assets rebuild-index` dry-run, apply, verify and activate sequence above. Verification
checks every existing asset tag against the vocabulary and writes a per-game `tags-v1#verified`
marker only after the complete game passes. Activation requires both asset and tag verification
for every discovered game before setting `tags-v1#catalog/ready`. Until activation, the new tag
API returns an explicit migration-unavailable response. This migration preserves source bytes,
original metadata and historical tag spellings; no source-content migration or inference occurs.

`GET/POST /novel-review` stores the user's Approved/Rejected decision independently of the
immutable manuscript and AI review evidence. Writes require the publisher capability, a guarded
expected review revision and an idempotent operation identity. A transaction checks the completed
source chapter record/output and retains each prior review with the exact chapter reference.
This metadata Lambda cannot change manuscripts or jobs, dispatch generation, or access S3.
The novel reader's existing read-only permissions remain unchanged.

## Video covers

List cards never mount a video element or sign/download a video to find a frame. They use an
explicit same-game `thumbnailKey` or `extra.preview.imageKey`, otherwise a format placeholder.
Image signing is viewport-triggered, batched (at most 60 keys) and cached below the signing TTL.
Opening a video explicitly still obtains its playback URL. Missing covers do not poll indefinitely.

Prepare covers outside browsing with `panther assets video-covers --all-games --work-dir PRIVATE_DIR`.
This audits without downloading or writing. Add `--apply` to extract a nonblank frame from the
first ten seconds with local FFmpeg, upload an immutable `video-thumbnail`, and link the exact
source through a version-guarded metadata migration. Source bytes and prior metadata stay intact.
Private receipts and migration records make the operation resumable; ambiguous uploads stop for
inspection rather than overwriting. Run this after publishing new videos and for every existing game.
No new index version is needed: these are read-time projections over existing metadata fields.
