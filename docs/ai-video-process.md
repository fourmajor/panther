# AI session video: the audio-first process (plan 14)

This replaces the 16-stage video plan (treatment, screenplay, script edit, shooting script, breakdown,
design, reference plan, voice casting, blocking, edit/sound/VFX, production plan) and the one-take,
no-retry rule. It is generic. Game-specific references, prompts, shot books and outputs belong with the
session's artifacts in S3, never in this repository.

## Why

- Lip sync and pacing only work when the picture is cut to locked audio. Timing the audio to finished
  picture produced drift and dead air.
- Identity holds when every prompt carries the same identity block and the same reference sheet.
- One take with no retry left obvious defects in the cut. A small, capped re-roll budget fixes them.
- The 2026-11-12 bake-off (one 5 s dialogue shot on four models) chose the routing below.

## The seven stages

| # | Stage | Who | Output |
|---|---|---|---|
| 1 | Source brief | editorial `video-source-brief` | story-relevant facts with transcript citations |
| 2 | Audio script | editorial `video-audio-script` | line table (lineId, speaker, exact words, delivery, dialogue or narration), voice cast, music cue sheet |
| 3 | Audio lock | trusted tools | TTS clips, Whisper word timings, procedural score, master mix at -14 LUFS, `timing.json` |
| 4 | Cast lock | editorial `video-cast-lock` + image model | painted reference sheet and identity block per visible character |
| 5 | Shot book | editorial `video-shot-list` + `video-generation-packets` | shots on the master timeline, each with lineIds, kind, cast, prompt |
| 6 | First frames and board | editorial `video-storyboards` + image model | one composed first frame per shot; `video-preflight` checks the package |
| 7 | Generate, sync, cut, review | `tools/ai-video` | takes, review notes, the cut with the master mix laid back |

Stage 3 reuses `tools/procedural-video` (`voices`, `build-timing`, `score-engine`, `mix`). The audio is
locked before any paid picture is generated. If a line changes after lock, re-run stage 3 and re-time
the shot book; never stretch picture to cover it.

## Routing

| Shot kind | Model | Why |
|---|---|---|
| On-screen dialogue (one visible speaker, one line) | Seedance 2.5 reference-to-video (OpenRouter `bytedance/seedance-2.5`) | The only model in the bake-off that lip-syncs to supplied audio. The line clip goes in as an audio reference, with about 0.6 s of lead-in silence. |
| Everything else | MiniMax H3 Max image-to-video (OpenRouter `minimax/hailuo-3-max`) | Strong holds and camera moves, cheaper per second, no speech needed |

Seedance rejects photoreal human images as possible real people. Reference sheets and first frames
therefore use the game's painted portrait style, and H3 shots use the same style so the cut matches.
OpenRouter accepts only HTTPS audio URLs, so stage 7 presigns the line clip from the session bucket.
Veo was removed on 2026-11-12. Wan 3.0 rushed the line, and Gemini Omni refused the realistic first frame.

## Identity block

One short paragraph per character: visible facts only (age, build, face, hair, facial hair, skin, costume
layers and colours, signature props, handedness). It is pasted verbatim into every prompt that shows the
character, and the reference sheet is attached. `tools/ai-video` refuses a shot whose prompt lacks the
identity block of any visible cast member.

## Takes and re-rolls

- One take per shot by default.
- A re-roll needs a named defect: `lip-sync`, `identity`, `hands-anatomy`, `wrong-action`,
  `artefact`, `continuity` or `camera`.
- No shot gets more than 3 takes.
- Every take is kept. Review records the chosen take and the defect for each rejected one.

## Budget guard

`tools/ai-video` keeps a ledger per session. Before every paid call it reserves the estimate and refuses
if `spent + reserved + estimate` would pass the cap. The default cap is $9.00, and only an explicit owner
decision raises it. After the call the actual cost replaces the reservation; a failed job settles at $0
when the provider reports no charge. The ledger lives with the session artifacts.

## Sync and cut

- For each dialogue take, measure the offset between the take's own audio and the line clip by
  envelope cross-correlation, then trim so the mouth lands on the master line.
- Drop each take's first 2 frames, which often hold a blend from the reference.
- Concatenate the chosen takes on the master timeline.
- Lay the master mix back at -14 LUFS. The model's own audio is never used in the final mix.

## Review

Score each take on lip sync, likeness to the reference sheet, faces and hands, motion and continuity.
Contact sheets come from `ffmpeg` frame extraction. The cut is reviewed as a whole before delivery.
