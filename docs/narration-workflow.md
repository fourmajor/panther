# Premium narration workflow (v1)

Default: **ElevenLabs Eleven v3 through fal**, with a deliberately cast stock voice and
performance-directed text. No Chatterbox, system TTS, lower-quality fallback, or automatic
provider substitution—even for previews. This policy is not a claim that every generated
take will be good: performance, pronunciation, natural pacing and narrative intent need review.
Keep original historical takes/provenance; do not regenerate or relabel old media automatically.

## Stages and approval boundary

1. Write a voice brief and pronunciation guide from authorized game context. For a trailer:
   restrained ominous opening, resonant delivery, short dramatic phrases and escalating intensity.
   Do not impersonate a named actor. Use subscription-backed editorial planning, not a paid LLM.
2. Prepare a short audition (at most 600 characters) with the selected stock voice and performance
   tags. `direction` records intent; only `text` with tags and the bounded voice settings go to fal.
   Plain direction prose is not secretly a supported synthesis instruction. No source files,
   portraits, journal or real-player recordings are sent by this adapter.
3. Allocate an explicitly approved project total and protect the allowance for video/other media.
   Live price/balance check → immutable plan → explicit approval → reserve → one queue submission.
4. Poll and download the original MP3, generation metadata and full provenance. Screen for omitted
   words, repetitions, clipped peaks and pronunciation, then judge delivery. ASR matching is not
   perceptual quality approval. Supply the audition separately from a readable storyboard.
5. Record the requested owner's voice approval with `accept-voice`. Production must reference that
   accepted same-game/project/voice audition and needs a separately approved full-text plan.
6. Generate complete thought units (up to 5,000 characters per approved request). Never stretch
   every sentence to fill arbitrary shot durations. Preserve original takes; edit pictures to the
   performance, keep clean narration separate from music/effects and inspect the finished mix.
7. Publish using Panther with exact sourceKeys, model/provider/voice, remote inference location,
   request-matched cost when available and explicit review status. Unknown cost is not zero.

No editorial completion event starts paid narration. This is a resumable local CLI workflow, not
an always-on service or a new AWS Step Function. Existing video-generated dialogue model choices
remain unchanged; this policy controls separately synthesized voices/narration. Real-player voice
cloning is a separate consent/provider workflow and is not supported by this stock-voice adapter.

## Commands

Save actual game files outside Git. Example identifiers below are fictional.

```sh
panther narration allocate --project lighthouse-recap --game saltwater \
  --cap 15 --hold-for-other-media 13.48 --reason 'Owner-approved total and protected film allowance' \
  --owner-approved
panther narration prepare /private/path/audition.json
panther narration approve PLAN_ID --text-voice-rights-approved --auto-topup-disabled
panther narration submit PLAN_ID
panther narration poll ATTEMPT_ID
panther narration download ATTEMPT_ID
# Only after actual owner acceptance of this audition:
panther narration accept-voice ATTEMPT_ID --owner-approved
panther narration budget lighthouse-recap
```

Manifest:

```json
{
  "schemaVersion": 1,
  "gameId": "saltwater",
  "projectId": "lighthouse-recap",
  "purpose": "audition",
  "text": "[dramatic] The sea remembers every promise. [long pause] Tonight, it comes to collect.",
  "voice": "Bill",
  "direction": "Resonant cinematic trailer delivery; restraint, pauses, then rising urgency.",
  "sourceKeys": ["games/saltwater/assets/recap-script/original/script.json"]
}
```

Production uses `purpose: production` and `approvedAudition: ATTEMPT_ID`. Only explicitly listed
stock voices are accepted; arbitrary voice IDs/reference audio/provider arguments are rejected.
The v3-specific payload uses `text`, `voice`, `stability: 0.5`, `timestamps: true`, English and
automatic text normalization. Do not send parameters from unrelated generic TTS schemas.

## Budget and recovery

Uses additive narration tables in the existing private `video-comparison/budget.sqlite3`, one
full-sync SQLite transaction lock shared with video submissions. The historical comparison
$50/$51 allowance, extensions, plans and attempts are unchanged. Each separately authorized
production project has a create-only ceiling and fixed protected other-media hold. This is a
new project allocation, not a reset or refill of the old comparison budget. Duplicate allocation
commands preserve history; conflicting facts fail. There is no increase/release/reset command.

For a $15 movie with $13.48 protected for footage, narration can reserve at most $1.52 total,
including every audition and full take. **The hold does not reserve provider funds or authorize
video generation.** Existing `panther video` still uses its old comparison allowance, not these
production funds. Before enabling the later film executor, its enforced video ceiling must be
bounded by the protected hold and combined with narration costs under the original total. Never
silently give video a fresh $15 after spending on narration. Other projects need their own
explicitly approved allocations; do not create project aliases to evade an exhausted budget.

fal's live price must be USD per 1,000 characters. Use the greater of its price and $0.10,
conservatively count UTF-8 bytes, add 25% headroom, round upward to cents and reserve before POST.
Submission refreshes price/account/balance and protects the other-media hold plus a $5 balance
floor. This is a local conservative guard, not a binding provider quote or an account-wide cap.
Keys remain in the OS credential store. Only the read-only billing client receives the admin key.
Never buy credits, enable top-ups, run another writer from a copied ledger, or log secrets.

One request per approved plan; repeated submission returns the same attempt. Timeouts/crashes and
unrecognized results retain reservations and block both narration and video submissions. No paid
retry or fallback is automatic. Failed and completed requests keep reservations. Billing is read
only and cannot release them. A new take requires a new explicitly approved plan within the same
project. Poll/download failures never cause resubmission. Existing downloaded originals are never
overwritten; interrupted metadata publication requires recovery of those bytes, not generation.

Queue narration requests use `X-Fal-Store-IO: 1`: fal's standard 30-day JSON input/output
retention makes delayed result retrieval possible. Only the approved text and stock-voice settings
are sent; no journal files or player recordings. Do not disable response retention for this
asynchronous workflow. Media-file retention is a separate provider setting.

If a known completed request repeatedly returns HTTP 404, owner-authorized
`panther narration reconcile-unavailable ATTEMPT --owner-approved --reason 'authorization'`
verifies account, request completion, missing result and exact billing before recording a terminal
lost-output state. It preserves every reservation, billed amount and original request. Unknown
submissions, absent billing and still-running requests remain blocked. This command neither refunds
nor retries: prepare/approve a new take only when the owner explicitly authorizes its expense.

## References

- [fal v3-specific schema](https://fal.ai/models/fal-ai/elevenlabs/tts/eleven-v3/api)
- [fal price](https://fal.ai/models/fal-ai/elevenlabs/tts/eleven-v3): live API verified
  2026-09-14 at $0.10 per 1,000 characters; preparation/submission check again.
- [ElevenLabs voice design and performance](https://elevenlabs.io/docs/eleven-creative/voices/voice-design)

Verify locally with `pytest tests/test_narration.py tests/test_video.py`. Tests use synthetic
manifests and fake billing/generation only. No hosted CI or AWS deployment is needed for this CLI.
