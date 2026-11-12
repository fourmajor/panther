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
speaker groups across the recording rather than treating each
30-second chunk as an independent final identity decision. Transcript alignment uses
pyannote's exclusive diarization, the timeline without overlapping speech. Player identity
uses the same full-waveform extractor as confirmed enrollment, run on each speaker's
exclusive speech. Cluster centroids stay in the diarization file as diagnostic evidence
and are not the identity prototype. Private input pins, progress, diarization and the
final transcript survive completion and restarts. A saved diarization from before
exclusive reference embeddings is not reused; leave it in place and rerun in a new
private work directory. The pass uses the existing offline
pyannote weights on the laptop's MPS device, with bounded batches and no paid service.
Uncertain voices remain unknown. Chunk-level recognition and timestamp limitations remain visible. There is no
automatic enrollment or inference of identity from character dialogue.
Explicit enrollment now extracts the confirmed single-speaker reference waveform directly,
retaining its diarization/clustering evidence separately. A short-reference clustering vector
can disagree with the very source used to enroll it; it must not silently become the identity
prototype. Enrollment checks reference-to-roster ambiguity and records the extraction method.
Existing immutable enrollments remain historical evidence: rebuild a new revision from the exact
confirmed source checksums and explicitly select it, never overwrite or train from guessed labels.
Word-timing recovery must demonstrate improvement on the actual session before publication;
reusing approximate tokens alone does not guarantee better assignments.
An all-zero runtime speaker embedding is unavailable identity evidence, not permission to
choose the nearest player or discard speech. Preserve that analyzer result and mark affected
utterances unassigned with an attribution warning. The session diarization file uses the same
unavailable-embedding record as the chunk pass, so one non-finite speaker does not discard the
other speakers. Transcript text shows the diarized speaker label when the player is unknown.
Unassigned means there is no player and no speaker label. Malformed evidence and invalid enrolled
profiles still fail closed. Reconciliation assigns each diarized speaker to a different enrolled
player. A match is kept when its cosine leads the runner-up by at least 0.1, or when the cosine
is at least 0.75. A tie stays unknown. After reconciliation, a player-assignment rate below 25% of
segments fails the handoff. An accepted cosine below 0.75 is logged as a prompt to re-enroll that
profile from a clean sample.
The local candidate and the cosine for each diarized speaker are kept; the transcript is
not published and adaptation does not start. A near-zero rate is a broken mapping, not a
successful unknown.
Very brief speech can also produce non-finite runtime embeddings. The analyzer retains
those exact values as diagnostic strings in `unavailableEmbeddings`, emits no usable
identity vector for that turn, and preserves its speech/timing with an unassigned-speaker
warning. This cannot authorize enrollment or weaken matching thresholds. Earlier failed
partial results remain preserved; resuming reuses completed chunk checkpoints rather than
retranscribing the session.
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
while logged in and awake. The editorial worker is a separate resident LaunchAgent. It uses the
same pinned release and Panther authentication. Its inference is subscription Codex through a
ChatGPT login on that machine, with no API-key fallback. Upgrades require explicitly stopping
old services and preserving their plists/releases. A failed Panther refresh stops the worker
heartbeat; Workshop and the pipeline SNS alarm show that worker as offline. Never replace an
authentication error with AWS asset writes or a paid inference fallback.

Writing prompts use a versioned reading projection retaining every utterance, timestamp,
player label and capture warning, while detailed per-word analysis stays in the exact pinned
raw asset. Raw inputs up to 16 MiB are supported. There is no silent truncation and no rewrite
of previous transcript or chapter editions. Independent review receives one complete raw
transcript plus a verified correction overlay, not two duplicate copies of its speech. The
overlay is emitted only when its edits exactly reconstruct the candidate and all non-text
speech fields are unchanged. Full corrected assets remain stored unchanged. Prompts stay below
the observed one-Mi-character CLI transport limit. Correction reviews at most 80 utterances
per call, and both correction and corrected-transcript split a prompt that would exceed
1,000,000 bytes. Each window is merged. Unambiguous capitalized catalog names are repaired
in code before the model runs. Each window's
candidate corrections are the edits for that slice; a review edit replaces the same utterance,
and an empty edit list does not revert the slice to raw wording. An empty correction while a
catalog name is still misspelled fails the job instead of continuing on raw speech, and the
failure names the segment, the word, and the catalog spelling. A prompt that still cannot fit
fails once, with the measured size stored on the task, and is not retried as a subscription failure.
