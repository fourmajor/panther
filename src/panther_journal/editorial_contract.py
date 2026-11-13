"""Versioned editorial stages and deterministic correction guards. No generated code execution."""

import copy
import json
import re
from importlib.resources import files

PLAN = json.loads(files("panther_journal").joinpath("editorial-plan.json").read_text())
STAGES = [s for branch in ("correction", "novel", "video") for s in PLAN[branch]]

BRIEFS = {
    "video-audio-script": "Write the audio script the whole cut is timed from: a numbered line table with lineId, speaker (a pinned character entity ID, or narrator), the exact words, delivery direction, target seconds and the source fact or chapter passage each line comes from. Mark each line as on-screen dialogue (lip-synced) or narration (voice-over). Spoken lines total 45–75 seconds for a 60–90 second cut. Cast each speaker with a designed synthetic voice (a named Gemini TTS voice plus style direction) and keep it for every line; never clone or imitate a real player, celebrity or other real person. Add a music cue sheet (sections, mood, tempo, where it ducks under speech). Trusted tools then synthesize, Whisper-align and master the mix at -14 LUFS; picture is cut to that locked audio, never the other way round.",
    "video-cast-lock": "Lock the visible cast before any shot is planned. For each on-screen character give the pinned portrait keys, a reference-sheet request (face-on head and shoulders plus front, three-quarter and back full-length views on neutral grey, in the game's painted portrait style, never photoreal) and an identity block: one short paragraph of visible facts (age, build, face, hair, facial hair, skin, costume layers and colours, signature props, handedness) that is pasted verbatim into every prompt showing them. Lock recurring locations and hero props the same way. Describe only what the pinned portraits and sources support; list gaps as uncertainties instead of inventing them.",
    "video-source-brief": "Preprocess optional transcript sources against the user's creative brief and pinned cast. Select only story-relevant events, dialogue, character actions, setting and explicit continuity facts; exclude table chatter, irrelevant rules discussions and audit/provenance documents. Return sourceFacts with exact sourceKey and source-local segmentIndex for each extracted fact plus explicit uncertainty; quote dialogue only when that source actually contains it. Keep factual evidence, creative direction and proposed inventions distinct. With no transcripts, sourceFacts MUST be empty: work from the creative brief and explicit character/background references, without fabricating a transcript, recording session or supposed dialogue evidence. Describe the coherent proposed scene, cast and factual gaps in markdown. Do not generate media or authorize spending.",
    "novel-options": "Develop three genuinely distinct narrative approaches within the brief (POV, opening, emphasis, structure), compare tradeoffs, and choose one against explicit craft criteria. Create an original voice/style bible and a fact-versus-invention ledger. Do not average options into generic prose or imitate a named living writer. This is creative exploration, not factual correction.",
    "novel-continuity": "Audit the revised chapter against the corrected transcript and pinned game evidence: names, character knowledge, geography, chronology, possessions, injuries, goals and consequential events. Check distinct character voices, POV drift, cliches, repetitive AI phrasing and overexplained themes. Produce a concrete continuity/style ledger and targeted copyedit instructions; don't erase deliberate creative choices merely for uniformity.",
    "video-generation-packets": "Produce provider-neutral per-shot generation packets tied to locked shot IDs: reference bundle/appearance IDs, initial/end-frame requirements, visual composition, subject action, environmental motion, camera motion and timing, continuity dependencies, proposed duration, acceptance/rejection tests, and bounded candidate/retry counts. Prefer one clear action/camera idea per shot, positive observable instructions, separate image-to-video motion prompts from text-to-video scene descriptions, and flag conflicting instructions. Record provider/model/seed/support as undecided, never assume seeds or camera controls guarantee continuity. Plan candidate comparison and selected-take provenance. Do not generate any image/audio/video or choose a provider.",
    "context": "Select relevant game evidence: character names, aliases, locations, chronology, prior transcripts, ruleset and metadata. Explain relevance and uncertainty. Never select adaptations, held-out scripts or future-session spoilers as factual authority.",
    "correction": "Propose minimal speech-recognition corrections. No audio is available or expected; the pinned catalog and context text are the evidence for names and setting terms. Edit clear ASR errors: a catalog or context name or term spelled wrong in the utterance, an obvious mishearing, and a phrase duplicated by a recognizer hallucination. Use the catalog spelling and cite catalog or the context id on that edit. Set passed true when those edits are the correction. Utterance text may already contain a deterministic catalog-name repair; keep that spelling unless the evidence shows it is wrong, and set before to the utterance text shown in this input. Preserve table talk, hesitations, negation, uncertainty, numbers, player identities and timestamps. Do not invent missing speech, polish style, or delete chatter. Flag only a line you cannot resolve. An empty edit list while a clear catalog-name error remains is a failed round, not a decision to keep the raw wording.",
    "corrected-transcript": "Independently audit the supplied candidate against every raw utterance and pinned context, including consistency of repeated names. No audio is expected; do not reject a supported name correction for lack of audio. Fail if a clear catalog-name misspelling remains, if an edit is unsupported, if it changes meaning/identity/numbers, deletes table talk, fills missing sound, or treats game expectations as proof of speech. Retained wording with a note is acceptable only for a line that is actually uncertain. Passing means plausible AI corrections, not human verification. Return an actionable review. Rejection triggers automatic correction and fresh review. Restate an edit to change it. An empty edit list keeps candidate corrections already validated for this slice and does not excuse a catalog name that is still misspelled. Persistent disagreement keeps a candidate that already has corrections and records the uncertainty; it does not delete those corrections or publish raw speech over them.",
    "novel-brief": "Act as commissioning editor. Define audience, tone, original voice (no living-author imitation), POV, tense, chapter purpose, character goals/conflicts, emotional turn, continuity boundaries, and adaptation license. Separate table chatter/rules from story action without altering transcripts. For a test game, explicitly label this fictional test material, not campaign canon.",
    "novel-outline": "Develop a chapter synopsis and scene/beat outline: POV, goal, obstacle, escalation, reversal, consequence, transitions, opening promise and closing hook. Trace story events to transcript segments. Do not force a formula onto sparse material. List invented connective details separately.",
    "novel-draft": "Write the complete chapter from the approved brief/outline. Use scene, action, sensory detail, subtext, paced exposition and differentiated dialogue. Dramatize rather than summarize every utterance. Keep consequential outcomes faithful; disclose invented connective tissue in notes outside the chapter.",
    "novel-developmental-edit": "Independently edit the full draft for structure, causality, stakes, POV, characterization, pacing, theme and continuity. Supply prioritized concrete revision instructions. Distinguish intentional adaptation from unsupported changes to consequential game events.",
    "novel-revision": "Produce the complete revised chapter, addressing developmental notes. Preserve intended voice and source outcomes. Add a change log outside the reader-facing prose and list unresolved editorial questions.",
    "novel-line-copyedit": "Produce the complete line- and copyedited chapter. Improve sentence rhythm, clarity, dialogue, grammar and consistency without flattening voice. Supply a style sheet for names, capitalization, POV, tense, chronology and terminology.",
    "novel-proof": "Check the copyedited Markdown reading proof, including headings, paragraph breaks and dialogue punctuation. If revisionFeedback exists, revise the actual candidate chapter to address it. Return the COMPLETE final chapter alone in markdown, with proof notes and invention disclosures separately in decisions/uncertainties. This is a digital manuscript proof, not a claim of typeset print proofing.",
    "novel-chapter": "Independently quality-check the supplied candidate chapter (the latest revision, taking precedence over older priorStages) against the novel brief and continuity notes. The raw transcript is not in this prompt. Require compelling scene-level storytelling, coherent POV, resolved developmental issues, faithful consequential outcomes, and disclosed inventions. The title field becomes the published chapter title: use the story's concise literary title, never an audit, assessment, delivery or review label. Return pass/fail with actionable reasons; do not rewrite the chapter in this review. Rejection triggers an automatic actual manuscript revision and fresh audit, not a human approval request.",
    "video-shot-list": "Build the shot book on the locked audio script: ordered shots with stable shot IDs, scene ID and durationSeconds that together cover the line table in order. Begin every description with the lineIds it covers, its master-timeline start and end seconds and its kind (dialogue with the one visible speaker, or non-dialogue), then shot size, angle, lens intent, camera movement, one action per timed beat, lighting/color, continuity and source refs. Cut on line or music-section boundaries. Name visible characters by their cast-lock identity. Include normalized 0..1 subject positions for schematic storyboards.",
    "video-storyboards": "These panels are the first-frame board: each panel describes the composed opening frame to generate from the painted reference sheets. Review shot-book coverage and specify storyboard panels using the SAME shot IDs and durations. Each panel must include sceneId, shotId, durationSeconds, description, camera, color, subjects [{label,x,y}]. Describe framing, action direction and transitions. Trusted code renders schematic SVG panels; these are blocking boards, not finished concept art.",
    "video-preflight": "Independently review the whole preproduction package for story/scene/shot coverage, timing, visual consistency, sound/VFX dependencies, rights and practical feasibility. Distinguish planning completeness from production approval. Video generation MUST remain blocked pending human discussion of provider/model, budget, rights and final plan. No approval can be inferred from passing this review.",
}

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
    " Route each shot by kind: an on-screen dialogue shot is Seedance 2.5 reference-to-video driven by its"
    " locked line audio; every other shot is MiniMax H3 Max image-to-video at 768P with its own audio off."
    " Paste the cast-lock identity block of every visible character verbatim into the prompt and attach"
    " the painted reference sheet; never use photoreal identity images."
    " Start frames are generated by an OpenRouter image model from the reference sheets; a Blender render is allowed."
    " Plan one take per shot. A re-roll is allowed only for a named defect (lip sync, identity,"
    " hands or anatomy, wrong action, artefact) and a shot never exceeds 3 takes."
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
    " Copy the exact locked video-storyboards shots into the shots field. Partition every prior shot into exactly one scene, preserving shot order. Follow the locked audio script,"
    " cast lock and shot book. Do not claim audio or footage exists. sourceChapter is a creative"
    " adaptation source; preserve its consequential story outcomes and disclose inventions separately."
)

BRIEFS["video-generation-packets"] += " For a scene-directed request (creation.sceneRef), emit exactly one scene using creation.sceneRef.sceneId; preserve that existing owner rather than creating a second episode or extra scenes."

BRIEFS["video-generation-packets"] += (
    " For an Episode destination, return shots as an empty array; the application copies the exact validated storyboard panels."
    " Reference those existing panels only through episode.scenes[].shotIds and partition every shot exactly once in its locked order."
    " Use only the characterIds and referenceKeys allowed by the output schema; narrative NPC names remain prose unless they have a pinned catalog identity."
    " Do not turn proposed prop labels, names or future assets into stored references."
)


BRIEFS["video-source-brief"] += (
    " A request with creation.storyboardShotRef targets exactly that existing storyboard shot."
    " The pinned scene supplies context only: do not render other shots or rewrite its approved direction."
)
BRIEFS["video-storyboards"] += (
    " For creation.storyboardShotRef, plan only the exact pinned shot in the scene catalog."
    " Preserve its shotId, action, camera, narration and duration; do not expand into a whole scene."
)
BRIEFS["video-generation-packets"] += (
    " For creation.storyboardShotRef, emit footage instructions only for that exact shot."
    " Longer raw takes will be trimmed to the storyboard duration; never claim a short take satisfies a longer item."
)

# Audio-first production discipline (plan 14). These constraints improve new plans
# without changing previously approved storyboards or authorizing inference.
for _stage in ('video-shot-list', 'video-storyboards', 'video-generation-packets'):
    BRIEFS[_stage] += (
        " The locked master mix sets the cut: a full session cut runs 60–90 seconds in 8 to 16 shots,"
        " each 2 to 12 seconds, and every shot is timed to the line table, never the other way round."
        " Dialogue shots hold exactly one visible speaker's line on Seedance 2.5; other shots use H3 Max at 768P."
        " One take per shot; up to two re-rolls only for a named defect, never more than 3 takes."
        " The whole session render, re-rolls included, stays within the $9 session budget."
        " Use timed beats within an item; avoid asking a take to perform several unclear simultaneous"
        " interactions. Keep every consequential source action across items. Each item must state only its"
        " visible cast, relative size and screen positions, one clear physical action per timed beat with a"
        " start and end, exact prop ownership, setting/time, consistent lighting/palette and mood."
        " Express emotion as observable gaze, posture or movement. Bind character appearance to the cast-lock"
        " identity blocks and painted reference sheets, and apply the same game visual style across all items."
        " Include relevant setting/story continuity, not the whole cast or unrelated plot. Separate narration"
        " from on-screen speech. Starting frames depict the composed shot, never a portrait contact sheet."
        " Specify acceptance checks for lip sync, visible cast, costume, hands, props, geography and source outcomes."
    )

BRIEFS["video-preflight"] += (
    " Check the plan against the audio-first rules: every on-screen line has exactly one dialogue shot,"
    " every visible character has a cast-lock identity block and painted reference sheet, the shot timings"
    " match the line table, and a worst-case render (3 takes per shot) is reported against the $9 session budget."
)
