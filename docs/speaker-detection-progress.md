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

## Word-level attribution reruns

`panther recording attribute RAW_TRANSCRIPT_DIRECTORY --diarization FILE --mapping FILE
--word-level` reuses completed diarization and the original `asr-output/transcription.json`.
It never reruns recognition, changes raw wording, trains voice identities, publishes assets, or
starts editorial jobs. The private mapping must belong to this exact diarization run and be
supported by confirmed introductions; that does not guarantee cluster consistency throughout.

Words are grouped from original Whisper tokens, not evenly distributed across a sentence.
Invalid/missing token timings retain conservative whole-segment attribution. Text/timestamp
mismatches between source documents fail closed. Exact source hashes, settings, word decisions,
source-segment indexes and the original anonymous diarization remain available for audit.

The balanced defaults require 65% exclusive speaker coverage of a word, a 25-percentage-point
lead over the runner-up, and at most 10% simultaneous speech. `--minimum-coverage 0.8` is stricter;
`--winner-margin` adjusts the required lead. These are temporal ratios, not voice-similarity scores
or accuracy probabilities. Unknown clusters stay unknown. Whisper token timing is approximate,
not acoustic forced alignment; results remain unreviewed and can still misidentify speakers.

The printed output folder has `progress.json` with actual completed/total source segments,
`processingPercent`, elapsed seconds, an **estimated** remaining duration and finish timestamp.
The estimate extrapolates measured throughput, excludes later review/publication, and remains
unavailable before the first completed batch. Completed state is written only after transcript
and diarization files are saved. Failures retain the last completed count; stale snapshots require
checking the process, not assuming it is still running. These fields are separate from the
diarization stage counters described above; read this file directly for attribution status.

`attribution-report.json` reports assigned duration and timing fallbacks. Parent time intervals
are partitioned without loss so baseline/rerun duration percentages are comparable. They include
pauses within ASR segments and are **not** exact speech-time coverage or verified accuracy.
Keep originals; a rerun is a new experimental transcript revision, not a migration rewriting evidence.
