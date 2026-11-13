# AI session video runner (plan 14)

Stage 7 of `docs/ai-video-process.md`, plus the image steps of stages 4 and 6. It's generic: a session
folder holds everything game-specific and is kept with the session artifacts in S3, never in this repo.

```
SESSION/
  shotbook.json      cast (identity blocks, sheets), lines (audio, master start), shots, master mix
  audio/             locked line clips and mix.wav from tools/procedural-video (voices, build-timing, mix)
  audio/windows/     per dialogue shot: its lines at their master offsets (written by the runner)
  audio-urls.json    {"S05": "https://..."}: presigned HTTPS URL of each dialogue window (OpenRouter needs HTTPS)
  cast/ frames/      reference sheets and first frames
  takes/<shot>/take-N.mp4, takes.json, ledger.json, cut/, out/
```

```sh
python3 tools/ai-video/ai_video.py validate SESSION          # schema, routing, identity blocks, cost
python3 tools/ai-video/ai_video.py sheet SESSION endrik      # painted reference sheet from the portraits
python3 tools/ai-video/ai_video.py frame SESSION S03         # composed first frame
python3 tools/ai-video/ai_video.py take SESSION S03          # first take
python3 tools/ai-video/ai_video.py review SESSION S03 1 --reject lip-sync
python3 tools/ai-video/ai_video.py take SESSION S03 --defect lip-sync    # re-roll: named defect, max 3 takes
python3 tools/ai-video/ai_video.py review SESSION S03 2 --accept [--nudge 0.04]
python3 tools/ai-video/ai_video.py cut SESSION               # picture on the master timeline + mix at -14 LUFS
python3 tools/ai-video/ai_video.py ledger SESSION
```

## Shot book

```json
{
  "budgetUsd": 9.0, "fps": 24, "size": "1280x720", "output": "session.mp4",
  "style": "the painted game-portrait style",
  "master": {"mix": "audio/mix.wav"},
  "cast": {"hero": {"identity": "One paragraph of visible facts...", "sheet": "cast/hero.png",
                    "portraits": ["refs/hero-portrait.png"]}},
  "lines": {"L06": {"speaker": "hero", "audio": "audio/L06.wav", "start": 28.8, "text": "..."}},
  "shots": [
    {"id": "S05", "kind": "dialogue", "lines": ["L06"], "start": 28.2, "duration": 4.5, "cast": ["hero"],
     "frame": "first-frame composition", "prompt": "... identity block pasted verbatim ..."},
    {"id": "S06", "kind": "scene", "start": 32.7, "duration": 6.0, "cast": [], "frame": "...", "prompt": "..."},
    {"id": "S07", "kind": "still", "start": 38.7, "duration": 5.0, "frame": "establishing matte painting"}
  ]
}
```

- Shots are contiguous on the master timeline, 2–12 s each. `kind` sets the model:
  - `dialogue` uses Seedance 2.5, driven by the shot's audio window, with up to three cast sheets as
    references. A dialogue shot holds one visible speaker's consecutive lines.
  - `scene` uses H3 Max.
  - `still` is a slow push-in on the first frame and costs nothing beyond the image.
  A `model` override is allowed for scene shots only.
- A line's `start` is where its clip begins on the master (the speech start minus the clip's lead-in).
- `validate` refuses a prompt that lacks the identity block of any listed cast member, and a dialogue
  shot whose speaker isn't visible.
- H3 bills at least 5 s and Seedance at least 4 s. The cut trims to the shot length.

## Guards

- **Budget.** `ledger.json` reserves each estimate before the call and refuses when committed spend plus
  the estimate would pass the cap (default $9.00). A cap above $9 needs `budgetOwnerApproved` in the
  shot book. The cap stored in the ledger never widens.
- **Takes.** The first take needs no reason. A re-roll needs a named defect that review has recorded
  (`lip-sync`, `identity`, `hands-anatomy`, `wrong-action`, `artefact`, `continuity`, `camera`).
  Three takes is the hard maximum.
- **Key.** The OpenRouter key comes from `OPENROUTER_API_KEY` or `OPENROUTER_KEY_FILE` and is never printed.

## Sync

`sync.py` is adapted from claudia_kit (MIT). It finds each spoken phrase of the locked line in the take's
own soundtrack (log-mel subsequence DTW), and the cut re-times the picture along that map, so lips land
on the master words even when the model moved a pause. `syncCost` is reported per take: below about 0.2
means the model copied the line, 0.2–0.4 means it re-performed it. The take's own audio never reaches
the final mix. Each take's first 2 frames are dropped.

Runs on a small Linux box. It needs Python 3.11+, numpy and ffmpeg, and decodes one take at a time,
using about 1 GB for a 12 s 720p take.
