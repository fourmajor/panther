# Stop recording → session production

The reviewed laptop worker consumes the existing **server-verified COMPLETE chunk sets**,
not an individual upload, UI stop event, quiet period, or local filename. Completing capture
and finishing its cloud sync is the trigger. The uploader remains independent of processing.
AWS's completed-set record is the durable queue; sleeping/offline owned compute delays work.
Both native FLAC and browser WAV completed sets use this owned-compute path; original formats
and capture warnings remain unchanged. This does not enable or repeat paid browser ASR.
No new always-on cloud compute or paid recognition provider is required.

Run `panther recording automation worker --config PRIVATE_CONFIG --work-dir PRIVATE_DIRECTORY`.
`--once` drains each currently eligible recording once. A private per-game `completedAfter`
activation boundary prevents unexpectedly adapting old tests. Recover older desired sessions
explicitly using their preserved raw transcript and `panther editorial submit`.

Private version-1 configuration contains `games`, a mapping from game ID to:

- `whisperModel`: absolute local Whisper weights path.
- `speakerProfiles`: confirmed, immutable enrolled recognition profiles, not synthesis weights.
- `speakerModel` and `speakerRuntime`: the existing local pyannote model/runtime paths.
- `recordingsRoot`: private local capture root, for checksum-verified reuse of live ASR evidence.
- `completedAfter`: UTC Unix completion timestamp activating this game.

Never commit configuration, player identities, enrollment samples, or processing inventories.
The worker verifies pinned audio, reuses each checksummed live recognizer result where complete,
and recognizes only missing/gapped intervals. Original ASR output remains unchanged. It saves
an unassigned raw transcript, provisional chunk annotations, and a separate session-wide
enrolled-voice reconciled version before adaptation handoff. The session pass uses stable
speaker groups and aggregate embeddings across the recording rather than treating each
30-second chunk as an independent final identity decision. Its private input pins, progress,
diarization and final transcript survive completion/restarts. It uses the existing offline
pyannote weights on the laptop's MPS device, with bounded batches and no paid service.
Uncertain voices remain unknown. Chunk-level recognition and timestamp limitations remain visible. There is no
automatic enrollment or inference of identity from character dialogue.
An all-zero runtime speaker embedding is unavailable identity evidence, not permission to
choose the nearest player or discard speech. Preserve that analyzer result and mark affected
utterances unassigned with an attribution warning. Malformed evidence and invalid enrolled
profiles still fail closed.
When fresh ASR preserves readable text but returns invalid detailed timestamps, retain the
original response and all text in source order with an explicitly approximate whole-chunk
interval. Keep player identity unknown for that interval. Never clip away words, infer precise
timing, or invent missing speech. Malformed/unavailable text remains an explicit failure.

Per-chunk checkpoints, speaker evidence and measured chunk counters survive interruptions.
The session diarization progress reports genuine stage counters, not an overall percentage.
An interrupted model pass is not resumable within its inference batches; retain its evidence
and use a new private work directory for an explicit rerun, never silently replace files.
Changed inputs/checkpoints stop the run. A process lock prevents competing local workers.
Publication uses Panther's authenticated no-overwrite uploads and an idempotent editorial
commit. Partial publication is reconciled by those contracts, not repeated inference or S3 writes.
Novel and screen-planning stages run in the separate subscription-backed editorial worker.

Workshop shows **Session finalization** with input verification, raw preservation, player
matching, publication, and adaptation handoff. Chunk progress is in the private run's
`recognition/progress.json`; its percent measures completed chunks, not the entire creative
pipeline. Successful handoff is not a completed chapter or film. Follow the editorial run for those.

## Production approval

Stop automatically prepares the script/storyboard and finishes the novel, but **paid video
generation still waits for owner approval of the script/storyboard**. The standing authorized
ceiling is $10 per session using the established fal production models. Approval is tied to
the exact plan/input revisions, never inferred from recording completion or preflight success.
This ceiling is not permission to reset a ledger, buy credits, enable top-ups, clone voices,
automatically retry paid generation, or use an alternative provider. Premium separate speech,
when part of an approved project, shares the same total. Existing comparison history is retained.

## Installation

From clean, fetched and reviewed merged main:

```
.venv/bin/python ops/session-worker/install.py --repo "$PWD" --config PRIVATE_CONFIG --start
.venv/bin/python ops/editorial-worker/install.py --repo "$PWD" --start
```

The session LaunchAgent is `place.panther.session-worker`; it performs one pass per minute
while logged in and awake. The editorial worker independently executes queued creative stages.
Both use pinned, non-editable releases and normal Panther authentication. Upgrades require
explicitly stopping old services and preserving their plists/releases. Authentication errors
must remain visible; never replace them with AWS asset writes or a paid inference fallback.

Writing prompts use a versioned reading projection retaining every utterance, timestamp,
player label and capture warning, while detailed per-word analysis stays in the exact pinned
raw asset. Raw inputs up to 16 MiB are supported; prompt/result size limits still fail visibly.
There is no silent truncation and no rewrite of previous transcript or chapter editions.
Independent review receives one complete raw transcript plus a verified correction overlay,
not two duplicate copies of its speech. The overlay is emitted only when its edits exactly
reconstruct the candidate and all non-text speech fields are unchanged. Full corrected assets
remain stored unchanged. Prompts stay below the observed one-Mi-character CLI transport limit;
oversized evidence fails visibly rather than being truncated or treated as a subscription limit.
