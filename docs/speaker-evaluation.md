# Local speaker experiments and identification validation

Speaker separation and real-person identification are separate stages. A detected label is
not an identity, the player roster is not a fixed speaker count, and assigned percentage is
not accuracy. Recorded media can introduce additional voices. Keep the corrected words,
timing, original takes and prior transcript versions unchanged during experiments.

## Pinned local alternative

`panther recording diarize-nemotron` runs a reviewed native NVIDIA NeMo-Speech.cpp runtime
with an explicitly pinned local Nemotron-3-Diarization GGUF. Obtain the runtime/model from
the official releases/model index and verify their published checksums before use. The command
does not install anything, download weights, upload audio, transcribe again, assign player names,
change the active worker, publish or invoke a paid fallback.

```sh
panther recording diarize-nemotron /PRIVATE/recording \
  --runtime /PRIVATE/reviewed/nemo-speech --runtime-sha256 REVIEWED_SHA256 \
  --model /PRIVATE/reviewed/model.gguf --model-sha256 REVIEWED_SHA256 \
  --work-dir /PRIVATE/new-analysis
```

The source set must pass the existing recording checksum validation. A separate mono 16 kHz
listening derivative is assembled locally, then the bounded `v3-offline` preset runs on CPU.
Do not use full-attention `--offline` for an entire long session. Results retain model/runtime
pins, exact parts, anonymous overlapping turns and actual timings. Completed evidence can be
read again without inference; changed or partial evidence fails closed for inspection. This
command is an experimental producer, not automatic selection of a new production model.

Official sources:
- https://huggingface.co/nvidia/Nemotron-3-Diarization
- https://github.com/NVIDIA/NeMo-Speech.cpp
- https://www.pyannote.ai/benchmark

Benchmark comparisons must use the same source audio, annotations, collar and overlap policy.
Published vendor numbers across different datasets do not establish a universal ranking.

## Named identification and calibration

The `speaker_evaluation.identify` helper requires multiple distinct, non-overlapping confirmed
references per person. It requires support from the second-best reference as well as a lead
over competing identities. It permits unknown, does not force a one-to-one mapping of anonymous
clusters to players, and never learns from provisional matches. All embeddings passed to it
must come from the same separately pinned recognition model; equal dimensions are not proof
of compatibility. A production adapter must verify model pins before invoking this helper.

Reference candidates may be selected automatically from already confirmed introduction
material. A previous diarizer's inferred full-session assignments are not independent truth.
Reject overlap, mixed voices and confirmed playback; the fact that a model calls a turn
exclusive does not prove it contains one real person. Never extrapolate an excerpt correction
to an entire cluster. Do not treat synthetic voice performances as recognition enrollment.

`calibrate` uses separately confirmed, disjoint held-out samples and unknown-speaker negatives.
It refuses repeated/overlapping samples and requires at least five holds per player and ten
negatives before proposing a policy. These are minimum evidence guards, not a statistical
guarantee. It records correct, wrong, unknown and negative false matches. A proposal needs a
separate untouched test set before activation; it never modifies the active policy itself.
Scores and cosine thresholds are not probabilities and are not interchangeable across models.
Insufficient evidence is a real result, not permission to lower thresholds or manufacture labels.

## Duration-based reporting

```sh
panther recording evaluate-speakers /PRIVATE/evidence.json --output /PRIVATE/report.json
```

Private evidence has `schemaVersion: 1`, `recordingSha256`, `modelPins`, `reference` and
`prediction`. Each interval has `start`, `end`, and nullable `playerId`. Truth must additionally
have `confirmed: true` and `identityEvidence`; a null identity is scored only when explicitly
confirmed as `context: "playback"`. References must not overlap. Score overlapping truth using
a separate multi-speaker DER evaluator, not this single-speaker named-identity metric.

Reports contain correct/wrong/unknown **duration** and per-player counts, with playback wrongly
named measured separately. Only annotated intervals are evaluated; do not extrapolate their
accuracy to the entire recording. Conflicting predicted identities count wrong rather than
being hidden by a majority vote. Automatic coverage reports must remain distinct from this
ground-truth evaluation. Keep real audio, names, embeddings and reports outside Git and CI.

This tooling does not activate a new enrollment or change an asset contract. A validated
transcript repair still requires a new immutable semantic version through authenticated Panther,
original text/timestamp equality checks, source lineage and reader verification. Cloud audio
processing, provider enrollment or paid trials require separate privacy and spending authority.
