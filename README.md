# Panther

Panther is a private workspace for tabletop roleplaying games: record sessions, edit characters,
organize assets, and adapt game material into novel chapters and episodic videos.

The app is available at [panther.place](https://panther.place). Game content and private account
data stay outside this repository. The CLI uses the same Panther authentication as the website;
normal game operations do not require AWS credentials.

## The app

Choose the current game in the header. Its sections are:

- **Dashboard:** links to each section and recent characters, transcripts, chapters, videos and assets.
- **Characters:** editable profiles, reference media, selected appearances, with revisions retained in the background.
- **Sessions:** browser recording, continuous playback and transcript browsing in one section.
  Previous Audio and Transcripts routes lead here. Transcript details open separately from the list.
- **Novel:** generate a chapter from a prompt with optional transcript/context inputs, or write and
  edit chapters manually. Source reviews preserve raw speech separately from summaries/adaptations.
- **Videos:** searchable multi-tag and multi-character filters use removable selections. Episodes own ordered scenes. A scene can start with a title, use characters and optional
  sources, and specify a scene type. Episode/scene forms open in dialogs; a focused editor keeps
  ordered scenes beside the selected scene’s prompt, cast and output choices. Playback opens in its
  own dialog. Map scenes select an actual map asset. An episode's playback
  follows its selected rendered scene outputs in order; drafting or planning does not imply footage
  has been generated.
- **Assets:** browse and search game assets, filter by type, identify file formats, upload files and request image generation. Jobs show activity or an explicit worker/configuration problem.
- **Workflows:** inspect reported server/laptop job stages, dependencies and output links. Progress
  updates automatically; queued work is distinct from a running worker or completed output.
- **Settings:** edit the game's name, description, system and visual defaults. Account settings have
  their own page.

The frontend combines the existing application shell with React components, Radix controls,
Tailwind 4, TanStack Query for cached server state and TanStack Table for the media browser.
Generation requests are durable jobs. Available controls do not guarantee that a worker is running
or authorize paid rendering; progress and output links must reflect actual stored results.

Recordings, raw recognition, corrections and adaptations remain distinct. Derived assets retain
exact immutable inputs and generation metadata. Character appearances use explicit character links;
creative adaptations do not become evidence for subsequent transcript correction.

## Local development

Install Python and frontend dependencies, build the React components, then start the local server:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
npm ci --prefix web/ui
npm run build --prefix web/ui
.venv/bin/python tools/dev_server.py
```

Open [127.0.0.1:8765](http://127.0.0.1:8765). The SQLite database defaults to
`~/.local/state/panther/development.sqlite`; `--database` selects another private file outside Git.
Application reads use persistent database state, not static preview fixtures. An empty database
stays empty until you create data or explicitly use Development → Regenerate demo data (`--seed`
at startup). Demo regeneration preserves user-created content and uploads.

For real continuous playback of browser recordings, install FFmpeg (`ffmpeg` and `ffprobe`) and
start the separate local worker in another terminal:

```sh
.venv/bin/python tools/dev_playback_worker.py \
  --database ~/.local/state/panther/development.sqlite \
  --work-dir ~/.local/state/panther/playback
```

The worker verifies explicitly completed WAV sets, preserves originals, creates a continuous MP3,
and publishes its source-linked manifest into the same database. `--once` drains current queued
work and exits. Queue failures retain the source audio and a reason; existing bytes are never
replaced. Its heartbeat lets the app distinguish a waiting job from available processing.

Local development does not configure OpenAI transcription, image generation, transcript-summary
inference or editorial workers. Requests can be persisted or report that generation is unavailable;
they never return invented transcripts, images or completed manuscripts. The local identity and
SQLite data are separate from hosted authentication and game data. Production generation runs
through authenticated, subscription-backed laptop workflows. Browser transcription requires an
explicit server-side OpenAI secret; paid video/narration needs separate approval.

## Verification and operations

Run focused Python tests with `.venv/bin/pytest` and React component tests with
`npm test --prefix web/ui`. Frontend changes also require isolated desktop/mobile Playwright checks
on the repository's self-hosted Docker runner. See [runner setup](docs/self-hosted-runner.md) and
[repository instructions](AGENTS.md) for the readiness gate.

AWS infrastructure is defined in CDK, with near-zero idle compute cost as a standing goal.
Administrative deployment uses short-lived credentials; game files, private inventories,
work directories and database files must remain outside Git. Changes ship through reviewed branches
and pull requests, with current-commit checks and the owner's merge policy.

## Documentation

- [Persistent local development](docs/local-development.md)
- [CLI setup and usage](docs/cli.md) — agents should also run `panther instructions`
- [Browser recording](docs/browser-recording.md)
- [Continuous recording playback](docs/recording-playback-workflow.md)
- [Local recording and player attribution](docs/local-audio.md)
- [Editorial workflows](docs/editorial-workflows.md)
- [Video production and delivery](docs/video-production.md)
- [Asset browsing](docs/asset-browse-index.md), [storage](docs/asset-storage.md),
  [versions](docs/asset-versions.md) and [generation metadata](docs/generation-metadata.md)
- [AWS foundation runbook](docs/aws-foundation-runbook.md)

Earlier mock-pipeline commands remain in the Python package for isolated development. They do not
supply the app's database or define its current functionality.
