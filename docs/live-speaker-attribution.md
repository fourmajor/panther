# Live player attribution

`panther recording live` can recognize enrolled players while consuming completed capture
chunks. Capture remains a separate process. Recognition runs locally with the existing
pyannote Community-1 audio runtime; no API billing, voice upload, new cloud resource or
microphone access is introduced. This is near-live chunk processing, not sample-level streaming.

## Enroll once, reuse in future sessions

Prepare private mono 16 kHz PCM16 WAV reference clips, 10–120 seconds of clean speech each.
Confirm identity from introductions or an owner-labeled sample, never character dialogue,
cluster order, accent guesses or another run's anonymous speaker label. More clean speech
is preferable to noisy or overlapping speech. Enrollment detects one speaker but cannot
independently prove the supplied name is correct.

The owner-only manifest outside Git has `gameId` and `samples`. Each sample has `playerId`,
an absolute `file`, its `sha256`, `confirmedSingleSpeaker: true`, and an `identityEvidence`
description. The command checks player IDs against Panther's authenticated game roster.

```sh
panther recording enroll-speakers /PRIVATE/enrollment.json --output /PRIVATE/profiles-v1.json
panther recording live /PRIVATE/recording-ID --from-start --speaker-profiles /PRIVATE/profiles-v1.json
```

Profiles are immutable recognition embeddings, not voice-synthesis models. They pin the exact
local weights and source audio checksums. Keep them private; don't check them into Git, expose
them in web responses or use them as login credentials. Re-enroll to change identity evidence
or model weights. Recognition permission does not imply permission to synthesize speech.

## Conservative live decisions

Each completed chunk retains raw Whisper output and speaker analysis. A label requires cosine
similarity >= 0.75 and a >= 0.15 lead over the next profile. These are conservative starting
parameters, **not calibrated accuracy or probability claims**. Validate with held-out labeled
speech before relying on them. Mixed/overlapping segments and weak matches remain unassigned.
Never learn new profiles automatically from provisional matches (that compounds mistakes).

The preview identity includes the profile checksum and model pins. Restarts reuse saved chunks;
changing enrollment makes a distinct preview, preserving old results. A failed speaker pass
saves text without labels and a private error record. Capture and backup continue independently.
Network publication failures are retried separately. Browser labels explicitly say provisional
and resolve names from the selected game's players, never characters or arbitrary supplied names.

Older unlabeled previews remain compliant: identity is unknown, not an invented historical
assignment. No existing transcript evidence is rewritten by enabling this feature.

## Performance and final review

Measure the combined recognition/transcription time against chunk duration on the target laptop.
The live CLI allows Whisper GPU acceleration by default; `--cpu` disables it. This setting is
pinned in the preview identity, so changing it preserves the prior preview rather than overwriting it.
The live worker keeps the speaker pipeline resident, with two CPU threads, low
priority and a 180-second per-chunk deadline, using Apple MPS with bounded batches when available.
It may fall behind; no real-time guarantee is made. The first chunk includes model startup time.
On the development Mac, a two-chunk local check measured roughly 39 seconds for the first
30-second chunk (startup included) and 22 seconds for the next, combining Whisper and resident
MPS speaker analysis. CPU-only speaker analysis alone took roughly 83 seconds for one chunk.
Other local analysis was active during these measurements. This small throughput check is not
a sustained recording benchmark, speaker-identity accuracy test, or guarantee for other hardware.
Do not trade away capture reliability or silently switch to a paid provider.

Completed live recognition is provisional. Final reconciliation should reuse its saved evidence
and focus on gaps/uncertain intervals. `panther recording finish-live /PRIVATE/recording-ID/live-preview/PREVIEW`
checks every source/checkpoint and creates separate local raw and provisionally attributed
transcript versions, without rerunning recognition or triggering editorial work. Missing chunks
and recognition gaps block finalization rather than silently producing an incomplete transcript.
The current full-session `recording diarize` remains a separate
optional quality pass, not something automatically launched by this preview.

## Voice synthesis follow-up

Store consent evidence and verified clean source clips separately from recognition embeddings.
A future local synthesis profile must pin its actual model, reference samples and consent scope.
Generated speech must be labeled synthetic with source provenance, never added to raw transcripts
as if it were recorded conversation. Provider uploads or paid inference require separate approval.

When authorized, publish profiles and reference audio through normal Panther uploads, not AWS
commands. Use distinct immutable assets with kinds `speaker-recognition-profile`,
`voice-synthesis-profile`, and `voice-reference-audio`, explicit `extra.playerIds`, exact sourceKeys,
`category: reference`, `extra.contextUse: exclude`, and generation metadata. Recognition embeddings
are not synthesis weights: a reference-conditioned synthesis profile may consist of source clips,
configuration and an exact base-model revision rather than per-person trained weights. Describe
what actually exists. Keep consent evidence linked and its verification status honest. Strip local
filesystem paths from published manifests; retain local originals. Old revisions remain available.
