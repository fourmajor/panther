# Shot prompt preparation

A storyboard item is one independently rendered shot and one editable cut, not an
entire scene. A full session cut is 14–16 shots of 2–7 seconds, targeting 60–80 seconds and
staying within 60–90, one H3 Max take each. A scene cut stays at most 16 shots and 90 seconds.
An item may describe a
clearly timed sequence such as `[shot 1, 0-4s]`, with achievable actions in each beat. The cut duration controls when
the action must finish; extra source-take time holds the ending rather than delaying
an event beyond the cut.

## Direction and continuity

Local scene requests pin the exact storyboard item, scene revision, character
profile revisions, official portrait bytes/checksums, game visual style and game
background. Prompt preparation policy 2 produces a structured, retained result:
visible character IDs, setting, lighting, mood, blocking, action, camera, sound,
source citations, uncertainties and renderability/frame-compatibility judgments.
Scene membership is a candidate cast, not an instruction to show everyone.
Only the visible subset is bound to video-provider identity images and finished
video character associations. Candidate references used in prompt analysis remain
in exact input lineage; they are not relabeled as on-screen appearances.

Use observable performance instead of abstract emotion, explicit actor/prop
ownership instead of ambiguous pronouns, one clear camera move, and one achievable
physical beat with a start and end, or an explicit chronological sequence. The selected game style is attached as canonical
prose independently of portrait style. The exact approved action and camera remain
constraints; a composer cannot silently replace them with a simpler invented event.
An incompatible starting frame or an over-complex item fails before video submission
with a specific correction message. These are AI preflight judgments, not guarantees
of fidelity or a substitute for reviewing the actual footage.

This follows [Google's Veo prompting guide](https://cloud.google.com/blog/products/ai-machine-learning/ultimate-prompting-guide-for-veo-3-1),
[MiniMax's reference guidance](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md),
and [Kling's model guide](https://kling.ai/quickstart/klingai-video-3-model-user-guide).
The [OpenAI image-input contract](https://developers.openai.com/api/docs/guides/images-vision)
is used for bounded visual analysis of the actual frame and candidate portraits.

## Reference modes of the production models

Session cuts follow `docs/ai-video-process.md`: Seedance 2.5 for on-screen dialogue, MiniMax H3 Max
for everything else. Scene-level generation uses MiniMax H3 Max image-to-video; Kling 3 Pro is an
explicit per-shot override. Veo was removed on 2026-11-12. Input mode is chosen from that model's documented capabilities; there is
no provider/model fallback.

| Model | Shot conditioning |
| --- | --- |
| MiniMax H3 Max | `reference-to-video` sends visible portraits through `reference_image_urls`, binds them as Image 1, Image 2, etc., and retains an optional exact starting frame. Prompt expansion stays disabled. |
| Kling 3 Pro | I2V sends the composed starting frame plus visible identity `elements`, bound as @Element1, etc. A character action shot without a starting frame fails instead of quietly reverting to text-only conditioning. |

Exact input schemas:
[H3 Max reference-to-video](https://fal.ai/models/minimax/h3-max/reference-to-video/api),
[Kling image-to-video](https://fal.ai/models/fal-ai/kling-video/v3/pro/image-to-video/api).
Reference portraits are individual images, never a contact sheet masquerading as a
starting frame. Conditioning copies apply EXIF orientation and preserve aspect ratio
within 1536 pixels per edge; originals and immutable pins remain unchanged. Image
inputs must be same-game PNG/JPEG/WebP, no larger than 8 MiB or 40 million pixels.

This adds no automatic image-generation pass, paid retry, voice reference or cloned
voice. Reference endpoint prices remain unknown until exact settings-specific pricing
is established; prices from another endpoint are never presented as theirs. Retained
queue identities continue polling the exact submitted endpoint after restart.

Policy changes apply to new requests across games. Existing approved boards, takes,
source bytes, submitted requests and unknown billed outcomes are not rewritten or
resubmitted. Old provider responses retain the policy actually used. This is a prompt
producer policy, not a storage/asset-contract migration. Cloud planning receives the
same shot discipline; executable visual conditioning described here is in the local
scene worker. Cloud render/assembly rollout remains a separate requirement.


## Timing and prompt fitting

A take may be up to 20% shorter than the planned item: fifteen seconds can serve an
eighteen-second item. Selection and assembly store the real available cut duration,
never pad or stretch footage to imply missing action. Longer takes are trimmed.

Prompt length alone does not fail local generation. Preparation budgets approved
action, camera, style, visible identities and direction separately; excess context
is shortened at word boundaries. Final provider prose is bounded to 2500 characters,
with identity bindings first. Original inputs, composition responses, fitting details
and the exact submitted request remain retained. Fitting performs no paid retry and
does not rewrite the approved storyboard. Shortening can omit detail, so footage
still needs review against the source.
