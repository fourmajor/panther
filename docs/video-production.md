# Local video production, version 1

Panther now **executes** a separate finishing workflow after footage selection. This is not a
new paid-generation state in the transcript/editorial Step Function. The owner’s laptop runs
FFmpeg and subscription-backed Codex reviews; OpenAI hosts inference. There is no additional AWS
resource, idle cloud polling, API-key inference, voice cloning or automatic paid retry.

## Process

1. **Prepare shots:** select immutable appearance references, a complete starting composition and
   optionally an ending frame. Review the actual plates against the references, blocking, costume,
   prop/weapon hand, camera and continuity brief. Produce an **unapproved** generation manifest.
2. **Generate/select elsewhere:** use the existing separately approved `panther video` budget guard.
   Preserve every provider original and exact generation metadata. Attach selected uploaded takes
   to the production manifest. Only explicitly `complete: true` manifests can start finishing.
3. **Review footage:** sample each selection at four frames/second in ordered contact sheets;
   compare selected appearances, faces, clothing, weapon hands, object locations, movement, screen
   direction, composition and color. Every category needs evidence or an honest not-visible/uncertain
   result. Compare the previous shot's ending as well. No claim of exhaustive frame/lip-sync review.
4. **Edit and re-review:** apply bounded endpoint trims and modest exposure/contrast/saturation
   adjustments. Preserve intentional scene/lighting changes. Never cut supplied caption/dialogue/sound
   cues or trim a kept native mixed track without verified speech boundaries. Save the actual edited
   picture and obtain a fresh review. Unresolved problems become **WORKING_DRAFT**, not approval or
   another paid generation request. No routine human creative gate.
5. **Sound:** render independently editable, full-length dialogue, music, effects, ambience and
   native-mix WAV stems. Mix supplied cues at explicit times/gains; duck music under independent
   dialogue, normalize toward -16 LUFS/-1.5 dBTP, and measure actual loudness/peak. Empty stems are
   silence, explicitly not generated content. Native audio defaults to muted.
6. **Finish:** assemble the selected edit, produce a clean 720p24 ProRes 422 HQ/24-bit PCM MOV master,
   timed editable WebVTT, and fast-start H.264/AAC MP4 with burned-in captions when supplied. Caption
   burn-in makes the browser copy self-contained; the master stays editable. Decode both deliveries,
   check duration and true peak, then independently review the assembled sequence across cuts.
7. **Publish:** explicitly upload master, browser version, captions, stems, mix and structured
   provenance through Panther authentication. Finished media and hidden processing assets retain
   exact lineage; originals are never overwritten.

The browser AAC export reserves an additional 1.5 dB of gain headroom because lossy encoding can
reconstruct peaks above the PCM mix. The master and stems are unchanged. The actual gain is recorded
in delivery provenance, and both decoded exports must still pass the same true-peak check.

The 720p24 profile is bounded and repeatable, not a claim that resampling restores detail. It handles
SDR inputs through 4K, rejects HDR until a reviewed tone-map profile exists, and preserves originals
at their native resolution. Masters can be large; the existing 1 GiB upload limit remains a hard
limit, never silently lower quality or split the master to bypass it. Local jobs allow up to 20
shots, 30 seconds each, and five minutes total. Future profiles require a workflow version bump.

## Sound and review honesty

A generator's soundtrack is a **native mix**, not isolated dialogue/music/effects. This workflow
does not pretend channel splitting can recover stems, remove only a laugh track from mixed speech,
or synthesize missing dialogue. Mute it and supply independently created/authorized audio to replace
it. Each cue has an explicit rights note; do not invent consent or license evidence. No TTS,
source-separation model download or voice-training service is implicitly approved here.

Codex receives selected frame images and structured evidence, **not the soundtrack**. Audio checks
are technical: decoded duration, measured loudness and peak, not perceptual listening or verified
speech/lip sync. These limits persist in the result and publication provenance. AI_REVIEWED means
the sampled visual checks passed, not human approval or complete audiovisual certification.
Insufficient samples/uncertainty must remain visible. Failed creative checks still produce an
inspectable working draft. Credentials, corrupted evidence and subscription limits stop safely.

## Commands and trigger

```sh
panther video production schema
panther video production prepare /private/path/production.json --work-dir /private/path/video-jobs
# Explicit models/references/rights and budget approval remain required before paid generation.
panther video production run /private/path/completed-production.json --work-dir /private/path/video-jobs
panther video production publish /private/path/video-jobs/RUN_ID

# Optional local queue: process only explicitly completed manifests, not individual arriving files.
panther video production worker --inbox /private/path/video-inbox --work-dir /private/path/video-jobs
```

The worker is a local inbox workflow, **not a deployed AWS event subscription**. Put a manifest in
the inbox atomically after all declared selected inputs have been uploaded and downloaded locally.
`complete: false` stays pending; a missing/mismatched declared input fails instead of guessing the set
is complete. The worker verifies every file's immutable Panther checksum before any review. It never
auto-publishes or spends. The command can also run directly from an authorized agent after generation
finishes. It runs while awake; no always-on compute is needed. `--once` drains one scan and exits.

Resuming the exact same manifest uses the same content-addressed run and verifies all saved-stage
checksums. Stage outputs and failed partial attempts remain private and recoverable. Locks prevent
duplicate concurrent work. A subscription pause exits without another provider or purchase; restart
the same command after capacity returns. Changed selections/settings produce a distinct revision.
Private inputs, copies, prompts and outputs belong outside Git. Cleanup is an explicit owner action.

## Manifest

Use `production schema` for the complete strict JSON Schema. A synthetic minimal example:

```json
{
  "schemaVersion": 1,
  "entityType": "VideoProduction",
  "gameId": "synthetic-game",
  "sessionId": null,
  "title": "Harbor scene",
  "complete": false,
  "sourceKeys": [],
  "shots": [{
    "id": "harbor-wide",
    "sceneId": "harbor",
    "use": "city",
    "prompt": "Wide harbor establishing shot; slow forward camera movement.",
    "continuity": "Late afternoon, ships remain on screen left; warm neutral palette.",
    "appearances": [],
    "inSeconds": 0,
    "outSeconds": 8,
    "nativeAudio": "mute",
    "sounds": [],
    "captions": []
  }]
}
```

Every `Reference` is `{key, sha256, path}`: exact immutable same-game asset reference, lowercase
hex SHA-256, and an absolute local private path. Add a `clip` reference before marking complete.
Character shots require `appearances: [{characterId, reference}]` and a `startImage` reference:
select the intended appearance revision explicitly, not a mutable “latest” filename or inferred
identity. The starting image must be a prepared full 16:9 composition, not a cropped headshot.
The preparation step validates/reviews existing plates; it does **not** create missing imagery.
Use the authorized image creation process to make missing plates before preparation.

`use` selects the owner's model policy: city/default → Veo 3.1 Fast; dialogue → H3 Max (not Turbo);
action → Kling 3 Pro. Mixed scenes should be broken into shots with one dominant purpose. A pinned
starting frame selects the corresponding image adapter. `endImage` is currently accepted only for
Kling action image shots. Preparation has no billing client, permission declarations or submit path.
Reports can flag unready compositions; a generated manifest is never itself approval to use them.

Each sound cue supplies `role` (dialogue/music/effects/ambience), `source`, `at` (original shot time),
`sourceStart`, `duration`, `gainDb` and a factual `rightsNote`. Caption cues supply `start`, `end`,
plain single-line `text` and their exact `source` reference. All times are seconds within the
original selected clip. Trust actual recorded/generated speech timings, not screenplay intent.
The assembler maps cues to the final timeline after permitted trims. Captions are not autogenerated
transcripts; supplying none produces no caption text rather than invented words.

## Publication and existing assets

New kinds use the existing layout-2 server builder and extensible structured metadata; there is no
new physical-path convention or legacy storage fallback. `video-production` is an intermediate
provenance artifact with full `sourceKeys`/`inputArtifacts`. Final `tv-episode` browser files and
`video-master` exports point to it, letting the reader traverse to finished original inputs.
Stems/mix/caption technical files are marked intermediate. Exports share an asset identity, not a
mutable output list on sources. Actual model/provider/cost for original generation stays on original
clips; the finishing operation records subscription-backed Codex plus local FFmpeg, not another
charge for upstream video generation. Machine-specific paths are removed from published JSON.

Existing clips remain original footage, not invalid pre-workflow productions. This new derived
artifact type imposes no invented historical QC, appearance choices or sound-isolation metadata on
them. They can all be selected as immutable inputs using the same contract. Re-finishing creates
new assets with original provenance; never relabel existing comparison footage as reviewed masters.

## Verification and sources

`pytest -q tests/test_video_production.py tests/test_video.py` tests contracts, exact source checks,
no-overwrite/resume behavior, real FFmpeg audio replacement/normalization, caption pixels, codecs,
working drafts and paid-adapter isolation using synthetic media. No cloud credentials or real
generation in tests. An opt-in laptop-only `PANTHER_VIDEO_AI_SMOKE=1` test additionally exercises
the real subscription reviewer; never enable it in CI or mount personal credentials in a runner.

- [Community filmmaking guide](https://www.reddit.com/r/aivideo/wiki/tutorials/) and
  [tool directory](https://www.reddit.com/r/aivideo/wiki/index/): motivation for continuity,
  deliberate image anchoring, separate sound and finishing; not provider quality benchmarks.
- [Kling Pro image schema](https://fal.ai/models/fal-ai/kling-video/v3/pro/image-to-video/api):
  verified optional `end_image_url` on 2026-09-10. Both images get the same checksum, size, cloud
  identity, consent and budget guards. The existing Veo Fast/H3 Max adapters do not expose verified
  ending-frame support, so Panther rejects that request rather than dropping it.
- [FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html): deterministic assembly, mixing,
  ducking, loudness measurement, grading and caption rendering.
- [Codex non-interactive execution](https://learn.chatgpt.com/docs/non-interactive-mode) and
  [CLI reference](https://learn.chatgpt.com/docs/developer-commands?surface=cli): fresh sessions,
  image attachments and structured results. ChatGPT-only auth, tools disabled, no agent credentials.
