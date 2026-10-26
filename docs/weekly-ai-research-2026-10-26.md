# Weekly research follow-up: evaluation before another model switch

Checked October 26, 2026. Continue draft PR #217 rather than creating a second prototype.
The selected improvement is still the isolated duration-scoring event sweep, not an inference
model change. No production configuration, assets, workers, authentication or dependencies
are changed, and no paid requests are authorized by this proposal.

## Newly relevant release

[MLX Audio v0.6.2](https://github.com/Blaizzy/mlx-audio/releases/tag/v0.6.2) was published
October 26 at 15:40 UTC, after v0.6.1 on October 20. Its release API and tagged source were
checked directly: the search/browser cache was still showing v0.6.1 and the upstream PR as
open. The GitHub API reports [ECAPA extractor PR #1070](https://github.com/Blaizzy/mlx-audio/pull/1070)
merged October 25, with merge commit `894055e805c395c106ef1f4d8ba7f0daa3d63f2f`.

This is a useful Apple Silicon **identification** candidate, distinct from anonymous
diarization: the extractor produces normalized 192-dimensional SpeechBrain ECAPA embeddings
from mono 16 kHz audio, supports pinned weight revisions and strict loading, and does not
import model-repository Python. Its documented
[MLX weights](https://huggingface.co/aufklarer/SpeechBrain-ECAPA-VoxCeleb-20M-MLX)
are Apache-2.0, about 39.7 MiB, and pin the original
[SpeechBrain model](https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb).
The [runtime license](https://github.com/Blaizzy/mlx-audio/blob/v0.6.2/LICENSE) is MIT;
[tagged requirements](https://github.com/Blaizzy/mlx-audio/blob/v0.6.2/pyproject.toml)
include Python >=3.10, MLX 0.32.4 and transformers >=5.14.0. These are nontrivial dependency
changes, so any later trial needs an isolated environment, not an upgrade of Panther's worker.
No reliable peak-memory or throughput measurement on this particular Mac was established.

Upstream reports embedding cosine >0.99999 against a pinned SpeechBrain checkpoint and a
public example, plus a 36-crop parity comparison. That is **conversion parity**, not
meeting identification accuracy, calibration, end-to-end latency or a Panther result.
The original model's VoxCeleb EER does not transfer automatically to noisy tabletop sessions.
No threshold, enrolled identity, speech policy or production model is changed here.

## Other candidates rechecked

- [FluidAudio releases](https://github.com/FluidInference/FluidAudio/releases) still list
  v0.17.7 (October 8) as latest. Its recent additions concern compact TTS; they do not
  justify replacing Panther's approved high-quality speech. The
  [Nemotron CoreML benchmark](https://huggingface.co/FluidInference/nemotron-3-diarization-coreml/blob/main/BENCHMARKS.md)
  still measures one M5 Pro, not this Mac: fast128 has 9.36 DER and 546x wall RTFx on
  all 16 AMI MHM test meetings, zero collar, overlap included. Runtime Apache-2.0,
  weights OpenMDW 1.1, [package](https://github.com/FluidInference/FluidAudio/blob/main/Package.swift)
  Swift 6/macOS 14 minimum. Do not confuse package minimums with every backend's support.
- [pyannote pricing](https://www.pyannote.ai/pricing) still lists Developer EUR19/month
  including usage credit, and Precision-3 batch EUR0.112/audio-hour. Ten minutes is
  EUR0.0187 marginal listed diarization usage, **not** the total cost to activate a paid
  account, and excludes other services/taxes. Trial/credit entitlement was not checked.
  No cloud audio upload or API test was made. The recurring USD2 allowance remains disabled.
- Video-price aggregators surfaced conflicting numbers; an attempted official fal model
  page was unavailable. No new video-price/quality claim or routing change is supported
  by this research. Existing approved production policy stays intact.

## Decision and next bounded test

Keep one proposal: the existing faster evaluator makes repeated named-speaker comparisons
cheap to score without altering recognition. Re-run its synthetic oracle parity tests and
benchmark before adding this research to the same draft. This does not test the new MLX model.

October 26 recheck: **139 focused tests passed**, including 100 seeded differential cases;
Ruff and diff checks passed. With 3,000 synthetic truth intervals, 9,000 predictions and
three repetitions, scan-oracle median was **7.411866 s**, sweep median **0.020645 s**:
**359.0x scorer-only speedup**, exact metric parity. The original-scan oracle still omits
some validation/report overhead. Machine load/timing varies; this is not an additional
improvement over last week's 330.3x measurement, an inference-speed claim or a timing gate.
Reproduce with `tools/benchmark_speaker_evaluation.py --intervals 3000 --repeats 3`.
No browser-affecting code changed; no CI dispatched. Advisory `yarn review:smart --offline`
is unavailable because this repository has no root package.json. Draft remains unmerged.

A future separate, explicitly reviewed MLX experiment should pin runtime and weight revisions,
use public/licensed held-out speech, compare the same SpeechBrain weights/frontend with
the MLX conversion, and measure cold/warm wall time, peak memory and embedding agreement.
Then evaluate named-speaker wrong/unknown rates and playback false assignment separately;
do not weaken thresholds to inflate coverage. Until that passes, there is no measured model
speed/quality improvement to deploy. No installation, model download or inference occurred
in this weekly follow-up. Local synthetic scoring uses existing tools; hardware/energy costs
were not metered, not declared zero.
