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

Publishing stops before any upload when the master exceeds that limit. Explicitly use
`panther video production publish RUN_DIRECTORY --retain-oversize-master-locally` to keep the
unchanged full-quality master locally while publishing the browser movie, captions, stems and
mix. Provenance records the master's checksum, size and local-only disposition; no nonexistent
cloud master link is created. Preserve the run directory in durable private storage. This does
not enable multipart uploads or lower the master quality.

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

For an approved replacement, pass `--new-version-of SAME_GAME_PRIOR_BROWSER_MP4_KEY`
to publication. Only the browser movie joins that semantic version family; master,
stems and provenance remain new immutable related outputs. The predecessor is pinned
before any upload, unchanged resumes are idempotent, and a different predecessor
fails closed. Source lineage stays distinct from version history. This never overwrites
the earlier movie or authorizes another paid generation.

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

Captioned browser delivery requires an FFmpeg build with the `subtitles` filter
(libass), in addition to the documented video/audio codecs. Check
`ffmpeg -hide_banner -filters` before running captioned finishing. The integration
tests explicitly skip captioned delivery when that optional local capability is
absent; schema, source-integrity and other available-tool tests still run.

## Assemble an episode from finished scenes

Episodes contain an explicit ordered scene list. Each scene selects exactly one already
finished, same-game video output with an exact generation scene revision. Reordering an
episode creates an Episode revision; changing its scene selection creates a Scene revision.
Missing selections block rendering of the whole episode rather than silently omitting a scene.

```sh
panther videos render-episode --game GAME_ID --episode EPISODE_ID --work-dir /private/path/episode-renders
# Optional explicit publication after rendering:
panther videos render-episode --game GAME_ID --episode EPISODE_ID --work-dir /private/path/episode-renders --publish
# Recover/inspect local output first, then publish separately:
panther videos publish-episode /private/path/episode-renders/RUN_HASH
```

This separate deterministic assembly uses **FFmpeg only**, without an AI review, regeneration,
paid provider request, or additional voice production. It pins an authenticated EpisodeComposition
and downloads every selected original through Panther signed object access, verifying its exact
SHA-256 and byte length. The content-addressed run retains its private manifest, original scene
files, technical logs, normalization attempts and completed-output receipts outside Git. An
identical pinned composition resumes a verified completed checkpoint; changing order, Scene
revision or selected output creates a new run. Incomplete downloads and failed attempts remain
recoverable and never overwrite successful source files.

The version-1 profile supports 1–20 scenes, at most five minutes per scene and thirty minutes
in total. MP4, MOV and MKV inputs have one SDR video track and at most one selected mixed
audio track through 4K; HDR is rejected without a tone-map
profile. It explicitly normalizes picture to letterboxed 1280×720 at 24 fps, H.264 CRF 18,
and sound to stereo 48 kHz. Selected scenes' existing mixed soundtracks are preserved, including
dialogue, music and ambience; a scene with no audio receives an explicitly recorded silent track.
This operation does not default to mute, infer separate stems, insert transitions, change gain,
apply creative trims, generate missing narration, or invent captions. Normalized intermediate
clips retain PCM audio so scene boundaries avoid repeated AAC encoder padding; the final
continuous browser MP4 receives AAC 192 kbps and fast-start layout. The original files remain
unchanged. Duration and a complete technical decode are verified, with explicit limits: these
checks do not constitute a new perceptual listening or creative continuity review.

Publication is explicit and uses Panther's immutable upload operation and server path builder.
A hidden `episode-composition` JSON records the exact ordered scene references, original
generation scene references, selected source keys/checksums/sizes, Episode revision and actual
FFmpeg version. The finished `tv-episode` browser output points to that intermediate artifact,
allowing Inputs/Outputs to traverse to all finished scene inputs without crowding metadata or
presenting manifests as ordinary media. `extra.episodeRef` and `extra.compositionHash` identify
its exact episode selection. Generation metadata reports procedural local FFmpeg with no
inference charge; it does not relabel or duplicate upstream provider charges. Publication stops
before a browser file exceeding 1 GiB and preserves the local output. Interrupted uploads may
already have succeeded: storage rejects duplicate writes, so inspect Panther metadata and retain
the original upload identity rather than choosing another identity to hide the uncertainty.

`pytest -q tests/test_episode_rendering.py` exercises real synthetic colored scenes and different
audio tones, checking visible scene order, audible tone order, continuous duration, unchanged
sources, strict checksums and no-overwrite behavior. It performs no cloud or paid calls.
