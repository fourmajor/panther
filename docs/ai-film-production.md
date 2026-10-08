# AI film production: researched operating method

Reviewed 2026-10-06. This is Panther's synthesis, not a guarantee of successful generation.
Provider documentation describes supported controls; marketing quality claims are not independent
evidence. No method here authorizes a new model, paid retry, voice clone or service subscription.

## Evidence and decisions

| Primary source | Finding | Panther application |
| --- | --- | --- |
| [Runway image-to-video guide](https://help.runwayml.com/hc/en-us/articles/48324313115155-Image-to-Video-Prompting-Guide) | The image establishes appearance/composition; describe motion simply. Defective anatomy and conflicting implied motion can carry into animation. | Inspect real plates before spending; keep the continuity bible out of every provider request. |
| [MiniMax H3 official base guide](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/VIDEO_PROMPT_WRITING_GUIDE_base_en.md) | Frame-conditioned modes need temporal alignment and separate visual-action, soundscape and score sections. | H3 formatting uses its native field structure; do not generalize another provider's syntax. |
| [H3 full-reference guide](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md) and [fal reference adapter](https://fal.ai/models/minimax/h3-max/reference-to-video/api) | Reusable subjects and frame anchors have different roles; full-reference prompting has six sections. fal numbers portraits by their reference-list order and carries the opening composition separately. | Conditioning renders the reference-specific structure and avoids calling the first identity portrait the opening composition. |
| [fal H3 Max API](https://fal.ai/models/minimax/h3-max/image-to-video/api) | Image and ending-frame fields, duration, resolution and prompt expansion are explicit adapter inputs. | Verify actual endpoint support; pin submitted settings and image bytes, not imagined capabilities. Current CLI ending-frame support remains Kling-only pending separately tested adapter work. |
| [Google Veo 3.1 guide](https://cloud.google.com/blog/products/ai-machine-learning/ultimate-prompting-guide-for-veo-3-1/) | Cinematography/action/context, ingredients and endpoint frames provide different controls. | Choose the input mode deliberately; identity references are not interchangeable with opening compositions. |
| [Runway long-form guide](https://help.runwayml.com/hc/en-us/articles/26871350018835-How-to-create-longer-videos-and-films) | Build narrative from shorter clips, reference-led storyboards and editing. | Plan coverage, then curate takes; do not demand that one generation perform an entire scene. |
| [Runway reference-media guidelines](https://docs.dev.runwayml.com/recipes/reference-media/) | Clear isolated subjects and compatible reference quality matter. | Keep separate likeness/wardrobe references and environment/prop references; avoid feeding storyboard collages as first frames. |
| [Adobe filmmaker case studies](https://blog.adobe.com/en/publish/2026/01/30/sundance-dispatch-expanding-creative-expression-filmmaking-generative-ai) | Actual films combine character development, boards, timing voices, compositing, editing and conventional repairs. | Storyboard timing and sound planning precede generation; use real postproduction rather than describing broken takes as completed films. |
| [STAGE research](https://arxiv.org/abs/2512.12372) | Joint opening/ending-frame planning and cross-shot memory address narrative continuity, but temporal defects still occur. | Review start/end state pairs and previous closing frames. Do not claim Panther implements the paper's trained architecture. |
| [H3 physical-world evaluation](https://arxiv.org/abs/2609.18323) | Recent research explicitly evaluates physical reasoning instead of assuming visual fidelity proves it. | Treat strings, cork mechanisms, collisions and occlusion as high-risk shots; validate their causal progression directly. This preprint is not a guarantee about fal's post-trained H3 Max variant. |

## Executable workflow and gates

1. **Ground the story.** Preserve source facts and their uncertainty separately from adaptation decisions.
   State the scene's dramatic purpose and required outcome. Never invent factual victim identities to
   make a storyboard mechanically complete; label deliberate staging in review metadata, not the
   provider's motion prompt.
2. **Lock visual development.** Select immutable current appearance revisions, wardrobe and weapon
   ownership. Pin environment, lighting/palette and significant props. Character sheets help create
   plates; only reference fields actually supported by the selected endpoint condition video.
3. **Plan coverage.** Establish geography once; use action, reaction and object inserts to convey
   subsequent beats. All party members can feature across the sequence without occupying every
   close-up. Reduce simultaneous interactions rather than changing the approved story outcome.
4. **Track state.** For each shot, write the visible cast, prop/creature state before and after,
   dominant action, actor/target, screen direction, sound and next-shot handoff in its continuity
   notes. Corked/open, spirit counts and intact/broken glass must progress coherently. These notes
   are review context, not a global paragraph appended to every shot.
5. **Prepare real plates.** One clean starting composition per shot, correct identity/anatomy,
   supported aspect ratio, readable props and feasible starting pose. Object inserts contain only
   necessary objects. A creature-free opening must not carry later effects. Prepare compatible end
   plates only where the verified adapter supports them. Never reuse a defective generated closing
   frame just to gain continuity; review it first.
6. **Review a timed storyboard.** Inspect frame order, narrative causality, action coverage and sound
   intent at intended duration. The owner reviews the actual storyboard in Panther. An optional
   timed animatic is clearly previsualization, not a finished movie or replacement for native review.
   Prepare separately approved premium voice auditions where needed; no system-TTS shortcut.
7. **Compose exact shot requests.** Use the visible subset, one clear action trajectory and a feasible
   camera move. Starting images already establish appearance. Prefer positive outcomes (corks lift
   and stay clear) over extensive negations. Keep audit commentary, offscreen cast and unrelated
   effects out of provider prose. `motion_prompt` formats H3's sections without adding the whole
   party; other profiles keep their own syntax. Existing scene composition keeps approved action
   and camera text intact. Over-limit text fails; it is not clipped to a shorter, different action.
8. **Preflight before spending.** Check exact prompt against the plate, selected references,
   start/end states, duration and adapter settings. Local `production prepare` preserves failed
   candidates but emits an executable manifest only when preparation passes. Static tripwires catch
   obvious empty-insert/full-cast contradictions; independent visual/semantic review remains necessary.
   The legacy preparation export is an eight-second comparison manifest; for other lengths, use the
   existing version-2 generation manifest with an explicitly allocated project and exact durations.
   Do not silently pass a short timing plan as an eight-second generation request.
9. **Approve and pin.** Owner storyboard approval, exact models/input-sharing permission and project
   budget are separate from quality checks. Any materially changed depiction needs a new review
   revision. A readiness label cannot substitute for approved assets/settings.
10. **Generate incrementally.** Start with an explicitly approved representative high-risk shot,
    inspect its source take, then proceed serially. Stop remaining submissions when it exposes a
    systemic prompt/identity problem. Iteration is normal filmmaking practice, but paid retries
    require authorization and retained receipts; never reinterpret a budget cap as retry authority.
11. **Review source footage.** Compare starting composition, selected appearances and adjacent
    closing state at sampled times. Check faces, clothes, hands, props, action/physics, spirit counts,
    axis and completion of the intended beat. Examine suspect transitions at finer sampling;
    disclose coverage limits. Four-frame-per-second sheets do not prove every frame or lip sync.
12. **Select, don't conceal.** Bounded trims/grades cannot repair a transformed face or wrong cast.
    Keep failed takes, mark them failed and preserve a diagnostic local assembly if useful.
    Ordinary publication now blocks failed visual QC; `--allow-working-draft` is solely an explicit
    diagnostic publication choice, never final completion. Do not silently remove a necessary beat,
    replace motion with a still, or regenerate in the background.
13. **Build sound deliberately.** Plan dialogue, score, effects and ambience independently. Native
    sound is one inseparable mix. Music continuity generally belongs across shots, not fourteen
    independent generated scores. Use actual licensed/authorized stems; silent export placeholders
    are not completed sound design. Pin voice and approved words; review performance and lip sync
    separately from technical audio measurements.
14. **Finish and verify.** Edit pacing, cross-shot color and sound, captions and delivery formats.
    Review actual assembled pictures and measure decoded audio/headroom. Preserve clean master,
    browser derivative and exact lineage. Technical decode success is not creative approval.
15. **Publish a genuine result.** Only a passing movie is normal delivery. Preserve previous versions,
    costs, source takes and review evidence. Historical failed films remain historical evidence,
    not newly certified output or an invitation to repeat their paid generation.

## Limits and next capability decisions

No single prompt can ensure four distinct actors retain faces and weapons during complex spectral
combat. Reference/endpoint conditioning helps but is not deterministic. Multi-shot, motion-control,
reference-to-video and compositing can be useful, but require verified adapters, tests and explicit
model/spending permission. Future control work must compare like-for-like shots, not assume an
advertised capability is available through Panther's current fal endpoint.

The repaired preparation/review policy and fail-closed publication apply to every game. Existing
immutable plans, completed runs and provider receipts remain unchanged. Finishing workflow version 2
creates new checkpoints rather than retroactively relabeling version 1 review outcomes. This is a
production policy change, not a new asset schema requiring old media to be regenerated. Any later
structured state-contract change must include an all-game migration, preserving unknown states.
