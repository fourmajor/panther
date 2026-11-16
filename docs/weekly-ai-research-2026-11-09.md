# Weekly follow-up: do not denoise away other speakers

Checked November 9, 2026. Resume draft PR #217; no second prototype or production rollout.

## Current release and availability checks

[MLX Audio 0.6.4](https://github.com/Blaizzy/mlx-audio/releases/tag/v0.6.4), published
November 2 at 17:24 UTC, adds NVIDIA NemotronLabs RE-USE enhancement and several long-form
and streaming ASR repairs. The tagged
[enhancement documentation](https://github.com/Blaizzy/mlx-audio/blob/v0.6.4/mlx_audio/sts/models/nemotron_reuse/README.md)
describes Apple Silicon execution, independent channels, 8–48 kHz input, offline processing,
five-second default chunks and float32 weights. Chunk size can change the output; full-file
inference uses more memory. [Tagged requirements](https://github.com/Blaizzy/mlx-audio/blob/v0.6.4/pyproject.toml)
remain Python >=3.10 and MLX 0.32.4. Runtime MIT and model rights are separate.

The official [NVIDIA model card](https://huggingface.co/nvidia/NVIDIA-NemotronLabs-RE-USE)
describes a 9.6M-parameter enhancer but explicitly warns that overlapping speech keeps the
main speaker while suppressing others. Its [license](https://huggingface.co/nvidia/NVIDIA-NemotronLabs-RE-USE/blob/main/LICENSE)
is OpenMDW 1.1, distinct from earlier RE-USE checkpoints. This is a strong reason **not** to
put it automatically before multi-speaker transcription/identification. Better-sounding
audio is not necessarily more faithful evidence. No installation, weights download or
audio inference was performed; Mac-specific latency and peak memory remain unmeasured.

[MLX's upstream validation](https://github.com/Blaizzy/mlx-audio/pull/1101) reports waveform
error against CUDA rather than exact waveform parity. That is a conversion check, not a
held-out transcription/identity-quality result. No advertised throughput is transferred
to this machine and no cloud savings are claimed.

[FluidAudio 0.18.3](https://github.com/FluidInference/FluidAudio/releases/tag/v0.18.3),
November 7, adds streaming encoder-output callbacks and repairs seam replacements, among
other changes. These are useful future evaluation hooks, not proof of improved Panther
accuracy. Its [package](https://github.com/FluidInference/FluidAudio/blob/v0.18.3/Package.swift)
still declares Swift 6/macOS 14; Apache-2.0 code does not relicense every model. No blanket
upgrade or TTS substitution is selected.

[pyannote pricing](https://www.pyannote.ai/pricing) still lists EUR19/month Developer with
credit, Precision-3 batch EUR0.112/audio-hour. Ten minutes of diarization is EUR0.0187 listed
usage, excluding other capabilities, taxes and activation minimum. Account entitlement is
unverified. A new subscription would exceed the disabled USD2 weekly testing allowance;
no provider request, subscription purchase or trial assumption was made.

## One proposal retained, no new performance claim

The duration-scoring sweep remains the only prototype. Its 145 focused synthetic evaluation,
profile and session-worker tests passed again; Ruff/diff checks passed. No runtime code or
new test cases changed this week. The October26 359x scorer-only benchmark is historical,
not remeasured or an additional weekly gain. No new model candidate has passed a Panther
quality benchmark. No frontend change/CI dispatch; the known offline runner is not repaired
or bypassed here. Advisory root review tooling is unavailable without package.json.

Leave PR #217 draft and unmerged. Rollback remains a code revert with no migration. Local
test hardware/energy cost is unmetered, not zero; paid inference and autonomous rollout
remain disabled.

## Next experiment, not execution

If enhancement is later tested, use a separate immutable derivative of public/licensed
speech, never overwrite source audio. Include single-speaker noise, competing voices,
overlap, quiet speakers and laughter. Measure ASR word error, named-speaker false assignment,
secondary-speaker retention and latency/memory against the unenhanced baseline. Reject an
enhancer that deletes quieter participants even if perceptual quality increases. Keep it
out of the source-evidence path until those checks genuinely pass.
