# Persistent local development

## Start the complete stack

Install Python dependencies, frontend dependencies and FFmpeg (`ffmpeg` and `ffprobe`):

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
npm ci --prefix web/ui
cp .env.example .env
chmod 600 .env
```

Fill `OPENAI_API_KEY`, `FAL_API_KEY` and `ELEVENLABS_API_KEY` in the gitignored `.env`.
Never place actual keys in source, URLs, browser code or logs. Shell environment values
have precedence. `PANTHER_EDITORIAL_MODEL` defaults to `gpt-5-mini`; `XAI_API_KEY` is
optional and is not required by the currently selected providers.

```sh
.venv/bin/python tools/dev.py
```

Open **http://127.0.0.1:8766/**. The launcher builds the React components and starts
all nine processors before the API. Startup checks private key-file permissions,
required credentials/tools, conflicting worker locks and **fresh database heartbeats**
from every processor. A process merely remaining alive does not count as readiness.
Errors name the missing setting or worker log. Provider keys stay in server-side processes;
the server reads the ElevenLabs key for the stock-voice picker. They never enter browser code.

The thumbnail processor uses local FFmpeg to backfill existing and newly uploaded/generated
videos without paid inference. It samples the opening ten seconds in order, skips black/blank
frames, and retains a JPEG derivative with the exact immutable video as its source. All-black
footage retains its actual first frame. Video library/object projections expose `thumbnailKey`
and `thumbnailStatus`; episode posters come from the first ordered scene with an actual video.
An explicitly selected take wins; otherwise the latest completed render supplies the poster.
This projection never chooses a playback take or changes episode assembly readiness.
Extraction errors are retained once in the private `video-thumbnail` records and worker log,
without repeating a failing decode indefinitely. This local processor does not migrate hosted
storage; hosted thumbnail backfills must use authenticated immutable upload/catalog operations.

Defaults:

- Database: `~/.local/state/panther/development.sqlite`.
- Logs/checkpoints: `~/.local/state/panther/development-workers/`.
- Port: `8766`.

Override with `--database`, `--work-dir`, `--port`, or `--env-file`. `--no-build` skips
rebuilding existing React bundles. Paths containing actual data must remain outside Git.
Only one processor of each kind may own a database at a time. Do not start the launcher
alongside manually started processors using the same database.

## Processors and provider calls

| Processor | Purpose | Provider/tool |
| --- | --- | --- |
| `dev_editorial_worker.py` | Full chapter writing/revision/independent review and screen planning | OpenAI Responses API |
| `dev_image_worker.py` | Character portraits and generated assets | OpenAI image API |
| `dev_transcription_worker.py` | Live parts and a separate complete recording pass | OpenAI `gpt-4o-transcribe` |
| `dev_summary_worker.py` | Source-cited transcript summaries and regeneration | OpenAI Responses API |
| `dev_playback_worker.py` | Continuous listening copies of completed WAV sets | Local FFmpeg |
| `dev_video_worker.py` | Explicit scene video generation | fal: Veo 3.1 Fast, MiniMax H3 Max or Kling 3 Pro |
| `dev_narration_worker.py` | Stock-voice narration with performance direction | ElevenLabs `eleven_v3` |
| `dev_episode_worker.py` | Ordered episode assembly from selected real scene outputs | Local FFmpeg |

A scene requires a title; extra direction is optional. Action uses Kling 3 Pro,
dialogue uses MiniMax H3 Max, and other scenes use Veo 3.1 Fast. Map scenes pin the
selected map as the actual input frame and direct route markers/footprints. Selected
transcripts are optional sources: prompt composition extracts relevant source-local
facts with exact segment citations, preserving unknown speaker identities. Character
profiles and other selected context guide the creative prompt without altering speech.

Episodes have nested `/games/:gameId/videos/:episodeId` pages, with scene URLs below
`/scenes/:sceneId`. The scene view is a read-only summary; Edit scene owns the prompt,
character selection and optional source material. Scene records may include versioned
`generationInputs`; missing inputs mean an empty selection, not inferred characters.
Saves preserve those inputs across output selection and retain every earlier scene revision.
Selected sources participate in archive guards, and submission pins their exact bytes.

Narration direction is applied through validated v3 audio-tag insertions. The approved
spoken words remain unchanged; requests retain both the original text and performance
cues. Voice selection uses stock voices, not a cloning operation. Episode assembly uses
actual selected outputs in scene order; it does not fabricate a rendered result.

Calls are billed to the configured provider accounts. Requests, responses, model IDs,
usage when returned, immutable source pins and real output files are retained. Dollar
cost remains unknown without actual billing evidence. Local app generation does not
invoke Codex CLI or an AI subscription harness. Existing cloud workers and the separate
comparison CLI retain their own documented transport/budget policies.

## Persistence and identity

The API binds to loopback only. Local SQLite identity and content are separate from the
hosted service; local sign-in cannot grant production access. Account security actions
require the live service. A new database stays empty until you create content or use
Development → Regenerate demo data. Demo regeneration is an explicit database write,
replaces only tagged fictional records and preserves user-created content.

Uploads, settings, characters, recordings, transcripts, generated assets and chapters
survive reloads and server restarts. GET routes never return hardcoded preview records.
Production does not expose local debugger/seed endpoints.

## Individual processors and recovery

For intentionally partial development, start the API and only the needed processors:

```sh
.venv/bin/python tools/dev_server.py --port 8766
.venv/bin/python tools/dev_editorial_worker.py \
  --database ~/.local/state/panther/development.sqlite \
  --work-dir ~/.local/state/panther/editorial \
  --env-file .env --model gpt-5-mini
```

Other processors accept the same database/work-directory arguments. API-backed
processors accept `--env-file`; playback and episode assembly require no provider key.
`--once` processes the current queue and exits. Missing processors are reported honestly.

Playback verifies a completed recording manifest and every original WAV before building
a continuous MP3 and source-linked manifest. Assembly belongs to workers, not browser
or server upload handlers. Originals and capture warnings remain available.

Authentication errors identify the key/project setting to fix. Rate/quota errors identify
provider limits. Unknown submissions remain blocked rather than automatically paying for
another request. Acknowledged fal request IDs can be polled again without submitting a
new video. Stopping during a paid call may leave an unknown outcome; inspect retained
responses/provider history before an explicit retry. **Do not kill an in-flight worker
just to reload code.** Let its active request finish, then restart it safely.

Completed retained API responses may be revalidated offline after a deterministic guard
repair only against the exact original model, schema and stage inputs. Original instructions,
request/response bytes, hashes and audit history remain preserved; this is not a response
to a changed prompt and never submits another paid request.

Local development changes do not deploy cloud infrastructure, move production data or
implicitly authorize automatic session-video rendering.

Completed narration audio has a separate provider-completion checkpoint and checksum. If the
worker stops after that checkpoint, it can validate and publish the retained MP3 on restart
without another ElevenLabs request. An unacknowledged request remains unknown and is never
repeated automatically. Narration, transcription and summary publication checks the current
job and immutable source bytes again inside the database transaction; a concurrent cancellation
or changed request cannot be overwritten by a late provider response. A summary queue failure
does not change a successfully published transcript into a failed transcription.
