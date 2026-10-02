# Persistent local development

Build the UI with `npm ci --prefix web/ui` and `npm run build --prefix web/ui`, then run:

```sh
python3 tools/dev_server.py
```

The server binds only to `127.0.0.1:8765`. Its database lives outside Git at
`~/.local/state/panther/development.sqlite` (override with `--database`). No games,
characters or assets are silently supplied by GET routes. An empty database starts
at Account; Development → Regenerate demo data explicitly writes fictional
records. `--seed` invokes the same operation at startup. Regeneration replaces
only tagged demonstration records; user-created characters, uploaded originals
and chapters remain. The local UI uses the same cached reads and editing contracts
as the hosted app. Settings, profile, character history, chapters and audio persist
across page reloads and server restarts.

This is a development backend, separate from the hosted Panther database. Local
sign-in is an explicit development identity and cannot grant access to the hosted
service. Cognito security settings require the live service. Transcription is off;
no OpenAI secret or paid provider call is made. Editorial submissions
remain pending without an attached real worker; the server never invents transcripts,
derivatives or LLM results. Real cloud jobs continue through the authenticated APIs
and subscription-backed laptop workers. Production configuration does not expose
the Development section or seed endpoint.

The browser and API use database state; the only preset data is the explicit seed
operation. Tests use separate temporary databases and fictional identities.

## Local continuous recording playback

Run the separate development playback worker alongside the server, using the same
private SQLite database (the defaults match):

```sh
python3 tools/dev_playback_worker.py \
  --database ~/.local/state/panther/development.sqlite \
  --work-dir ~/.local/state/panther/playback
```

Install the project Python dependencies and FFmpeg (`ffmpeg` and `ffprobe`) first.
`--once` processes the current completed queue and exits. The worker advertises a
local heartbeat; the server can report whether processing is available. This is
not the authenticated production worker and requires no AWS credentials or API key.

Only explicit server-verified completed browser recordings enter the queue. The
worker verifies the pinned manifest and every original WAV, uses the existing
protocol-2 playback assembler, then publishes a real continuous MP3 and its typed
manifest in one SQLite transaction. It preserves the originals, exact source links,
capture warnings and creation metadata. It validates the shared organized-storage
contract; the local database indexes stable asset references rather than S3 paths.
Working checkpoints stay outside Git and are verified on resume; existing content
is never overwritten. Queue states are `QUEUED`, `PROCESSING`, `DONE` or `FAILED`.
Failures retain the original audio and a visible reason; they are not automatically
retried. A stopped worker leaves queued work pending until it is started again.
