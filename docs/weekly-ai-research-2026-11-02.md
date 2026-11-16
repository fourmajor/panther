# Weekly follow-up: conversion correctness before changing speaker models

Checked November 2, 2026. Continue the single evaluation-sweep proposal in draft PR #217;
do not create another prototype while it remains unreviewed. No production rollout, model
installation, worker change, paid inference, asset publication or dependency upgrade occurred.
The requested recurring USD2 testing allowance remains disabled by this schedule.

## Primary-source developments

[FluidAudio 0.18.2](https://github.com/FluidInference/FluidAudio/releases/tag/v0.18.2),
published November 1, changes overlapping-speech output defaults, fixes short-file/tail
prediction, and loads corrected CAM++ v2 embeddings. Its release reports overlap-scored AMI
DER 24.2% to 20.3%. These are upstream measurements, not Panther improvements, and changing
exclusive output affects the evaluation contract. A blanket dependency upgrade is inappropriate.

The detailed [CAM++ repair](https://github.com/FluidInference/FluidAudio/pull/1099) identifies
frontend window/floor differences, pooling-tail division and length-dependent fp16 errors.
It reports 10-second extraction increasing from 7.7 to 12.7 ms and model size 14 to 27 MB on
an M5 Pro. Correctness can cost speed; do not select by a single headline. The updated
[model card](https://huggingface.co/FluidInference/campplus-coreml) distinguishes within-meeting
EER (3.07% to 2.85% versus v1 plus host normalization) from across-meeting EER (3.48% to 3.55%).
It uses 413 AMI segments and reports PyTorch parity across 357 lengths. Neither establishes
named-player accuracy, good enrollment or calibrated thresholds in another acoustic setting.

Hardware/license checks: the model card specifies fp32 CPU preprocessing and CPU/GPU
embedding execution on Apple Silicon, despite its ANE-oriented title. The tagged
[package](https://github.com/FluidInference/FluidAudio/blob/v0.18.2/Package.swift) declares
Swift 6/macOS 14; [runtime code](https://github.com/FluidInference/FluidAudio/blob/v0.18.2/LICENSE)
is Apache-2.0. Weights are separately labeled `campplus-upstream`, not automatically covered
by that code license. Exact upstream weight rights remain unresolved here; do not ship them
on that assumption. No model download, peak-RAM or runtime measurement on this Mac was done.

[MLX Audio 0.6.3](https://github.com/Blaizzy/mlx-audio/releases/tag/v0.6.3), October 28,
adds Nemotron 3.5 Transcribe support and bulk PCM conversion. The
[PCM optimization report](https://github.com/Blaizzy/mlx-audio/pull/1083) measured about 28%
less round-trip time on a specific synthetic Linux workload, not Mac inference or Panther
recording. The principle is worth evaluating, not copying as a guaranteed gain. Speech
recognition is not speaker identification. This does not replace the pinned identification
candidate or premium narration policy described in last week's research.

[pyannote pricing](https://www.pyannote.ai/pricing) still lists Precision-3 batch at
EUR0.112/audio-hour and Developer EUR19/month including credit. A ten-minute trial would
be EUR0.0187 listed marginal diarization usage, excluding plan activation, identification,
taxes and other features. A conservative later experiment must first verify existing
entitlement and all included services: without it, the EUR19 plan minimum exceeds this
schedule's disabled USD2 allowance. No account/trial checks or cloud requests were made.

## Same bounded prototype, stronger checks

The existing sweep is still the only selected code improvement. Added six synthetic oracle
parity regressions for fractional tail intervals in files from 0.1 seconds to three hours,
including mixed unknown/known overlap. This guards scoring of short/tail and overlap evidence;
it does not test a diarizer's ability to find that evidence. All **145 focused evaluation,
speaker-profile and session-worker tests passed**. Ruff and diff checks passed. No frontend
behavior changed, so no browser CI was needed or dispatched.

The prior October 26 measurement remains the measured baseline: 3,000 synthetic truth
intervals/9,000 predictions, three repetitions, scan median 7.411866 s versus sweep 0.020645 s,
359.0x scorer-only, exact metrics. It was **not remeasured this week**; no additional speed,
quality or cost gain is claimed. Local test hardware/energy cost is unmetered, not zero.
Advisory `review:smart` remains unavailable without a root package.json. Leave the draft
unmerged; rollback is a code revert with no migration or production state changes.

## Next experiment specification, not execution

Before any later model comparison, pin source/conversion revisions and frontend contract;
test several excerpt lengths including tails and exact boundary cases; retain true overlap;
report within/across-session verification separately from diarization DER; and measure
named-speaker wrong/unknown/playback rates on held-out licensed fixtures. Compare the same
audio, scoring collar and overlap policy. Reject weak identities rather than lowering gates
to inflate coverage. The new conversion bug reports strengthen this requirement, but are
not evidence that Panther currently uses the affected CAM++ runtime.
