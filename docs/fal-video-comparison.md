# Local fal video comparison

Panther's owner-funded comparison has a **$50 total ceiling**, not $50 per model, shot or session.
This opt-in local CLI does not run in the editorial worker or change AWS infrastructure. Planning
continues through subscription-backed Codex; fal inference is the separately authorized exception
for video generation. No paid request is made by installation, `check`, `budget`, `prepare` or `approve`.

## Credentials and account controls

Keep the regular key in the OS credential store under service `panther.place/fal`, account
`api-key`. Keep the separate admin key under account `admin-key`. Panther's generation client
never receives the admin key: only a dedicated GET to fal's account-billing endpoint uses it.
Both must belong to the **same fal account**. The provider does not expose the regular key's
account identity through the billing endpoint, so this setup fact needs owner confirmation.
The admin key remains powerful at fal; the read-only restriction is in Panther's implementation,
not a reduction of that key's provider-side scope. Neither key belongs in Git, `.env`, prompts,
AWS or the self-hosted test runner. CLI output omits keys, provider error bodies and signed URLs.

Turn **automatic credit top-up off** and use the dedicated prepaid comparison balance. The documented
billing API reports the balance, not the top-up setting, so the CLI requires an owner declaration.
It does not buy credits, change billing settings or request broader credentials automatically.

```sh
panther video check
panther video budget init
panther video budget status
```

State lives in `~/Library/Application Support/Panther/video-comparison/` outside Git: one private
SQLite ledger with full-sync transactions for all plans/attempts, plus original downloads.
Repeated `budget init` does not reset reservations. There is no reset, increase-limit, refund or
alternate-state-directory command. Keep this directory backed up privately. Do not delete it or
run a second independent copy on another laptop; that defeats a local-only budget. Migration must
transfer the ledger and stop the old writer before enabling the new one. Corrupt/missing state fails
closed rather than being silently reconstructed. An explicitly invoked `init` can create a missing
ledger, so agents must never use it to recover a previously established but lost ledger.

## Bounded initial profiles

### Production model selection

The owner's standing production policy (2026-09-10) is:

| Shot use | Model through fal | Text-only CLI profile | Image-anchored CLI profile |
| --- | --- | --- | --- |
| Default / other shots | Veo 3.1 Fast | `veo-3.1-fast` | `veo-3.1-fast-image` |
| Dialogue | MiniMax H3 Max (not Turbo) | `h3-max` | `h3-max-image` |
| City / urban establishing shots | Veo 3.1 Fast | `veo-3.1-fast` | `veo-3.1-fast-image` |
| Battle / action | Kling 3 Pro | `kling-3-pro` | `kling-3-pro-image` |

Select per shot, not per whole film. Action takes precedence over city setting; dialogue close-ups
between action beats use H3 Max, as does dialogue in a city. For an inseparable mixed shot, choose
Kling if action drives the shot, H3 Max if dialogue drives it, otherwise Veo, and record why.
H3 Max supersedes the earlier Veo dialogue preference. Agents must write the explicit profile into each new manifest;
the CLI still requires `model` and does not infer scene types or silently default a missing field.
These preferences do not authorize new paid requests, reference sharing, extra attempts, automatic
fallbacks or model upgrades. Owner-approved comparison experiments may intentionally use other
models. Historical comparison manifests and actual generation metadata remain unchanged.

### Supported comparison adapters

All profiles produce a single eight-second 16:9 clip with native generated audio, no reference
uploads, voice cloning, voice controls, automatic prompt rewriting or multi-shot expansion:

| CLI model | fal endpoint | Settings |
| --- | --- | --- |
| `veo-3.1-fast` | `fal-ai/veo3.1/fast` | 720p, 8s, audio on, auto-fix off |
| `kling-3-pro` | `fal-ai/kling-video/v3/pro/text-to-video` | Pro profile, 8s, audio on, one prompt |
| `seedance-2.0` | `bytedance/seedance-2.0/text-to-video` | Standard model, 720p, 8s, audio on, standard bitrate |

These are supported adapters, **not authorization to run any model**. Additional models need
reviewed input and billing adapters. Unknown units fail closed; token units are never treated as seconds.

Seedance's live pricing API on 2026-09-09 returns **$0.014 per 1,000 tokens**. Its
[settings and pricing](https://fal.ai/models/bytedance/seedance-2.0/text-to-video) define tokens as
width × height × duration × 24 / 1024: this fixed 1280×720, eight-second profile estimates 172,800
tokens, or $2.4192. The page also quotes a slightly higher $0.3034/second; Panther takes the higher
estimate ($2.4272), adds 25% headroom, then rounds up to a **$3.04 reservation**. This is not a
provider-enforced maximum. Audio has no separate multiplier. Duration/aspect ratio are never auto;
reference input, higher resolutions, Fast/Mini variants and arbitrary arguments are not supported.
Old Veo/Kling plans and all lifetime reservations remain intact; adding this adapter does not reset
the ledger or authorize another attempt. Seedance needs its own explicit model approval.

On 2026-09-09, fal's live base-price API returned $0.15/second for Veo and $0.14/second for Kling.
[Veo's settings-aware page](https://fal.ai/models/fal-ai/veo3.1/fast) lists $0.15/second with audio
at 720p/1080p. [Kling's page](https://fal.ai/models/fal-ai/kling-video/v3/pro/text-to-video) lists
$0.168/second with audio, while its base-price API is not settings-aware. Panther conservatively
uses the greater of the live base multiplied by 1.5 or $0.21/second for Kling, then adds 25% headroom.
For Veo it uses the greater of the live base or $0.15/second, also plus 25%. Current reservations
are therefore $1.50 and $2.10 per attempt, respectively; **these are not actual charge quotations**.
Money is rounded upward to integer cents, with nonfinite/negative/unknown values rejected.

## Prepare and explicitly approve

### Image-anchored comparisons

`h3-max` uses `minimax/h3-max/text-to-video` for the same bounded settings below, with explicit
16:9 and no reference image. This allows a like-for-like comparison with earlier text-only city
shots. It shares the same regular-price reservation and lifetime ledger, not a separate budget.

`h3-max-image` uses `minimax/h3-max/image-to-video` (H3 Max, not Turbo), one pinned starting
PNG, eight seconds, `768P`, integral native audio, `prompt_expansion_mode: disabled`, safety
checker enabled and synchronous/base64 output disabled. There are no end frames, voice references,
extra provider arguments or retries beyond the approved manifest. The source frame supplies the
canvas. The original prompt and any provider-returned expanded prompt remain in private attempt
history; do not treat provider rewriting as owner-authored content.

On 2026-09-10 the live pricing API reports the 480p base of $0.0125/second. The
[model page](https://fal.ai/models/minimax/h3-max/image-to-video) quotes 768p at $0.02/second
until September 14, then $0.08/second. The bounded quote takes the greater of live base × 1.6
or the regular $0.08/second rate, then adds 25% headroom: **$0.80 reserved per eight-second
attempt**, despite the current expected $0.16 bill. This avoids relying on an expiring promotion.
The [API schema](https://fal.ai/models/minimax/h3-max/image-to-video/api) is the payload reference.
H3 Max is the selected dialogue model under the production policy above. Adapter availability
does not authorize new spending or additional comparisons.

`seedance-2.0-image` uses `bytedance/seedance-2.0/image-to-video`, with exactly one
checksum-pinned starting PNG in `image_url`, explicit 16:9/720p/eight seconds, native audio and
standard bitrate. No end frame, voice reference, auto duration, higher resolution or arbitrary
arguments are accepted. It shares the image validation and existing lifetime ledger, without
changing earlier plans. On 2026-09-10 its documented token formula and $0.014/1,000-token rate
match the text adapter: a conservative $2.4272 estimate and $3.04 reservation per attempt.
Submission checks live pricing again; this is not a provider-enforced spending cap. Obtain the
same explicit model/reference-sharing approval as for the other image profiles.
See [Seedance image schema](https://fal.ai/models/bytedance/seedance-2.0/image-to-video/api)
and [settings/pricing](https://fal.ai/models/bytedance/seedance-2.0/image-to-video).

The additional bounded profiles `veo-3.1-fast-image` and `kling-3-pro-image` use
`fal-ai/veo3.1/fast/image-to-video` and `fal-ai/kling-video/v3/pro/image-to-video` respectively.
They retain eight seconds, native synthetic audio, the same lifetime ledger, serialized submissions,
and no automatic retries. Veo uses 720p; Kling's Pro endpoint controls its output resolution.
These profiles do not add voice cloning, reference videos, multiple shots, or arbitrary arguments.
They require explicit approval to send the specific reference images to fal in addition to model/spend approval.

Add `image: {"path": "/private/path/frame.png", "sha256": "64-lowercase-hex-digits", "key":
"games/synthetic-game/assets/frame/original/frame.png"}` to an image-profile shot. The source key
must also occur in the manifest's `sourceKeys`. Use a complete 16:9 starting frame, not a portrait
that the provider will crop: PNG, RGB/RGBA 8-bit non-interlaced, 1280×720 through 3840×2160, up to
8 MiB. Prepare verifies decoded PNG integrity and exact bytes against Panther's stored checksum.
Submit rechecks local bytes before reserving, then sends a base64 data URI with the paid request.
No extra public file hosting, expiring S3 link, or separate provider upload is needed. The ledger
pins file descriptors/checksums rather than duplicating image data. Never delete the private inputs.
Optional manifest `characterIds` tags explicitly depicted characters on the downloaded video metadata.
Set `sessionId: null` for standalone screen tests with no real session association; never invent a
session ID just to choose a storage folder. Such outputs use the ordinary shared-game media library.

On 2026-09-10 the live image-endpoint base rates matched the text endpoints ($0.15/s Veo, $0.14/s
Kling). The existing conservative audio/headroom calculation reserves $1.50 and $2.10 respectively;
these are safeguards, not binding charges. Preparation/submission always checks current pricing.
References: [Veo image API](https://fal.ai/models/fal-ai/veo3.1/fast/image-to-video/api),
[Kling image API](https://fal.ai/models/fal-ai/kling-video/v3/pro/image-to-video/api).

Synthetic example only; save actual game manifests outside Git. Source keys identify the existing
same-game preproduction/source artifacts; the CLI does not fetch or automatically send those files
to fal. Only the explicitly reviewed prompt and fixed settings go to the provider.

```json
{
  "schemaVersion": 1,
  "gameId": "synthetic-game",
  "sessionId": "synthetic-session",
  "sourceKeys": [],
  "shots": [
    {"id": "harbor-veo", "model": "veo-3.1-fast", "prompt": "A fictional harbor at dusk, wide shot, gentle camera movement. Ambient water sounds; no speech.", "maxAttempts": 2},
    {"id": "harbor-kling", "model": "kling-3-pro", "prompt": "A fictional harbor at dusk, wide shot, gentle camera movement. Ambient water sounds; no speech.", "maxAttempts": 2}
  ]
}
```

```sh
panther video prepare /private/path/comparison.json
panther video show-plan PLAN_ID
# Only after actual owner approval of this plan's models, rights and billing settings:
panther video approve PLAN_ID --models-and-rights-approved --auto-topup-disabled
panther video submit PLAN_ID --shot harbor-veo --attempt 1
panther video poll ATTEMPT_ID
panther video download ATTEMPT_ID
```

Preparation pins the manifest, exact provider payloads, adapter version, quotes and billing account,
verifies their content hash on use, and requires enough remaining budget
for **all allowed attempts**. Approval is not inferred from a preflight report or stored API key.
Submission checks current pricing and credit balance again. Price increases require a new reviewed
plan; a different billing account fails. A request must leave at least a **$5 provider-balance safety
floor** after its reservation. This may stop the comparison before using all $50, intentionally.

SQLite reserves the full amount **before** sending the generation POST. The local attempt key is
derived from plan/shot/attempt. Concurrent identical commands return the same reservation; repeated
commands after timeouts never submit another POST. Only one unresolved provider request may exist
at once. fal queue retries and endpoint fallbacks are disabled with documented request headers.
HTTP redirects and client-side request retries are also disabled. A 300-second queue-start timeout
does not imply cancellation after processing starts.

## Recovery and honest cost accounting

`panther video costs` now reads actual, request-matched billing events (including explicit zero
charges) with the separate read-only-use admin key. Downloads include known model/provider and
attempt the same billing lookup; unavailable costs remain unknown. This does not alter the ledger,
release reservations or recover blocked requests. See [generation metadata](generation-metadata.md).

- `panther video reconcile-unavailable ATTEMPT_ID` is a separate explicit recovery operation,
  not a generation retry. It only accepts acknowledged submissions, verifies the original billing
  account and pinned endpoint, a live `COMPLETED` status with the exact request ID, HTTP 404 from
  the verified result URL, and an exact request/endpoint-matched zero-charge billing event. Any
  missing, ambiguous, nonzero or conflicting evidence fails closed. It records `UNAVAILABLE`,
  not success/failure, keeping every existing content field, an audit record and the full lifetime
  reservation. A conflict guard rejects concurrent changes. Uncertain submissions (`UNKNOWN` /
  `SUBMITTING`) remain blocked. No lost video is invented, no budget is released and the unavailable
  attempt cannot be retried. Independently approved new shots can proceed after this verified
  terminal closure. Why the result disappeared remains unknown; do not infer retention or refunds.
- A verified queue `COMPLETED` result may return HTTP 422 with typed
  `content_policy_violation` or `no_media_generated` errors. Poll records these as `FAILED`,
  retaining the entire reservation and safe error type only. Unknown/malformed errors and
  failed submissions remain blocked, not assumed settled. This does not authorize a retry,
  altered-input workaround or a refund. See [fal model errors](https://fal.ai/docs/documentation/model-apis/errors).
- `SUBMITTING` after a process crash or `UNKNOWN` after a lost/invalid response retains the full
  reservation and blocks all new requests. Check fal request history/support; no automatic
  reconciliation or reservation release is implemented. Do not create a new plan to bypass this.
- `poll` follows only saved, validated same-model fal queue URLs using the original request ID.
  Read/poll/download failures do not initiate generation. It is safe to poll again after a read error.
- A completed or failed attempt **keeps its full reservation permanently** in this first version.
  Actual invoice charges/refunds are not inferred from success, cancellation, discounts or errors.
  `actualProviderSpendUsd: null` explicitly means not reconciled, not zero spent.
- A creative retry is another paid candidate: it requires an explicit reason, the previous attempt,
  an available per-shot attempt slot and another reservation under the same lifetime cap.
- Downloads use a separate unauthenticated client, approved fal delivery hosts, no redirects, an
  MP4 header check and a 128 MiB limit. They preserve the original MP4 and checksum with metadata;
  no transcoding or overwrite. If an interrupted local publish left the MP4 but not its metadata,
  inspect/recover that original; do not regenerate to recover bookkeeping.

The ledger limits **Panther's conservative reservations**, not fal's billing system. Live base prices
are not binding maximum quotes, pricing can change during a request, and dashboard/other-device
usage bypasses this ledger. No local tool can promise a provider-enforced account-wide hard cap.
The prepaid balance, disabled top-ups, $5 balance floor, 25% reservation headroom and serialized
requests are layered safeguards, not permission to conceal actual overspend. Stop if balance/cost
behavior differs from expectations; reconcile with fal before resuming. No AWS resources are needed.

## Sources and checks

- [Account billing API](https://fal.ai/docs/platform-apis/v1/account/billing): admin-scoped, balance expansion.
- [Pricing API](https://fal.ai/docs/platform-apis/v1/models/pricing): base prices and billing units.
- [Estimate API](https://fal.ai/docs/platform-apis/v1/models/pricing/estimate): historical/unit estimates,
  not settings-aware guarantees; not used as a substitute for reviewed model adapters.
- [Queue API](https://fal.ai/docs/documentation/model-apis/inference/queue): persistent request IDs,
  polling, timeout and no-retry semantics.
- [Platform headers](https://fal.ai/docs/documentation/model-apis/common-parameters): disabling fallback/retry.

Tests use synthetic data and fake provider responses only. Run `pytest -q tests/test_video.py` and
the local regression suite; CI is not needed for this CLI-only change. Real verification uses `video
check` only. No production key, prompt, game data or generated video is committed to Git.
