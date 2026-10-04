# Shot prompt preparation

A storyboard item is one independently rendered shot and one editable cut, not an
entire scene. New planning stages split complex action into items of at most eight
seconds, preserving consequential source events. The cut duration controls when
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
physical beat with a start and end. The selected game style is attached as canonical
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

Model selection remains the established city/dialogue/action policy. Input mode is
chosen from that model's documented capabilities; there is no provider/model fallback.

| Model | Shot conditioning |
| --- | --- |
| Veo 3.1 Fast | Without a starting frame, `reference-to-video` sends only visible portraits through `image_urls` (maximum three). With a frame, the existing I2V endpoint animates that frame; portrait comparison happens during preparation. More visible identities need a composed frame or separate shots; identities are never silently dropped. |
| MiniMax H3 Max | `reference-to-video` sends visible portraits through `reference_image_urls`, binds them as Image 1, Image 2, etc., and retains an optional exact starting frame. Prompt expansion stays disabled. |
| Kling 3 Pro | I2V sends the composed starting frame plus visible identity `elements`, bound as @Element1, etc. A character action shot without a starting frame fails instead of quietly reverting to text-only conditioning. |

Exact input schemas:
[Veo reference-to-video](https://fal.ai/models/fal-ai/veo3.1/fast/reference-to-video/api),
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
