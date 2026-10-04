"""Versioned editorial stages and deterministic correction guards. No generated code execution."""

import copy
import json
import re
from importlib.resources import files

PLAN = json.loads(files("panther_journal").joinpath("editorial-plan.json").read_text())
STAGES = [s for branch in ("correction", "novel", "video") for s in PLAN[branch]]

BRIEFS = {
    "video-source-brief": "Preprocess optional transcript sources against the user's creative brief and pinned cast. Select only story-relevant events, dialogue, character actions, setting and explicit continuity facts; exclude table chatter, irrelevant rules discussions and audit/provenance documents. Return sourceFacts with exact sourceKey and source-local segmentIndex for each extracted fact plus explicit uncertainty; quote dialogue only when that source actually contains it. Keep factual evidence, creative direction and proposed inventions distinct. With no transcripts, sourceFacts MUST be empty: work from the creative brief and explicit character/background references, without fabricating a transcript, recording session or supposed dialogue evidence. Describe the coherent proposed scene, cast and factual gaps in markdown. Do not generate media or authorize spending.",
    "video-voice-casting": "Create separate player and character voice casting plans tied to stable entity IDs, plus an independent narrator. A real player's cloned voice requires that person's explicit scoped permission and suitable licensed/consented samples; recording consent is not cloning consent. Character voices may be independently designed and must not silently impersonate a player, celebrity or another real person. Describe timbre, range, accent intent, rhythm, emotion/performance direction and pronunciation lexicon. Specify clean enrollment sample requirements, ownership, revocation, usage scope, versioning and an original non-impersonating fallback where permission is absent. Plan dialogue alignment/lip-sync and consistency testing without training, cloning, generating audio or selecting a paid provider. All profiles remain proposals with no model reference or generation authorization.",
    "novel-options": "Develop three genuinely distinct narrative approaches within the brief (POV, opening, emphasis, structure), compare tradeoffs, and choose one against explicit craft criteria. Create an original voice/style bible and a fact-versus-invention ledger. Do not average options into generic prose or imitate a named living writer. This is creative exploration, not factual correction.",
    "novel-continuity": "Audit the revised chapter against the corrected transcript and pinned game evidence: names, character knowledge, geography, chronology, possessions, injuries, goals and consequential events. Check distinct character voices, POV drift, cliches, repetitive AI phrasing and overexplained themes. Produce a concrete continuity/style ledger and targeted copyedit instructions; don't erase deliberate creative choices merely for uniformity.",
    "video-reference-plan": "Create an AI reference-asset registry: character plates (front/profile/back, expressions, wardrobe/appearance state), environment plates and hero props, tied to stable character/location IDs. Separate existing verified Panther keys from missing assets. Define reusable reference bundles and per-scene appearance changes. Specify how keyframes must be visually checked before motion generation; no invented asset keys or external calls.",
    "video-generation-packets": "Produce provider-neutral per-shot generation packets tied to locked shot IDs: reference bundle/appearance IDs, initial/end-frame requirements, visual composition, subject action, environmental motion, camera motion and timing, continuity dependencies, proposed duration, acceptance/rejection tests, and bounded candidate/retry counts. Prefer one clear action/camera idea per shot, positive observable instructions, separate image-to-video motion prompts from text-to-video scene descriptions, and flag conflicting instructions. Record provider/model/seed/support as undecided, never assume seeds or camera controls guarantee continuity. Plan candidate comparison and selected-take provenance. Do not generate any image/audio/video or choose a provider.",
    "context": "Select relevant game evidence: character names, aliases, locations, chronology, prior transcripts, ruleset and metadata. Explain relevance and uncertainty. Never select adaptations, held-out scripts or future-session spoilers as factual authority.",
    "correction": "Propose minimal speech-recognition corrections. Preserve all table talk, hesitations, negation, uncertainty, numbers, player identities and timestamps. Game context can disambiguate names; it cannot override what was said or reconstruct missing audio. Cite evidence IDs for every edit. Uncertain edits must remain unresolved. Do not polish dialogue or remove pizza chatter.",
    "corrected-transcript": "Independently audit the supplied candidate against every raw utterance and pinned context, including consistency of repeated names. Fail if unsupported, if it changes meaning/identity/numbers, deletes table talk, fills missing sound, or treats game expectations as proof of speech. Retained ambiguous raw wording with a note is acceptable. Passing means plausible AI corrections, not human verification. Return an actionable review. Rejection triggers automatic correction and fresh review; persistent disagreement falls back to raw wording with notes.",
    "novel-brief": "Act as commissioning editor. Define audience, tone, original voice (no living-author imitation), POV, tense, chapter purpose, character goals/conflicts, emotional turn, continuity boundaries, and adaptation license. Separate table chatter/rules from story action without altering transcripts. For a test game, explicitly label this fictional test material, not campaign canon.",
    "novel-outline": "Develop a chapter synopsis and scene/beat outline: POV, goal, obstacle, escalation, reversal, consequence, transitions, opening promise and closing hook. Trace story events to transcript segments. Do not force a formula onto sparse material. List invented connective details separately.",
    "novel-draft": "Write the complete chapter from the approved brief/outline. Use scene, action, sensory detail, subtext, paced exposition and differentiated dialogue. Dramatize rather than summarize every utterance. Keep consequential outcomes faithful; disclose invented connective tissue in notes outside the chapter.",
    "novel-developmental-edit": "Independently edit the full draft for structure, causality, stakes, POV, characterization, pacing, theme and continuity. Supply prioritized concrete revision instructions. Distinguish intentional adaptation from unsupported changes to consequential game events.",
    "novel-revision": "Produce the complete revised chapter, addressing developmental notes. Preserve intended voice and source outcomes. Add a change log outside the reader-facing prose and list unresolved editorial questions.",
    "novel-line-copyedit": "Produce the complete line- and copyedited chapter. Improve sentence rhythm, clarity, dialogue, grammar and consistency without flattening voice. Supply a style sheet for names, capitalization, POV, tense, chronology and terminology.",
    "novel-proof": "Check the copyedited Markdown reading proof, including headings, paragraph breaks and dialogue punctuation. If revisionFeedback exists, revise the actual candidate chapter to address it. Return the COMPLETE final chapter alone in markdown, with proof notes and invention disclosures separately in decisions/uncertainties. This is a digital manuscript proof, not a claim of typeset print proofing.",
    "novel-chapter": "Independently quality-check the supplied candidate chapter (the latest revision, taking precedence over older priorStages) against sources, brief and edits. Require compelling scene-level storytelling, coherent POV, resolved developmental issues, faithful consequential outcomes, and disclosed inventions. The title field becomes the published chapter title: use the story's concise literary title, never an audit, assessment, delivery or review label. Return pass/fail with actionable reasons; do not rewrite the chapter in this review. Rejection triggers an automatic actual manuscript revision and fresh audit, not a human approval request.",
    "video-treatment": "Develop a screen adaptation brief, logline, synopsis/treatment, character arcs, audience/tone, provisional runtime and scene beats. Identify compression, invented dialogue and other dramatization explicitly. This is a creative reimagining, not a transcript or campaign canon.",
    "video-screenplay": "Write the complete screenplay using scene headings, present-tense action and character/dialogue formatting. Show rather than narrate. Preserve source outcomes and track invented material. Use stable scene IDs.",
    "video-script-edit": "Independently review screenplay structure, visual storytelling, character motivation, dialogue, pacing, source fidelity and feasibility. Supply concrete revision notes and continuity issues.",
    "video-shooting-script": "Produce the complete revised screenplay with stable numbered scene IDs and a scene-by-scene change log, addressing script-edit notes. Lock this revision for downstream planning.",
    "video-breakdown": "Break down every locked scene into cast/character appearances, locations, day/night, props, costumes, makeup, sets, practical/action effects, VFX, sound, music and special requirements. Identify available Panther references versus assets still needed; do not pretend assets exist.",
    "video-design": "Create the production design and cinematography bible: world/sets, costumes/props, character continuity, reference asset IDs, palette hex colors and emotional progression, contrast, light direction/motivation, aspect ratio, lens/shot language, texture and negative constraints. These are proposed creative choices, not provider capabilities.",
    "video-blocking": "Plan character blocking, spatial geography, eyelines, entrances/exits, screen direction and continuity/180-degree line for every scene. Give camera coverage strategy and transitions tied to dramatic intention.",
    "video-shot-list": "Create ordered shots covering all scenes with stable shot IDs, scene ID, durationSeconds, shot size, angle, lens intent, camera movement, action, dialogue cues, lighting/color, continuity and source refs. Include panel descriptions and normalized 0..1 subject positions for schematic storyboards. Do not choose a generation provider or assume its capabilities.",
    "video-storyboards": "Review shot-list coverage and specify storyboard panels using the SAME shot IDs and durations. Each panel must include sceneId, shotId, durationSeconds, description, camera, color, subjects [{label,x,y}]. Describe framing, action direction and transitions. Trusted code renders schematic SVG panels; these are blocking boards, not finished concept art.",
    "video-edit-sound-vfx": "Plan the timed storyboard edit/animatic, transitions, dialogue timing, ambience, Foley, sound effects, music cues and VFX/continuity requirements per shot. Provide an edit decision list with shot IDs and durations. Specify rights/consent questions; no voice cloning, music licensing or external generation is authorized.",
    "video-production-plan": "Prepare a provider-neutral production package: asset dependencies, shot batching/schedule, continuity checks, acceptance criteria, retry limits, budget worksheet with quantities and UNKNOWN unit prices/totals, rights/consent checklist, postproduction plan for assembly/edit, VFX, sound mix, color grade, captions and delivery QC. Provider, model and spend cap remain UNDECIDED. Do not invent quotations or generate video.",
    "video-preflight": "Independently review the whole preproduction package for story/scene/shot coverage, timing, visual consistency, sound/VFX dependencies, rights and practical feasibility. Distinguish planning completeness from production approval. Video generation MUST remain blocked pending human discussion of provider/model, budget, rights and final plan. No approval can be inferred from passing this review.",
}

# Standing casting direction, not provider authorization or a workflow-generation trigger.
BRIEFS["video-voice-casting"] += (
    " Production policy for separately synthesized speech: plan premium ElevenLabs Eleven v3"
    " through fal, subject to a separately approved paid narration plan. Never propose Chatterbox"
    " or system TTS as a preview/fallback. Cast and direct for the intended genre; cinematic trailer"
    " narration needs resonant tone, deliberate pauses and controlled escalation, not neutral reading."
    " Plan a separate short audition and pin the accepted voice before full narration. Preserve"
    " pronunciation and performance-review criteria; successful ASR is not performance approval."
)


def apply_corrections(raw, proposal, evidence_ids):
    result = copy.deepcopy(raw)
    seen = set()
    for edit in proposal.get("edits", []):
        i = edit["segmentIndex"]
        if type(i) is not int or not 0 <= i < len(raw["segments"]) or i in seen:
            raise ValueError("Invalid or duplicate correction segment")
        seen.add(i)
        original = raw["segments"][i]["text"]
        if edit["before"] != original or not edit["after"].strip() or not edit["reason"].strip():
            raise ValueError("Correction does not match immutable source")
        if not set(edit["evidenceIds"]) & set(evidence_ids) or not set(edit["evidenceIds"]) <= {
            "raw",
            *evidence_ids,
        }:
            raise ValueError("Correction requires pinned evidence")
        if re.findall(r"\d+(?:\.\d+)?", original) != re.findall(r"\d+(?:\.\d+)?", edit["after"]):
            raise ValueError("Numerical changes require audio review, not contextual guessing")
        protected = r"\b(?:no|not|never|zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|hundred|thousand)\b|n't\b"
        if re.findall(protected, original.lower()) != re.findall(protected, edit["after"].lower()):
            raise ValueError("Negation and spoken numbers require audio review")
        if len(edit["after"]) > max(80, len(original) * 1.5):
            raise ValueError("Correction adds too much material")
        result["segments"][i]["text"] = edit["after"]
    result["artifactType"] = "corrected-transcript"
    result["reviewStatus"] = "ai-reviewed-unverified"
    result["corrections"] = proposal.get("edits", [])
    result["uncertainties"] = proposal.get("uncertainties", [])
    return result


def voice_profile_proposals(catalog):
    """Versioned, entity-linked plans only; never infer consent or a trained model."""
    return [
        {
            "schemaVersion": 1,
            "entityType": "VoiceProfileProposal",
            "id": f"{subject_type}-{person['id']}",
            "subjectType": subject_type,
            "subjectId": person["id"],
            "name": person["name"],
            "mode": "player-clone" if subject_type == "player" else "designed-character",
            "status": "proposed",
            "consent": "not-recorded",
            "consentEvidenceKey": None,
            "sampleKeys": [],
            "provider": None,
            "modelReference": None,
            "generationAuthorized": False,
        }
        for subject_type, people in (
            ("player", catalog.get("players", [])),
            ("character", catalog.get("characters", [])),
        )
        for person in people
    ]


BRIEFS["video-source-brief"] += (
    " Use the pinned scene's name, description and type as the baseline and the explicit creative brief as direction."
    " Scene types: opener (title/establishing), travel (location journey), map (animated route on a selected map), action, dialogue, general."
    " For travel, retain actual map/location evidence and label unknown geography; prefer deterministic map composition where appropriate."
    " Scene type is a planning choice, never spending authorization."
)
BRIEFS["video-generation-packets"] += (
    " Include coherent structured scene and cast information from the pinned revisions in each packet."
    " Keep the same character identity, appearance selection and wardrobe across shots unless an explicit source supports a change."
    " Recommend the standing production profile per shot: action Kling 3 Pro, dialogue MiniMax H3 Max (not Turbo),"
    " otherwise Veo 3.1 Fast for city/opener shots; action takes precedence over city setting."
    " Travel/map shots must cite actual map and location references, not invented geography."
    " Recommendations do not select a paid provider or authorize generation; leave execution, rights and budget gated."
)
BRIEFS["video-source-brief"] += (
    " When sourceChapter is present, use it as the exact creative source of the episode adaptation."
    " Cite its key, preserve consequential story outcomes, and keep sourceFacts empty unless actual sourceTranscripts supply the cited utterances."
)

BRIEFS["video-source-brief"] += (
    " A map scene has mapInput: an exact checksummed image, first-frame role, and route-animation instructions."
    " Use the attached image as actual visual evidence; extract only readable locations relevant to the user prompt."
    " Preserve uncertain or missing locations explicitly."
)
BRIEFS["video-generation-packets"] += (
    " For map scenes, include mapInput.key and sha256 as the exact first-frame image reference."
    " Return renderPrompt as concise visual/motion direction only: no review, provenance, provider, budget or production boilerplate."
    " Put the full mapInput.instructions in the executable image-to-video prompt along with the user's journey."
    " Treat the input image as a map: red starting dot, red footprints moving to the requested destination."
    " Preserve map labels/geography/style and identify ambiguous locations as planning uncertainty."
    " This is image-to-video planning, not a landscape shot or authorization for paid execution."
)

BRIEFS["novel-brief"] += (
    " For prompt-led novel requests, creation.title is merely the original prompt excerpt until a manuscript title is chosen."
    " Choose a concise original chapter title from the actual user direction and source-backed chapter content."
    " Optional absent transcripts stay absent; never invent source speech or factual session history."
)

# The same screen stages can publish an owned Episode. Manuscripts are creative
# source material, never raw testimony or factual context for corrections.
BRIEFS["video-generation-packets"] += (
    " When episodeDestination is true, also return episode with schemaVersion 1, title, synopsis and ordered scenes."
    " Each scene needs a unique slug id, concise title, type (general/opener/travel/map/action/dialogue),"
    " complete render prompt, exact narration words (empty when none), characterIds, referenceKeys and shotIds."
    " Copy the exact locked video-storyboards shots into the shots field. Partition every prior shot into exactly one scene, preserving shot order. Follow the locked shooting script,"
    " voice casting and continuity plans. Do not claim audio or footage exists. sourceChapter is a creative"
    " adaptation source; preserve its consequential story outcomes and disclose inventions separately."
)

BRIEFS["video-generation-packets"] += " For a scene-directed request (creation.sceneRef), emit exactly one scene using creation.sceneRef.sceneId; preserve that existing owner rather than creating a second episode or extra scenes."

BRIEFS["video-generation-packets"] += (
    " For an Episode destination, return shots as an empty array; the application copies the exact validated storyboard panels."
    " Reference those existing panels only through episode.scenes[].shotIds and partition every shot exactly once in its locked order."
    " Use only the characterIds and referenceKeys allowed by the output schema; narrative NPC names remain prose unless they have a pinned catalog identity."
    " Do not turn proposed prop labels, names or future assets into stored references."
)
