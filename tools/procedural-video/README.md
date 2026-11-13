# Procedural recap pipeline

Turns a session folder (a shot timeline, a list of spoken lines, a cast, a score and some three.js sets) into a
short cinematic recap **rendered entirely by code**: real-time 3D in three.js/WebGL2 for the picture, a pure-Node
orchestral synthesiser for the music, word-synced captions, and optional AI voices. No Blender, no image/video/music
models, no samples or image assets.

The framework (`scene/`, `tools/`) contains nothing about any particular story. Everything story-specific lives in
`sessions/<name>/`.

```
SESSION=sessions/<name> npm run render     # timing -> score -> mix -> frames -> mux  => out/<output>.mp4
SESSION=sessions/<name> npm run voices     # optional: TTS + word alignment (only when OPENROUTER_API_KEY is set)
SESSION=sessions/<name> npm run stills     # 12-frame contact sheet -> out/contact-sheet.png
SESSION=sessions/<name> node tools/capture.js --stills 12.5,44.9 --tag x     # chosen stills -> out/contact-x.png
```

Output: 1920x1080, 30 fps, H.264 yuv420p, AAC 48 kHz stereo, 2.39:1 letterbox with captions in the lower bar.
Requirements: Node 20+, `npm install` (three, puppeteer), ffmpeg/ffprobe on the PATH, python3 for the voice step.

## Default setup

| Stage | Tool | What it does |
|---|---|---|
| Voices (optional) | `tools/voices.js` -> `tools/voice/tts_gemini.py`, `tools/voice/align_whisper.py` | Gemini TTS via OpenRouter, one WAV per line using the session's `voices.json` cast; Whisper word timestamps -> `voices/alignment.json`. The key is read from `OPENROUTER_API_KEY` only; without it the step is skipped. Nothing else in the pipeline touches the network. |
| Timing | `tools/build-timing.js` | Audio-first clock: line lengths from the real clips, speech in/out and per-word times from Whisper, mapped back onto the canonical `lines.json` text. Re-flows shot boundaries and beats into `out/timing.json`. |
| Score | `tools/score-engine.js` + `<session>/score.js` | Procedural symphony: the engine provides instruments, sequencing and a hall reverb; the session supplies the composition, keyed to shot/beat/line names. |
| Mix | `tools/mix.js` | Dialogue placement, sidechain ducking of the score (9 dB, look-ahead, smooth), master to -14 LUFS integrated with a true-peak limiter at -1.2 dBTP. |
| Picture | `tools/capture.js` + `scene/` + `<session>/scene/` | Puppeteer drives headless Chrome on the GPU, steps `t = i/fps`, calls `window.renderFrame(t)` and streams frames straight into ffmpeg, muxing `out/mix.wav`. |

Env knobs: `DUCK_DB`, `TARGET_LUFS`, `CEILING_DBTP` (mix); `TTS_MODEL`, `STT_MODEL` (voices).

## Framework

```
scene/index.html     page: WebGL canvas + DOM typography (title card, slugs, word-synced captions, end card)
scene/main.js        window.renderFrame(t); loads out/timing.json and <session>/scene/index.js; transitions;
                     window.renderCloseup(name, variant, t) for a session's close-up studio (mode=closeups)
scene/post.js        HDR pipeline: MSAA + depth -> raymarched volumetric fog / light shafts -> bokeh DoF -> bloom
                     -> ACES, grade, fringe, vignette, grain, letterbox, fades and flashes
scene/kit.js         batched geometry, world UVs, arched walls, voussoirs, columns, ribs, battlements, GPU particles
scene/textures.js    procedural PBR masonry (irregular ashlar / rubble / flags with erosion, cracks, lichen, grime)
                     plus world-space weathering; net and cloth textures
scene/sdf.js         signed-distance sculpting kit + surface-nets mesher (heads, skulls, jaws, pelvises, palms)
scene/face.js        procedural heads from a spec: skull shape, sockets, eyeballs (iris/pupil texture, wet clear-coat),
                     blinking lids and lashes, brows of individual hairs, nose, lips, jaw, ears, teeth, tongue;
                     skin shader (wrap/SSS diffuse, back-scatter, pores, wrinkles, freckles, stubble); morph
                     targets for jaw, lip shapes, smile/frown/snarl, brows, squint
scene/hair.js        strand-ribbon hair grown over a head's field: hairline, parting, gravity, waves, curls, locks, bun
scene/hands.js       articulated hands (palm, 4 x 3 phalanges, 3-joint thumb, nails/claws, gloves, bone variant) and a
                     pose table: relax, fist, grip, rapier, point, open, plead, claw, rope, hold
scene/skeleton.js    anatomical skeleton (skull + hinged jaw + teeth, vertebrae, ribs, sternum, clavicles, scapulae,
                     pelvis, long bones, hand/foot bones), aged bone, rusted armour scraps, eye points, jaw chatter
scene/materials.js   object-space procedural materials: cloth, linen, leather, damask, chain, fur, wood, metal, rust,
                     bone; soft skin
scene/figures.js     figure builder from a recipe: jointed body, 2-bone IK, wrist aiming / grasp, head + hair + hands,
                     wardrobe parts (straps, skirts/coats, collars, fastenings, trim, panels, pauldrons, cuffs, sleeves,
                     boots, hats with plumes, shields, scabbards, pendants, fetishes, earrings), cloaks, props
scene/lipsync.js     lip-sync driver: word timings + loudness envelope -> jaw / wide / round / emphasis per speaker
scene/util.js        seeded PRNG, noise, easing, stepped time
tools/envelope.js    per-clip loudness envelopes for lip sync -> out/envelopes.json (part of `npm run render`)
tools/sheet.js       contact sheets for review loops
tools/session.js     resolves SESSION / --session
tools/usage-guard.sh generic usage guard (see below)
```

Review close-ups (faces, hands, skeletons) render through the same post pipeline as the film:

```
SESSION=sessions/<name> node tools/capture.js --closeups all --variants front,three --dir out/closeups
```

A session provides them by exporting `closeups(renderer)` from `scene/index.js` -> `{ names, render(name, variant, t, ctx) }`.
Shots get lip sync from `ctx.speech('<speaker>')` and apply it with `figure.talk(state, expressionOffsets)`.

Rendering is deterministic: every frame is a pure function of `t` (no wall clock, no `Math.random`; particles are
stateless and shadow maps are redrawn per frame).

## Adding a session

Create `sessions/<name>/` with:

1. **`timeline.json`** — `title`, `subtitle`, `output`, `fps/width/height/letterbox`, `total_range: [min, softMax]`,
   optional `hard_max`, `title_card: {shot}`, `end_card: {shot, quote_line, credit}`, optional `speaker_labels`, and
   `shots: [{name, set, duration, min, transition: cut|dip|flash|dissolve|fade-in, slug, camera, beats}]`.
   A beat is `{name, at}` (seconds from shot start; negative = from the end) or `{name, line, offset}`.
2. **`lines.json`** — `[{id, speaker, voice_hint, text, source, start, target_duration, shot, audio}]`. `text` is
   canonical: captions always show it, whatever the recogniser heard.
3. **`voices.json`** — `{ "<speaker>": {"voice": "<TTS preset>", "instructions": "<delivery>"}, "_default": {...} }`.
4. **`scene/index.js`** — `export function buildSets(renderer)` returning
   `{ <set>: { scene, shots: { <shotName>(localT, duration, ctx) } } }`. Each shot function poses the scene for that
   instant and returns `{scene, camera, parts, focus, aperture, exposure, bloom, fog, flash, ...}`. `ctx` gives
   `T`, `start`, `end`, `beat(name)`, `line(id)`, `lineEnd(id)` in absolute seconds. Build sets from `scene/kit.js`,
   `scene/textures.js`, `scene/figures.js`.
5. **`score.js`** (optional) — `module.exports = api => { ... }` using the engine's instruments (`strings`, `brass`,
   `wind`, `choir`, `timp`, `bell`, `pluck`, `celesta`, `wash`, `bdrum`) and helpers (`P`, `seq`, `chord`, `hit`),
   with `api.S` (shots), `api.Bt` (beats) and `api.Ln` (lines) for cue times. Without it a plain fallback bed is used.

Then `SESSION=sessions/<name> npm run voices` (optional) and `SESSION=sessions/<name> npm run render`.
Session folders hold game-specific material (cast, portrait mappings, quotes, shot content) and are kept out of this repo; store them with the session's other artifacts.

Timing rules: above the soft maximum, shots give back slack they do not need; pauses between lines are squeezed
only if the total would still exceed `hard_max`.

## Usage guard for unattended agent runs

When an AI coding agent builds or iterates on a session unattended, run a guard beside it that polls your usage
meter and stops the run before it eats the budget. `tools/usage-guard.sh` is the generic form: give it `PROBE` (a
command printing a usage percentage), `MATCH` (a process pattern for the run) and `LIMIT`; it logs each reading to a
markdown table and kills the run at the limit, or exits when the run finishes. Pair it with a rule such as "do not
start above 50 %, stop at 55 %".

`tools/run-agent.sh` wires this up for Claude Code: `BRIEF=<brief.md> MODEL=claude-fable-5-2 tools/run-agent.sh` checks
usage with `tools/claude-usage-probe.sh` (headless `/usage`, no tokens), refuses to start at 50 % or more, runs the
agent headless on the subscription (API-key variables unset, no fast mode), and kills it at 55 %. Keep briefs, which
are game-specific, with the session rather than in the repo.

## Not part of the framework

Source material (transcripts, chapters, briefs), reference frames, run logs and `out/` are working files; keep them
out of the framework repo or inside the session folder.
