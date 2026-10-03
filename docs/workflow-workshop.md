# The Workshop

The per-game Workflows page contains workflow types only. Each type shows exact
run totals, successful and failed counts, and its latest run date in a compact row.
Right chevrons indicate navigation into the hierarchy. Run rows show available output
thumbnails; run details show one overall status and zoomable output previews.
Select a type
to browse its paged history, then select a run to inspect reported stages and
outputs. These are nested routes, so reload, Back and direct links preserve the
current view:

- `/games/:game/workflows`
- `/games/:game/workflows/:type`
- `/games/:game/workflows/:type/:workflowId`

Stage counts describe completed steps, not elapsed-time percentages or predicted
completion. Browsing never starts, retries or funds generation.

## Projection and access

CDK owns a retained, on-demand DynamoDB observation index and two Lambda functions.
Stream observers read current authoritative editorial, model, playback and final
browser-transcription jobs. Conditional revisions prevent an older stream event
from overwriting newer observations. Run observations and per-type totals update
in one DynamoDB transaction. Status changes replace their previous count rather
than incrementing a second run. Only whitelisted status fields enter the
projection: no transcript text, task tokens, credentials or account identities.

The JWT-protected reader queries bounded, game-scoped pages (30 records). It has
no source-table scan, S3, Step Functions or workflow-execution permission. Pages
fail closed until all durable sources have been backfilled. Type totals additionally
require hierarchy version 1; they never count only the currently loaded run page. Readers need catalog
access; reporting and explicit rebuilds require the existing worker capability.
Browsing never falls back to scanning source storage. The shared React Query layer checks type/run views every 15 seconds while mounted
and active run details every 5 seconds. Unmounting stops their polling.

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

The rebuild drains all four durable sources and then the hierarchy catalog in
bounded resumable pages, without writing source jobs. The final hierarchy pass
includes retained local progress reports and materializes exact per-type totals.
It sets the hierarchy version marker only when the pass completes; partial rebuilds
remain unavailable to readers. Each type supports up to 10,000 retained records
during initial aggregate construction; exceeding that bound is an explicit rebuild
blocker, never a partial total. It is repeatable; stream updates maintain the projection
afterward. Import every retained local production run with genuine receipts.
Production imports validate checkpoint and result checksums; missing stages stay
pending, and incomplete historical work stays paused. Never reconstruct status
from filenames, generate missing stages, or label unavailable local evidence as
completed. Keep inventories, logs, receipts and observations outside Git.

Follow list cursors for each game and inspect detail records before declaring the
rollout complete. Record any unavailable historical local evidence explicitly;
do not add compatibility paths or pretend that every old process reported stages.

The SQLite development backend derives exact totals from its authoritative job
records, uses the same type/status contract, and pages each selected history at
40 runs. It does not create synthetic jobs or need a cloud rebuild. Production
rollout requires deploying the reviewed code and completing the authenticated
`panther workflows rebuild` before checking every game's type totals and run pages.
