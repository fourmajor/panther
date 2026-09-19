# Soundtrack finishing

`panther soundtrack` adds explicitly authorized ElevenLabs Music, Sound Effects v2 and
short Eleven v3 stock-voice performances through fal. No clones, voice impersonation,
fallbacks, credit purchases, automatic retries or video generation. Narrator approval
remains unchanged; separately cast character performances require explicit owner casting
authorization, not a fabricated accepted audition. Prompted dialogue is an adaptation,
never transcript evidence. Only exact approved text/settings leave the laptop.

Reconcile an existing completed project with `soundtrack reconcile PROJECT --maximum 4
--reason 'Owner approval evidence' --owner-approved`. This is a one-way close of its old
video/narration submission paths, not an increase/reset/refund. Every old request must
have a terminal state, unique request ID and matching same-account billing evidence.
An additive audit retains original reservations, states and plans. The unchanged original
ceiling must cover reconciled historical charges plus the new maximum. Other projects and
the historical comparison allowance are untouched. Do not run older CLI versions against
a reconciled project; all writers must include the closure guard.

Use `soundtrack prepare MANIFEST`, `approve PLAN --owner-approved --auto-topup-disabled`,
`submit PLAN`, `poll ATTEMPT`, `download ATTEMPT`. The manifest contains schemaVersion 1,
projectId, gameId, kind (music/effects/speech), title, text, seconds and sourceKeys; speech
also has a listed stock voice. Music is instrumental and bounded to 240 seconds; effects
to 22 seconds; speech to 600 characters. No arbitrary endpoint or provider arguments.

Quotes verify current units/currency and add 25% headroom. Music additionally reserves
one rounded-up minute beyond requested duration. Attempts share the existing durable
transaction lock and global unresolved-request guard. Unknown requests keep their entire
reservation and block further submissions. Approval is not a quality assessment. Downloads
retain original bytes and separate model/provider/request/cost provenance outside Git.

Finishing must verify each required sound layer independently: non-silence and audibility
relative to narration, not merely a non-silent combined mix. Mark effects/ambience absent
when unsupplied. Leave natural speech gaps for character lines; do not stack narration and
dialogue, stretch speech, or claim offscreen dialogue is lip-synced. Preserve prior film,
original narrator, independent tracks and new edit/provenance as an immutable revision.

Sources: [Music API](https://fal.ai/models/fal-ai/elevenlabs/music/api),
[effects v2 API](https://fal.ai/models/fal-ai/elevenlabs/sound-effects/v2/api),
[Eleven v3 API](https://fal.ai/models/fal-ai/elevenlabs/tts/eleven-v3/api).
