# The Workshop

The per-game Workflows page groups individual runs beneath expandable workflow
types. A run shows a responsive step flowchart with dependency arrows, parallel
adaptation branches and independently queued tasks as appropriate. The graph is
a read-time projection of the implemented pipeline, not a new execution plan;
it applies to historical and future observations without altering job evidence.
Animated pixel cats indicate recently confirmed work, not merely queued
jobs. Stage counts measure completed steps, not elapsed-time percentages, quality
approval, publication, or predicted completion. Expired leases and stale local
reports are explicitly shown; the browser never starts, retries, or funds work.

## Projection and access

CDK owns a retained, on-demand DynamoDB observation index and two Lambda functions.
Stream observers read current authoritative editorial, model, playback and final
browser-transcription jobs. Conditional revisions prevent an older stream event
from overwriting newer observations. Only whitelisted status fields enter the
projection: no transcript text, task tokens, credentials or account identities.

The JWT-protected reader queries bounded, game-scoped pages (30 records). It has
no source-table scan, S3, Step Functions or workflow-execution permission. Pages
fail closed until all durable sources have been backfilled. Readers need catalog
access; reporting and explicit rebuilds require the existing worker capability.
Browsing never falls back to scanning source storage. The browser checks every
15 seconds only while the Workshop is visible; requests time out and preserve
the previous view with an explicit stale-data warning.

## Local work

`panther video submit` and `poll` report existing budget-ledger observations;
reporting does not call a provider or modify spending. `panther video-production`
reports actual checkpoint transitions and checks in every minute during local
processing. Reporting failures preserve private checkpoints and a latest local
outbox; subsequent check-ins can retry observations, never generation.
The UI distinguishes generation from finishing and planning. Older workflows
that do not report finer substeps remain honestly coarse-grained.

## Deployment and historical backfill

After deploying the reviewed CDK stack, use Panther authentication:

```sh
panther workflows rebuild
panther workflows import-video-ledger
panther workflows import-production /absolute/private/path/to/immutable-run-id
panther workflows list --game example-game
```

The rebuild drains all four durable sources in bounded resumable pages, without
writing source jobs. It is repeatable; stream updates maintain the projection
afterward. Import every retained local production run with genuine receipts.
Production imports validate checkpoint and result checksums; missing stages stay
pending, and incomplete historical work stays paused. Never reconstruct status
from filenames, generate missing stages, or label unavailable local evidence as
completed. Keep inventories, logs, receipts and observations outside Git.

Follow list cursors for each game and inspect detail records before declaring the
rollout complete. Record any unavailable historical local evidence explicitly;
do not add compatibility paths or pretend that every old process reported stages.
