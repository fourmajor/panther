# Panther pipeline status

Survey of the pipeline as it exists on this branch. Game recordings and account data stay outside Git. This environment has no AWS credentials and no `.env` provider keys, so nothing here was read from the live account.

## Where a session recording lives

Two capture paths share one session id (`sessionId`, a lowercase slug, max 96 characters) and one recording id (`recording-` plus 32 hex characters).

| Path | Capture | Local copy | Upload |
| --- | --- | --- | --- |
| Table microphone | `panther recording start --game --session --device`, optional `--tui` (Stop & save is S / Ctrl+C). Native macOS recorder. | `~/Library/Application Support/Panther/recordings/<game>/<session>/recording-<id>/` as contiguous FLAC parts, default 30 seconds, plus `recording.json`. | `panther recording sync` or `upload` after Panther login. Not an AWS CLI upload. |
| Browser room | Sessions → Record. Mono 32 kHz 16-bit WAV, about 15 seconds per part, kept in IndexedDB until backup. | Same browser profile until upload. | Authenticated create-only PUT of each part, then `POST /browser-recording/complete`. |

`panther recording upload` sends each part, `recording.json`, and optional `capture-health.json` through the Panther API. The stable asset reference is:

`games/<game-id>/assets/<recording-id>/original/<filename>`

That reference is not the physical S3 key. Layout version 2 (`infra/lambda/media-api/storage_layout.py`) places bytes in the private bucket at:

`games/<game-id>/content/sessions/<session-id>/audio/source/<recording-id>/<filename>`

Manifests, listening copies, raw transcripts, corrected transcripts, chapters, and workflow intermediates use the sibling collections in [docs/asset-storage.md](docs/asset-storage.md). The API reserves the catalog entry and signs the PUT. Callers cannot choose a bucket path.

The bucket name is not hardcoded. CDK writes it to SSM `/panther/foundation/private-asset-bucket` (published media is `/panther/foundation/published-asset-bucket`). Account `223663280572`, region `us-west-2`. Upload role: `PantherAssetUploader` (profile `panther-uploader`). Admin: `PantherAdministrator` (`panther-admin` / `panther-sso-admin`).

Completing a verified chunk set inserts a `RecordingChunkSet` and starts the playback Step Functions execution. It does not wait for a quiet period. Originals are never overwritten.

## Stage map

Status below is the code that exists, not a claim that a live session has been run from this machine.

| Stage | Inputs | Outputs | Code | AWS | State |
| --- | --- | --- | --- | --- | --- |
| Session audio | Microphone, game id, session slug | FLAC or WAV parts + `recording.json` | `recording.py`, `recording_tui.py`, browser recorder in `web/media-explorer/app.js` | S3 private bucket via signed PUT. No capture compute in AWS. | Implemented. Needs the owner's mic and Panther login to reach S3. |
| Listening copy | Completed chunk set | One MP3 plus playback manifest | `recording_playback.py`, `tools/dev_playback_worker.py` | Standard Step Functions `PlaybackProcessing` waits up to 30 days for the laptop callback. Lambda broker. No cloud encoder. | Implemented. Laptop must be awake with ffmpeg. |
| Transcription | Original parts, not the MP3 | Raw transcript windows | Browser: `browser_transcription.py` (`gpt-transcribe`, live side channel `gpt-live-transcribe`). Laptop session worker: local Whisper. | SQS + Lambda, not Step Functions. Secret `browserTranscriptionSecretArn` in us-west-2. | Browser path needs the OpenAI secret. Laptop path needs local Whisper weights. |
| Speaker matching | Raw audio, enrolled profiles | Reconciled transcript; unknown speakers stay unknown | `session_worker.py` (`match-players`), pyannote on the laptop MPS device | No paid diarization service. Progress is a local report (`session-finalization`). | Needs the private worker config: model paths, profiles, `recordingsRoot`, `completedAfter`. |
| Raw transcript published | Verified transcript | Immutable raw transcript asset | `recording.py` upload, session worker `publish-transcripts` | S3 + catalog. No overwrite. | Implemented. |
| Context, cleanup, corrected transcript | Raw transcript, same-game evidence pinned by checksum | Corrected transcript. Raw text is never rewritten. | `editorial-plan.json` correction branch, `editorial.py` | Step Functions callback per stage. Laptop or `dev_editorial_worker.py` claims the task. DynamoDB job/task rows are the execution record the site reads. | Implemented. Cloud workers are subscription-backed Codex; local worker is OpenAI Responses (`PANTHER_EDITORIAL_MODEL`, default `gpt-5-mini`). |
| Novel branch | Corrected transcript | Brief → approaches and voice bible → beats → draft → edits → proof → **novel chapter** | Plan `novel` list. Reader uses the JSON chapter, not the Markdown notes. | Same editorial state machine, parallel branch. | Implemented through the chapter. Illustrations are still issue #52. |
| Screen branch | Corrected transcript | Treatment through storyboards, generation packets, preflight | Plan `video` list. Storyboards are schematic SVGs, not concept art. | Same state machine. Terminal state `READY_FOR_VIDEO_DISCUSSION` / succeed state `VideoGenerationNotAuthorized`. | Planning is implemented. Paid render is intentionally not in this state machine. |
| Storyboard approval | Exact plan revision | Permission for one session's paid render, $10 ceiling | `docs/session-automation.md`, `panther video` | Not a Step Functions state. Owner approval is required. | Blocked until Stu approves a specific storyboard. |
| Still images | Game `visualStyle`, character references | Portraits, maps, plates | `dev_image_worker.py`, asset generation | Local OpenAI Images or fal. Not an automatic editorial state. | Runs only when a job is submitted and a key is configured. |
| Narration | Approved words plus performance direction | ElevenLabs v3 audio via fal | `narration.py`, `dev_narration_worker.py` | Local worker. No cloning, no system TTS. | Separate from the session state machine. Needs `FAL_API_KEY` and `ELEVENLABS_API_KEY`. |
| Video generation | Approved packets | Shot media | `video.py`, `dev_video_worker.py` | Audio-first (plan 14): Seedance 2.5 for on-screen dialogue, MiniMax H3 Max for the rest; `tools/ai-video` for session cuts. Veo removed. | Not started by recording completion. |
| Sound and delivery | Selected takes, real stems if they exist | 1280×720 24 fps browser MP4, master, captions | `video_production.py` on the laptop | Local ffmpeg. Checkpoints are reported; AWS does not encode. | Needs actual shot media. |
| Session video | Finished delivery | Episode/master the browser can play | `dev_episode_worker.py` for ordered scene outputs; production delivery for the laptop film | Assembly is local. | Cannot be completed without the paid shots or already rendered scene outputs. |

The editorial state machine is built in `infra/lib/editorial-processing.ts` from `editorial-plan.json` version 11: context, then correction, then a parallel novel branch and video branch. Each stage is a Lambda callback (`WAIT_FOR_TASK_TOKEN`) lasting up to 30 days. There is no ECS or Batch stage. Playback and 3D model jobs have their own small Standard state machines (`playback-processing.ts`, `model-processing.ts`). Recovery of a failed run reuses parent stages whose artifacts still validate, and dispatches those stages as already done.

The Pipeline page reads those job and task records (local SQLite, or the workflow index projected from the DynamoDB job tables). It does not call `states:DescribeExecution`. The workshop reader is deliberately not allowed to read Step Functions. Task status is the callback result the state machine is waiting on.

## Style already chosen

Do not invent a look or a voice for a session.

- Visual style is per game (`visualStyle`), default `photorealistic` for new games. Presets and prompt text are in `infra/lambda/media-api/visual_styles.py`. Generation must use the saved game style. Identity references do not override it.
- Novel voice is chosen inside each run by the `novel-options` stage (an original voice bible, no imitation of a living writer). There is no fixed chapter length.
- Narration is ElevenLabs Eleven v3 through fal, stock voices only. Trailer reads are paced, not neutral. Recording consent is not cloning consent.
- First-cut video is `h3-max-image` for every shot: H3 Max, audio on, 768P (480P is an option), one take of 2–7 seconds. A full session cut is 14–16 shots, targeting 60–80 seconds and staying within 60–90. A scene cut stays at most 16 shots and 90 seconds. A failed review is kept and flagged. Start frames are `gpt-image-2` medium or a Blender render. The plan stores the estimate; the session budget is `panther narration allocate`. This is not spending approval.
- Browser delivery that already exists is a 1280×720, 24 fps MP4.

## Providers, keys, hardware

From `.env.example`, server-side only: `OPENAI_API_KEY`, `FAL_API_KEY`, `ELEVENLABS_API_KEY`. The editorial worker uses no model key: Grok Bot answers its requests through files.

Laptop session finalization also needs local Whisper weights, pyannote model and runtime, enrolled speaker profiles, ffmpeg/ffprobe, and a signed-in Panther CLI. Browser transcription needs the us-west-2 Secrets Manager ARN deployed on the media stack. Native recording needs macOS and a named input device.

## What has to be run on Stu's machine

This agent cannot log in. From a machine that already has the SSO profiles:

```sh
aws sso login --profile panther-admin
aws ssm get-parameter --profile panther-admin --region us-west-2 \
  --name /panther/foundation/private-asset-bucket --query Parameter.Value --output text
# Then, read-only, with the uploader profile after its own sso login:
aws s3 ls --profile panther-uploader --region us-west-2 \
  "s3://BUCKET/games/"
panther workflows list --game GAME
```

That lists whether a real recording and its editorial execution exist. It does not grant this environment access. Paid video still waits for approval of the exact storyboard.

## Open issues

Eleven open issues, not thirteen: #209 transcript selection storage, #206 durable movie delivery, #122 Jev experiments, #85 billing-console access, #83 member/admin roles, #78 character animations, #52 chapter illustrations, #35 Blender characters, #34 Google sign-in, #21 self-service passwords, #9 budget alerts. None of them replace the session pipeline above.

## Editorial worker

Since 2026-11-16 the editorial worker runs on Grok Bot's box and makes no LLM calls. Each AI call
becomes a request folder that a Grok Bot routine answers (`ops/editorial-worker/grok-bot.sh`, then
`panther editorial agent-answer`). Claude, Codex and the xAI API are no longer editorial backends,
and the Mac LaunchAgent installer was removed. See
[Grok Bot handoff](docs/editorial-workflows.md#grok-bot-handoff).

A Mac that still has the old `place.panther.editorial-worker` LaunchAgent loaded should have it
stopped with `launchctl bootout gui/$(id -u)/place.panther.editorial-worker`; with no Claude login
it can only fail stages. Only one worker should claim stages.

Corrected-transcript review that does not fit the prompt limit runs in utterance windows and merges all of them. A deterministic preflight error is stored on the DynamoDB task and shown on the failed Pipeline step. It is not claimed three times.

If an editorial run is `FAILED`, replay it from the pinned inputs with the full job id shown in Workshop:

```sh
panther editorial recover --job-id FULL_JOB_ID --target both
```

Recovery starts a new execution. It does not rewrite the failed run.

## Pipeline page

The signed-in home at `/` opens `/games/<game>/pipeline`. The page lists sessions. Each card shows the session name or date, an overall status, the furthest stage reached or the failed stage, and a chip for each final artifact. Gray is not started. Green is success. Red with an X is failure. Opening a session shows the one branching graph from the recording to every final artifact. Shared, Novel, and Video are labeled lanes inside that graph, and each lane header shows that lane's status. Novel chapter and session video are the finals; another artifact is another lane. A session with more than one run, such as a recovery, has a run picker with the run id and start time. The latest run is selected, and stages it reused stay done. In the graph, blue and animated is running, and storyboard approval stays a waiting gate. A recorded error opens on click. Editorial, playback, and model each show a status pill. An offline warning appears only for a worker a pending stage in the open graph is ready to use. An empty game shows no sessions.
