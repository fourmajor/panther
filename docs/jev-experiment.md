# Jev experiment: offline preparation, not production inference

Issue #122 remains experimental and disabled. This implementation has no network client,
credential lookup, background job, production import or asset/transcript mutation. It does not
authorize API requests, even for synthetic inputs. No OpenRouter account, credit purchase or key
is needed for the offline work.

## Research checkpoint — 2026-09-29

OpenRouter explicitly documents typed decisions at `POST /api/alpha/decisions`, including Choice,
Noul and Score answers; its TypeSafe-compatible path is `/api/v1/systemone`. This is documentation
verification, **not** a live authenticated protocol test. Ordinary chat structured JSON is not a
substitute. Pin `typesafe/jev-1.13` and preserve the actual response model/provider. Public endpoint
metadata currently names `typesafe/jev-1.13-20260917`, text-to-decisions, a 32,000-token context and
$0.042 per million input tokens, zero output-token charge. These are advertised prices, not a bill.
Sources: [OpenRouter Jev guide](https://openrouter.ai/docs/guides/community/jev),
[Decisions API](https://openrouter.ai/docs/api/api-reference/alphadecisions/submit-a-decisions-request),
[public model endpoints](https://openrouter.ai/api/v1/models/typesafe/jev-1.13/endpoints),
[SDK routing](https://openrouter.ai/docs/guides/community/typesafe-sdk).

Choice returns a distribution over declared options. Score is a probability-weighted position on
the supplied scale. Noul is a yes-probability, not an intensity score. Confidence is a distribution
statistic, not automatically the probability that a selected answer is correct. Measure domain
calibration rather than adopting a vendor threshold. Schema correctness cannot establish truth.
Sources: [primitives](https://docs.typesafe.ai/primitives),
[confidence](https://docs.typesafe.ai/confidence), [Choice](https://docs.typesafe.ai/primitives/choice).

Keep arithmetic, date comparisons and exact identity/source checks in deterministic code; send
short relevant state, not a complete journal. Known weaknesses include counting and indirection.
Source: [published Jev limitations](https://docs.typesafe.ai/model-jaggedness/jev-1.13).

Privacy is **not cleared for game data**. Routing creates both OpenRouter and TypeSafe processing
boundaries; logging/retention controls need endpoint-specific verification. A vendor no-training
statement is not a proven zero-retention guarantee, nor proof of the owner's account settings.
Sources: [OpenRouter provider logging](https://openrouter.ai/docs/guides/privacy/provider-logging),
[TypeSafe legal overview](https://docs.typesafe.ai/legal).

## Offline smoke-test tooling

```
python -m panther_journal.jev_experiment prepare > PRIVATE_REQUESTS.json
python -m panther_journal.jev_experiment score PRIVATE_CAPTURES.json > PRIVATE_REPORT.json
```

Use owner-only paths outside Git. `prepare` accepts no private input; it builds twelve deliberately
fictional examples across utterance annotation, asset suggestions, typed entity linking and planned
continuity flags. Expected labels stay out of request state. Every case asks independent Choice,
Noul (ambiguity) and Score (evidence support) questions. No request is sent. Prepared requests
allow only the public `typesafe` provider slug and disable fallback. Credentials are never printed
or read. The routing restriction still needs a live protocol check; failure must not relax it.
Source: [provider routing](https://openrouter.ai/docs/guides/routing/provider-selection).

After a separately authorized live experiment, the capture format is a JSON array with one record
per prepared case: `caseId`, exact prepared `requestSha256`, measured `latencyMs` and the unmodified
`response` object. Response must contain the actual model, TypeSafe provider, usage and complete
typed answers. Preserve original requests/responses and billing evidence privately. The scorer
rejects aliases, mixed returned versions, missing/duplicate cases, altered requests, invented choice
options, invalid distributions, nonfinite/boolean numbers and a Score inconsistent with its scale.

Reports give per-task raw accuracy, coverage/abstention, selective accuracy, multiclass Brier score
and mean observed latency. An abstain-only benchmark control is labeled separately; it is not a
measurement of Panther's existing AI workflow. No accepted answers produces null selective
accuracy, not a fabricated zero or perfect score. Missing costs stay incomplete; reported response
cost is not independently reconciled billing. Tests use explicitly simulated responses, not Jev
results. They prove parser behavior only.

The initial *experimental* gate requires Choice confidence >=0.8, top-two margin >=0.2, ambiguity
Noul <=0.2 and a non-uncertain choice. It is not a calibrated production policy. Score is validated
and retained in captures, but is not silently converted into a hard action. A continuity flag
requires a later verifier; an entity decision remains restricted to the declared same-game set.

## Next gate, before any live request

1. Obtain explicit provider/model, external-sharing scope and hard total spend approval. Synthetic
   requests are the first live stage; real game examples require separate sharing approval.
2. Use a separately approved, limited key in the owner credential store. Establish provider/account
   caps where supported and a persistent local reservation ledger before network code is added.
   No auto-top-up, retries, fallback or reuse of the fal video allowance. Unknown submissions keep
   reservations and stop new sends. Do not put keys on the CI runner or in deployment templates.
3. Verify all three primitives with one tiny billed protocol request; pin its actual version and
   reconcile billing. Recheck retention/routing settings. Document failures instead of swapping to
   TypeSafe directly or ordinary chat calls.
4. Pre-register a held-out, separately reviewed set and baseline comparisons per use case. The twelve
   synthetic cases are only a smoke test, not evidence of production accuracy. Compare deterministic
   behavior and subscription-backed editorial decisions without tuning on the held-out set.
5. Measure errors, ambiguity handling, probability calibration, latency percentiles and reconciled
   cost. Preserve raw transcripts/player identity, typed references and all source evidence. Any
   adoption needs a disabled-by-default gate, rollout/rollback and a separate approval decision.

Current recommendation: **defer adoption**. Documented API support is promising, but no Jev quality,
live latency or per-request billing has been measured by Panther. No inference request was made.
