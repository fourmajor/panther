# Weekly experimental proposal: faster speaker-model evaluation

Research date: 2026-10-19. Draft only; no production defaults, models, assets,
workers, permissions or deployments changed. No paid inference submitted.
The requested $2/week testing allowance is not enabled by this schedule.

## Recent developments checked

- [NVIDIA Nemotron 3 Diarization](https://huggingface.co/nvidia/Nemotron-3-Diarization)
  was released September 23, 2026. Its available open weights support eight anonymous
  speakers and streaming/offline inference under OpenMDW 1.1. Anonymous labels are
  not enrolled player identities. NVIDIA's supported primary runtime is GPU-oriented;
  [NeMo-Speech.cpp](https://github.com/NVIDIA/NeMo-Speech.cpp) is its Apache-2.0 native
  alternative. Panther already has an explicitly pinned experimental native adapter:
  adding the same integration again would not be a new improvement.
- [FluidAudio](https://github.com/FluidInference/FluidAudio) provides an Apache-2.0
  Swift/CoreML runtime with Nemotron support. The separately licensed
  [converted model](https://huggingface.co/FluidInference/nemotron-3-diarization-coreml)
  retains OpenMDW 1.1. Its current
  [benchmark report](https://huggingface.co/FluidInference/nemotron-3-diarization-coreml/blob/main/BENCHMARKS.md)
  reports fast128 at 9.36 DER and 546x wall real-time factor on one M5 Pro, AMI test
  MHM, all 16 meetings, collar zero, overlap included. These are maintainer results,
  not Panther measurements or evidence of equivalent M2 performance. Earlier preview
  checkpoint tables were withdrawn: do not combine them with current results.
  [Package.swift](https://raw.githubusercontent.com/FluidInference/FluidAudio/main/Package.swift)
  declares Swift 6.0/macOS 14 minimum, but that does not validate every model/backend
  on every supported machine. Local inference has no provider usage fee, not zero
  electricity/hardware cost. CoreML comparison is a future candidate, not activated.
- [MLX Audio v0.5.9](https://github.com/Blaizzy/mlx-audio/releases/tag/v0.5.9), October 13,
  adds Nemotron streaming speech recognition and predictor reuse, plus transcription
  token-limit fixes. Speech recognition is not diarization or player identification.
  Its TTS additions are not substitutes for Panther's premium speech policy. No
  dependency upgrade or change to source recognition is proposed here.
- [pyannote Precision-3](https://www.pyannote.ai/changelog/precision-3) is available
  through its API/on-premises and reports 10.4% relative DER improvement over its
  predecessor across its 15-dataset benchmark; this is a vendor claim, not a Panther
  result. [Current pricing](https://www.pyannote.ai/pricing) lists Developer at
  EUR19/month with usage credit and batch Precision-3 at EUR0.112/audio-hour.
  Account/trial entitlement is not verified. A 10-minute comparison would have
  EUR0.0187 listed diarization usage before any plan minimum, taxes, identification
  or other charges. Do not equate that with an authorized USD2 experiment. No cloud
  trial, account setup, audio upload or paid request was performed.

## One selected improvement

Make Panther's existing duration-based named-speaker evaluator fast enough to compare
these alternatives repeatedly. Keep all validation, unknown-speaker handling, mixed
prediction penalties, playback checks and output schema unchanged. This is evaluation
infrastructure only, not a new diarizer, identity policy or accuracy improvement.

The previous implementation rescanned every prediction for each truth interval and
each resulting boundary. The draft indexes start/end events once and sweeps them across
ordered non-overlapping truth. A reference-counted active set preserves duplicated and
overlapping predictions; half-open boundary behavior and gaps remain unchanged. Work is
event sorting plus traversal and active-label set copies, rather than repeated full scans.

## Reproduction and measured result

From the draft checkout using the existing project environment:

```sh
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_speaker_evaluation.py tests/test_speaker_evaluation_sweep.py
.venv/bin/python tools/benchmark_speaker_evaluation.py --intervals 3000 --repeats 3
```

The benchmark uses only synthetic intervals, no recordings, models or real identities.
On the local host, three repetitions with 3,000 truth intervals and 9,000 predictions:

| Scorer | Median seconds |
| --- | ---: |
| Original scan-algorithm oracle | 7.594668 |
| Draft event sweep | 0.022990 |

Measured scorer-only speedup: **330.3x**. The deliberately simple oracle omits some
original validation/report assembly, making this a conservative algorithm comparison;
it is not an end-to-end Panther workflow benchmark. All scored durations and per-player
results matched exactly. Existing tests plus 100 seeded differential cases and explicit
duplicate/boundary/empty cases passed: 114 tests at the initial measurement. Timing is
not asserted in CI; parity is. No speaker-model quality gain, game-session speedup or
cloud cost saving has been measured.

## Limitations, review and rollback

Leave the draft PR unmerged. No browser behavior changes, so no Playwright run is needed
for this isolated backend evaluator. Revert the sweep implementation to roll back; raw
inputs, model output, active policies and asset schemas are unaffected. No migrations.
Before testing a new diarizer, pin its runtime/model, confirm fixture licensing, compare
the same held-out audio with identical collar/overlap rules, and report named-identity
accuracy separately from diarization DER. Do not use silence-only synthetic audio to
claim speech quality or transfer another machine's throughput numbers to this laptop.
