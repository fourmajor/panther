# Speaker-detection progress

New `panther recording diarize` runs print their run directory and save an atomic
`progress.json` there. Read it at any time without AWS access:

```sh
panther recording speaker-status /PRIVATE/recording-ID/speakers-RUN
panther recording speaker-status /PRIVATE/recording-ID/speakers-RUN --json
```

The snapshot reports decoding parts, segmentation batches and speaker-embedding batches
using actual library counters. It also reports model loading, clustering, finalization and
result writing, where no trustworthy batch percentage is available. Busy stages refresh
at most once every two seconds; transitions and final events are written immediately.

`stagePercent` refers only to the named stage. `overallPercent` is null until the result
has been successfully written, then 100. Never turn a stage percentage or elapsed runtime
into an overall percentage. Stages have very different costs. The timestamp means last
observed progress, not a heartbeat: clustering can run without additional callbacks.

Successful, failed and gracefully interrupted runs record terminal state. An abrupt kill,
power loss or inability to write the disk can leave a stale running snapshot; inspect process
state separately. Snapshots contain counters, not audio, embeddings, credentials, or inference
checkpoints. They do not make a batch run resumable.

Already-running workers cannot gain these hooks retroactively. Old runs with no snapshot
explicitly report progress unavailable; preserve their output and do not restart them solely
to obtain a percentage. No existing game asset schema changes or data migration is required:
this is optional local operational telemetry, not a transcript or published game artifact.
