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
no OpenAI secret or paid provider call is made. Editorial and playback submissions
remain pending without an attached real worker; the server never invents transcripts,
derivatives or LLM results. Real cloud jobs continue through the authenticated APIs
and subscription-backed laptop workers. Production configuration does not expose
the Development section or seed endpoint.

The browser and API use database state; the only preset data is the explicit seed
operation. Tests use separate temporary databases and fictional identities.
