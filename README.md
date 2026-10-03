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
  edit chapters manually. Compact transcript selections expand one concise summary at a time; raw speech
  remains separate from adaptations.
- **Episodes:** `/games/:gameId/episodes` searches episodes only. Episodes own ordered scenes. A scene can
  start with a title, use characters and optional
  sources, and specify a scene type. Episode/scene forms open in dialogs; a focused editor keeps
  ordered scenes beside the selected scene’s prompt, cast and output choices. Playback opens in its
  own dialog. Map scenes select an actual map asset. An episode's playback
  follows its selected rendered scene outputs in order; drafting or planning does not imply footage
  has been generated.
- **Assets:** browse individual videos, portraits and other game assets; search and filter by type, tags and
  characters with selections contained inside the controls. Identify file formats, upload files and request
  image generation. Jobs show activity or an explicit worker/configuration problem.
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

Install Python/frontend dependencies and FFmpeg, then start the complete stack:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
npm ci --prefix web/ui
cp .env.example .env
chmod 600 .env
# Fill OPENAI_API_KEY, FAL_API_KEY and ELEVENLABS_API_KEY in .env.
.venv/bin/python tools/dev.py
```

Open [127.0.0.1:8766](http://127.0.0.1:8766). The launcher builds React, checks local
requirements, starts the API and nine processors, and waits for fresh processor
heartbeats before exposing the app. Logs/checkpoints and SQLite data live outside Git.
See [local setup](docs/local-development.md) for individual workers, model settings and recovery.

Local creation uses direct provider APIs: OpenAI for chapters, summaries, transcription,
images and prompt composition; fal for scene videos; ElevenLabs v3 for narration.
Episodes assemble the selected scene videos locally with FFmpeg. Generation records
actual outputs, immutable inputs, provider responses and honest failures. Unknown paid
outcomes are never automatically submitted again. There is no AI CLI harness or dummy
successful output in this local stack.

The database defaults to `~/.local/state/panther/development.sqlite`; application reads
use persisted data. Development → Regenerate demo data explicitly writes fictional
records while preserving user-created content. Local identity/data remain separate
from production. Cloud workers retain their existing transport until explicitly migrated.

The React UI uses standard shadcn/ui registry components (Radix, Command and shared
buttons/inputs) with Tailwind CSS 4 and TanStack Query. Keep application-specific forms
and data handling in compositions of those components; widget focus, keyboard behavior
and popup positioning belong to the underlying libraries.
Radix DismissableLayer 1.1.19 receives a minimal, reproducible event-time Escape guard
from [upstream fix #4147](https://github.com/radix-ui/primitives/pull/4147) for
[nested-dialog regression #4143](https://github.com/radix-ui/primitives/issues/4143).
`npm ci --prefix web/ui` applies the version-specific patch only after verifying
both upstream file checksums, and fails if the version or sources have changed.
The build repeats this verification for existing installations. Remove the patch
after upgrading to a stable upstream fix, and rerun the
nested-dialog registration, keyboard/focus and body-portal Select regressions on
desktop and mobile.

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
