# Raw transcript → corrected transcript → adaptations

Panther keeps raw speech recognition, contextual corrections, and creative adaptations distinct.
The raw transcript is never rewritten. Corrections retain player identity, timestamps, every
utterance (including table chatter), the original text, evidence citations, and unresolved questions.
They are **AI-reviewed, not human-verified**. Context is not permission to invent missing speech.
Novel chapters are grounded adaptations; screen adaptations are creative reimaginings. Neither
becomes campaign canon or evidence for later transcript correction.

## Completion and automatic trigger

`recording transcribe` now saves the raw output first, then publishes and commits it by default.
Use `--local-only` for intentionally offline processing or a held-out test that must remain local.
`--blind` still isolates the recognizer from context and reference scripts; correction happens later.
If upload/commit fails, local raw outputs remain intact. Resume with `recording upload`, not another
recognition run. Publishing is a completed-artifact commit, not an event on each partial file write.

```sh
panther recording transcribe RECORDING_DIR --model MODEL_PATH --sole-player PLAYER_ID --blind
panther recording upload RECORDING_DIR --transcript RAW_TRANSCRIPT_DIR
panther editorial submit --game GAME_ID --raw-key EXISTING_RAW_JSON_KEY
panther editorial jobs
panther editorial jobs --job-id JOB_ID
```

The upload command automatically submits raw transcripts unless `--no-editorial` is given.
Legacy raw PlayerTranscript JSON is accepted without modifying its existing object. The same exact
input and workflow version produce the same run ID. Arbitrary file uploads do not start jobs until
committed through `editorial submit`; derived outputs cannot recursively trigger a new pipeline.
Future workflows require a new version instead of silently changing an execution's definition.

## Process and artifacts

Separately generated speech follows the owner's premium narration policy: ElevenLabs Eleven
v3 through fal, no Chatterbox or system-TTS fallback. Casting and performance direction are
still subscription-backed planning; the separately approved local
[narration workflow](narration-workflow.md) owns paid auditions and synthesis. Neither this
policy nor an editorial completion event authorizes spending. A storyboard preview is a
readable image-and-text review, with a separate audition, not a narrated slideshow.

The versioned plan is bundled in the CLI and used by CDK. Every row below is one or more named
Step Functions callback states, not one giant prompt. Each stage gets a fresh AI session and saves
JSON provenance plus a readable Markdown artifact. Version 3 retains version 2’s bounded autonomous review and resolves routine editorial uncertainty
autonomously. Rejection triggers actual revision and fresh review, not a human approval request.
The corrected transcript then unlocks the two independent adaptation branches.

Each stage has at most three rounds. Transcript-review failures rerun the correction specialist
against the immutable raw text; chapter-review failures rerun the proof/revision specialist on the
actual manuscript. Each revised candidate is reviewed again. Generic stages revise their own output
using feedback. All outputs preserve a structured decision ledger and revision history. After three
rounds, a structurally valid working draft continues as `accepted-with-notes`, without pretending its
review `passed`. Transcript disagreement instead preserves raw wording, with explicit uncertainty.
Invalid structures, citations, or locked shot sequences cannot be accepted. They retry later when no
valid candidate exists. Credentials, subscription limits and infrastructure failures remain real
operational constraints, not editorial decisions. No routine ambiguity requires owner approval.

`publicationStatus` is distinct from the review's honest `passed` result. Every artifact remains
AI-reviewed/unverified, never automatically canonical. Readers can request corrections later; retain
the originals and publish new versions. Version-aware leases keep old workers from claiming new jobs.
Resubmit the same raw key after a workflow-version upgrade to create a separate run while preserving
the old execution and artifacts. Previously failed v1 runs are not silently mutated or restarted.

| Branch | Ordered artifacts |
| --- | --- |
| Correction | Context-selection report and pinned evidence → minimal correction proposals → independent audit and corrected transcript |
| Novel | Editorial brief → alternative approaches and voice bible → outline/scene beats → full draft → developmental critique → full revision → continuity/style audit → line/copyedit and style sheet → digital reading proof → final chapter and independent review |
| Screen | Treatment → screenplay → script critique → revised numbered shooting script → production breakdown → design/cinematography bible → reference-asset registry → voice casting → blocking/coverage → shot list → schematic storyboards and timed animatic plan → AI generation packets → edit/sound/VFX plan → schedule/dependencies/budget worksheet/postproduction plan → independent preflight |

Video's final state is `READY_FOR_VIDEO_DISCUSSION`. The automated editorial pipeline has **no video
generation state, payment path, image-generation tool, voice clone, or mechanism to approve spending**. Provider,
model, reference generation, rights, voice/music permissions and spend cap must be discussed first.
Passing preflight means a planning package is ready to review, not permission to produce it.
The separate, explicitly gated local `panther video` fal comparison CLI is documented in
[fal-video-comparison.md](fal-video-comparison.md). It does not change this workflow definition,
auto-submit preproduction packets, or replace subscription-backed planning with paid inference.

### Video model selection policy

Owner-selected on 2026-09-10, based on the reviewed comparison clips. Use **Veo 3.1 Fast through
fal by default**, explicitly including city/urban establishing shots. Use **MiniMax H3 Max
(not Turbo) through fal for dialogue**, and **Kling 3 Pro through fal for battle/action shots**.
H3 Max supersedes the earlier Veo dialogue preference. These are production preferences, not
universal quality claims.

Apply the choice per shot: action in a city still uses Kling; a dialogue close-up between combat
beats uses H3 Max, including dialogue in a city. For an inseparable mixed shot, use Kling when
battle/action drives the shot, H3 Max when dialogue drives it, otherwise Veo. Record the selected
model and rationale in the production plan. New model versions,
comparison experiments and deliberate exceptions require an explicit owner choice; do not silently
substitute another model on failure.

This policy guides agents preparing executable video plans after preproduction. The existing
automated editorial stages remain provider-neutral and stop at `READY_FOR_VIDEO_DISCUSSION`;
this documentation change does not add an automatic router or alter an in-flight workflow.
Use the exact CLI profiles in [fal-video-comparison.md](fal-video-comparison.md#production-model-selection).
Model preference is not spending or reference-sharing approval: all existing plan approval,
rights/consent checks, attempt limits and lifetime budget safeguards still apply. Preserve historical
comparison plans and their actual model provenance; do not relabel or regenerate older clips.

Storyboards are real, safe SVG blocking diagrams derived from structured shot positions and colors,
not finished concept illustrations. The animatic is a timed shot manifest, not a rendered film.
Missing character/environment plates are documented dependencies with preparation instructions,
never fabricated existing assets. Actual footage, performances, VFX, sound mix, grading and delivery
QC depend on generated material and are planned here, not falsely reported as completed.

Once selected footage exists, the separate [local production workflow](video-production.md) now
executes continuity review, bounded edit/grade and re-review, independent sound-stem assembly,
mixing, captions, master/browser delivery and final sequence checks. Its explicitly completed
production manifest is a different trigger from transcript completion. Shot preparation validates
selected appearance references and full starting/optional supported ending plates, emitting only
an unapproved generation manifest. This does not change the editorial Step Function, submit paid
requests or manufacture missing imagery, consent or audio stems.

Voice casting produces versioned `VoiceProfileProposal` records linked separately to Player and
Character IDs. The plan describes performance, pronunciation, enrollment samples, consent/rights,
revocation, continuity and lip-sync requirements, with an independent narrator. Real-player cloning
requires that player's explicit scoped permission; permission to record game night is not permission
to clone a voice. Character voices can be original designs without impersonating their players.
Proposals start with no samples, no consent evidence, no provider/model reference and generation
disabled. They are not trained voice models or an assertion that a provider will permit a given use.
Actual enrollment, training, storage/security and synthesis await the provider/budget/consent discussion.
Provider restrictions need checking as well as consent: for example,
[ElevenLabs Professional Voice Cloning](https://elevenlabs.io/docs/eleven-creative/voices/voice-cloning/professional-voice-cloning)
requires the voice owner to create and verify their own clone. This is a constraint example, not a
provider choice. Keep enrollment recordings private and separate from ordinary game-night audio.

## Evidence and growing metadata

### Reading novels in Panther

Open **Novel** after choosing a game, or use `/games/GAME_ID/novel`. Completed
`novel-chapter` stages appear automatically, even while the independent video branch is still
running. The source-editions list shows one chapter per source session, using the newest run's
completed edition. This source list is not an approved book order. Stories, books and volumes have
explicit revisioned organization and immutable edition selections; see `novel-library.md`.
Each source edition has a stable URL at
`/games/GAME_ID/novel/JOB_ID`. Details links to earlier editions without overwriting assets.

The reader uses the checksummed JSON artifact's `payload.chapter`, **not** the older Markdown
export that mixed in editorial notes. Title and prose are shown in Read; review notes, uncertainty,
source artifacts, AI-review status and full revision history live in the separate Details view.
Test-game and working-draft notices sit outside the manuscript. The exact legacy microphone-test
notice is relocated outside the prose; arbitrary story headings are never used to truncate text.
Story downloads contain only the title and manuscript. New worker exports no longer append review
notes to novel Markdown; existing JSON and Markdown objects remain unchanged. A pinned worker
must be upgraded using the installer below to adopt exporter changes; the web reader works with
existing artifacts immediately, without upgrading or rerunning a job.

`GET /novel?gameId=...` returns bounded, cursor-paginated chapter summaries. The browser collects
pages before ordering editions. `GET /novel-chapter?gameId=...&chapterId=...` returns the manuscript
and separate details. Both require Cognito JWTs and the existing owner/DM group policy. Player
memberships remain game roles, not authorization grants; this is not multi-group tenancy.
The dedicated CDK-managed Lambda can only read the existing editorial table and private assets.
It validates game/run identity and pinned checksum/size before displaying content. No new database,
scheduled polling, workflow mutation or always-on compute is introduced. The initial renderer
supports prose paragraphs, headings, emphasis, quotations and scene breaks, and treats HTML,
images and arbitrary Markdown links as inert text. Known character names and unique asset titles
receive subtle internal navigation links; optional typed `payload.readerReferences` can disambiguate
aliases without changing prose. See [asset-library.md](asset-library.md) for the versioned contract
and limitations. These are reader projections, not changes to the editorial stage plan or evidence.
Generated illustrations are deferred to
[issue #52](https://github.com/fourmajor/panther/issues/52).

The broader library enhancements (book/volume organization, saved reading progress and richer
publication metadata) remain tracked in [issue #17](https://github.com/fourmajor/panther/issues/17).

### Context selection

The worker reads the structured game catalog and asks AI to select relevant same-game source assets
from their metadata. Eligible text sources include previous corrected transcripts, character/lore
records, `lore`, `game-context`, `character-profile`, `corrected-transcript`, and sources explicitly
marked `extra.contextUse: creative-evidence`. Generic reference categories alone are insufficient;
structured provenance, migration, audit and verification artifacts are excluded. Use `extra.contextUse: exclude` for a held-out script; never upload
the script for a blind test at all. Known script/holdout kinds and adaptation categories are excluded.
All source content is untrusted data, never executable instructions. No credentials enter prompts.

The raw object's upload time is the asset-context cutoff: later assets do not quietly alter a run.
The current game catalog is snapshotted at context-stage execution, so its snapshot time can be later
than the recording. This is not historical character-state resolution; conflicts must remain explicit.
Selected assets are pinned by key, byte length and SHA-256. All evidence and selection decisions are
saved; every correction must cite selected evidence. This first retrieval implementation supports
500 eligible candidates, up to 12 selected text assets of 256 KiB each, and a 900 KB prompt limit.
It fails visibly at limits rather than silently forgetting context. Large-campaign indexing, semantic
search, binary-document extraction and historical appearance/knowledge timelines are future adapters.
Previous AI corrections are fallible context, not automatically authoritative canon.

Corrections cannot change player IDs/times, numeric tokens, negation or source structure. These
deterministic guards complement an independent AI review; neither guarantees semantic accuracy.
Potentially ambiguous speech stays as recorded with uncertainty notes. The capture-integrity report
travels with newly generated raw transcripts. Legacy raw records may lack it and are not presumed
loss-free. The test campaign's invented scene must remain test material in every adaptation.

## Professional and AI-specific research

There is no single mandatory writing formula. The implemented sequence is Panther's synthesis of
professional practice, not certification that an AI produces publishable work.

- [Penguin's writing guidance](https://www.penguin.co.uk/discover/articles/how-to-start-writing-a-book)
  supports deliberate structure, pacing, character development and a distinctive voice. Panther makes
  those decisions explicit before drafting rather than asking only for a generic recap.
- [CIEP's editorial workflow](https://www.ciep.uk/resource/about-proofreading-and-editing.html)
  distinguishes developmental editing, copyediting and final proofing. Panther separates these roles;
  its Markdown proof is not a substitute for checking a future typeset print edition.
- [FilmSkills' professional directing curriculum](https://www.filmskills.com/new-directors-craft-lessons/)
  covers script breakdown, dramatic blocking, coverage, storyboards, shot lists and continuity.
  Panther translates those disciplines into provider-neutral scene/shot artifacts, then adds sound,
  VFX, schedule, budget and postproduction planning. Physical production roles cannot literally be
  performed by a text workflow before footage exists.
- [Research with 13 professional writers](https://arxiv.org/abs/2211.05030) found useful AI support for
  ideation and details but weaknesses in voice and story understanding. This older study is not a
  benchmark of today's models. It motivates alternative approaches, a voice bible, focused revisions
  and explicit continuity review—not a claim that self-critique solves creative quality.
- [Research on creative writers' AI practices](https://arxiv.org/abs/2411.03137) studies how writers
  integrate assistance into their process. Panther makes each intervention inspectable and keeps
  authorial choices and revisions separate instead of flattening everything into an opaque rewrite.
- [Runway's long-form filmmaking guidance](https://help.runwayml.com/hc/en-us/articles/26871350018835-How-to-create-longer-videos-and-films)
  advocates shot-based assembly and consistent character/environment references. Panther therefore
  plans reusable plates, appearance-state bundles, stable shot IDs and an edit timeline. This source
  informs preparation; it does not choose Runway or authorize using its paid services.
- [Runway's prompting guidance](https://academy.runwayml.com/guides/prompting-guide) distinguishes
  visual specification from motion direction and recommends concrete, non-conflicting, iterative
  prompts. Generation packets separate visual and motion instructions, define acceptance tests and
  bounded attempts, and leave provider-dependent settings unknown until capability checks.

Each AI stage is fresh, structured and least-privilege, following
[Codex non-interactive documentation](https://learn.chatgpt.com/docs/non-interactive-mode).
The autonomous revision prompts also apply [OpenAI's model guidance](https://developers.openai.com/api/docs/guides/latest-model)
on explicit initiative and concrete verification. Panther enforces bounded loops and source guards
in code; prompting alone is not a guarantee of correctness.
Shell, apps, web, multi-agent and image tools are disabled. Trusted Python performs downloads,
validation and uploads. Codex uses the existing ChatGPT login, never API keys or a paid fallback.
AI inference still occurs at OpenAI under the subscription; the worker and artifact processing are
on the laptop. Independent AI sessions can share biases; automatic review is not human endorsement.

## Operations

AWS CDK creates retained on-demand DynamoDB jobs, a durable stream outbox, short-lived Lambda brokers,
and a Standard Step Functions state machine in `us-west-2`. Each AI stage queues and
[waits for a callback](https://docs.aws.amazon.com/step-functions/latest/dg/connect-to-resource.html).
Callback tokens never leave AWS. Only the owner worker can claim jobs; owner and DM can submit/inspect.
Leases last ten minutes with one-minute heartbeats. Subscription pauses defer one hour without spending
crash attempts. Three abandoned attempts fail a stage. Waiting expires after 30 days; outbox records
have DynamoDB Streams' 24-hour delivery window, so prolonged delivery failures need operator recovery.
No NAT, EC2, hosted runner, provisioned database or paid AI service is created.

```sh
panther editorial worker --work-dir /private/path/editorial-jobs --once
```

Without `--once`, it drains available stages while awake and polls once a minute when idle. Polling
uses a small amount of API/database activity; stop it for literally no idle polls. Sleeping laptops
delay work, not lose it. Actual artifacts remain outside Git in existing immutable asset storage.
Each run/attempt has unique paths; raw files, earlier outputs and failed candidates are retained.

Install the automatic owner-scoped worker only from clean, fetched, reviewed merged main:

```sh
.venv/bin/python ops/editorial-worker/install.py --repo "$PWD" --start
```

It snapshots the commit and installs a non-editable CLI under the private editorial-worker directory.
The user LaunchAgent `place.panther.editorial-worker` processes one stage per minute while awake.
It never mounts/copies AWS or Codex credentials. Inspect with `launchctl print gui/$(id -u)/place.panther.editorial-worker`;
stop with `launchctl bootout gui/$(id -u)/place.panther.editorial-worker`. Upgrades refuse to silently
replace a loaded service or existing release. Preserve prior releases/logs when explicitly upgrading.

Browser room transcription produces an unreviewed `BrowserTranscript`, with unassigned speakers
and window-boundary timestamps. It can be selected explicitly for editorial creation. Preserve its raw evidence, capture
warnings and unassigned speaker identities; never invent player attribution. Later player
identification belongs in a separate annotated version. See [browser recording](browser-recording.md).

## Browser creation requests (workflow 3)

Novel’s **Generate chapter** and Videos’ **Create video project** select one to eight completed
raw PlayerTranscript or final BrowserTranscript assets, optional same-game text context, a title
and an editorial direction. Requests pin every input checksum and size in the immutable job.
Changing the direction or selected source order creates a separate execution; retrying the exact
request returns the same execution. The broker rejects provisional/live transcripts, foreign-game
assets, duplicate selections, excluded hold-out material and adaptation artifacts as context.
A selected bundle is bounded to 512 KiB so it fits the subscription worker’s prompt limits.

The worker’s read-time multi-source bundle preserves source-local times, player IDs (including
unassigned speakers), capture warnings, original documents and each segment’s source key/index.
It does not assert a shared clock or rewrite any raw asset. Every output links all selected raw
inputs; structured references retain exact immutable pins. Context-selection still obtains an
independent review, and explicitly selected eligible context remains included in later stages.

Creation requests run correction followed by only the requested novel or screen-planning branch.
Legacy CLI submissions retain both branches. Screen planning produces story, screenplay, shot
list, schematic storyboards, generation packets and preflight; it never submits paid clips.
The browser shows real leased stage progress and completed storyboard output. A new version 3
worker must be installed before these jobs progress. Existing version 2 jobs and assets remain
unchanged and retain their original worker protocol; never relabel old artifacts as version 3.

Editorial context browsing queries the versioned materialized catalog in bounded pages. An
unprepared catalog fails explicitly; there is no source-storage scan fallback. This change
creates a new execution protocol, not a new asset kind or a rewrite of historical manuscripts.

`GET /editorial-jobs?gameId=...` returns a bounded page of same-game executions with an opaque,
game-scoped cursor; the browser keeps earlier creation projects accessible after reload. Catalog
readers can follow jobs and read completed chapters. Creating a job still requires the configured
publisher capability, and claiming stages still requires the configured worker capability.

## Scene-owned prompt creation (workflow 4)

Episodes own scenes, and video outputs belong to a pinned scene. A browser video request uses
creation schema 2, with `target: video`, a required `sceneRef` containing `episodeId`, `sceneId`
and the scene's exact `revision`, and arrays `characterIds`, `sourceKeys` and `contextKeys`.
The broker checks the scene's same-game episode ownership and pins its immutable revision.
Title and prompt (`brief`) are optional overrides; the pinned scene name supplies their default.
A description remains separately recorded, without inventing narrative facts. There is no
user-facing standalone video project entity. Internal editorial jobs retain their run identity.

A video request can select zero raw transcripts. Such a job has `sourceMode: prompt`, `raw: null`
and an empty `rawSources` array. It runs context selection and the screen-planning stages without
creating a fake transcript or a correction artifact. With actual transcript inputs, correction
runs first. The version-4 `video-source-brief` stage extracts source-attributed narrative facts,
relevant action and gaps before screenplay or generation-prompt composition. Subsequent creative
stages receive that clean brief, prompt and cast rather than transcription correction audits or
entire table conversations. Raw utterances, source-local timing and unknown speakers remain
unchanged in their preserved inputs. Legacy raw-key submissions and source-driven chapter
creation retain their transcript workflows; older executions keep their original versions.

Selected characters are registered structured identities, not searches for their names in asset
filenames. The broker pins the exact details revision and snapshot and the current immutable
physical appearance/artwork pair. Associated portrait/model inputs must explicitly list that
character and retain checksums, sizes and same-game immutable asset references. An unavailable
or unfinished appearance migration fails rather than substituting unrelated or legacy imagery.
The selected game facts and registered visual-style guidance are pinned alongside the scene.
Character/game/scene snapshots are bounded to 256 KiB in the durable job; their combined text
and transcript/context input size remains bounded to 512 KiB for stage processing.

Creative text context uses positive structured kinds: `lore`, `game-context`, `character-profile`
and `corrected-transcript`, or an explicit `extra.contextUse: creative-evidence` designation.
Generic `category: reference` or `contextUse: evidence` alone does not admit a document into
creative input. Provenance, migration, audit and generation-verification types, intermediate
records, excluded scripts and adaptation categories are rejected both for explicit selections
and automatic context discovery. Eligibility uses structured kinds/artifact types/roles, never
private names or title guesses. This projection applies immediately across all existing indexed
records without deleting or rewriting technical evidence; old jobs retain their pinned context.
The source indexes themselves keep their existing version and complete-inventory requirement.

Scene types guide planning with the standing per-shot model policy: action recommends Kling
3 Pro, dialogue recommends MiniMax H3 Max, and city/opener shots recommend Veo 3.1 Fast.
Travel/map scenes require actual map/location evidence and preserve unknown geography.
These recommendations never authorize spending. Planning metadata preserves the exact
`sceneRef` and episode/scene IDs, while its envelope preserves full scene/cast snapshots.
Finished footage must carry its own explicit association from the renderer; matching titles
or planning outputs do not establish one.

Workflow 4 still executes only subscription-backed planning. It cannot submit paid footage,
performances or voice generation. Render permissions, source sharing, model choice and spending
remain governed by the separate production workflow and approved budget guard.

### Episode workspace migration (version 1)

Before enabling the scene-owned workspace for an existing deployment, an authorized
`ASSET_MIGRATORS` account runs `panther videos migrate-workspace`. This authenticated
`POST /video-workspace/migrate` dry run enumerates **every registered game** through
catalog metadata, then every current `tv-library` TVEpisode and its immutable DDB
history. It does not scan source storage. The complete inventory is bounded to 1,000
catalog/episode/history rows, 16 MiB and 100 pages per partition; exceeding any bound
blocks the plan rather than presenting partial completeness. Large individual histories
above 320,000 encoded audit bytes also block migration and need an explicit bounded migration extension.
Keep dry-run output outside Git: it contains private application inventory.

Review the returned statuses and `inventoryHash`, then run
`panther videos migrate-workspace --apply --inventory-hash HASH`. A changed inventory or
any destination conflict blocks the apply before writes. Each episode imports atomically
with a conditional guard on the exact legacy payload and revision, a new Episode pointer,
immutable Episode history, and an immutable versioned audit containing the exact source
current/history snapshots, source SHA-256, actor, timestamp and inventory hash. The original
TVEpisode records and histories remain recoverable; imports preserve episode IDs, titles
as names and synopses as descriptions. Missing historical creation dates stay unknown.
An interrupted run can be resumed by repeating the dry run and apply: already imported
records are verified against their source hash and never overwritten, including subsequent
human edits to the new Episode. Concurrent source/destination changes return a conflict;
rerun the dry run to review and resume any completed per-episode transactions.

Cuts are alternative immutable video representations, **not scenes**. The migration creates
zero scenes, leaves existing clip collections intact, and invents no episode ownership for
previous footage. Existing explicit scenes and episodes are never merged by matching names.
The new workspace has no legacy read fallback. Verify every dry-run episode is
`already-migrated` after apply and review destination records/history before cutover.
Source TV GET endpoints remain maintenance access to recoverable history, not a supported
workspace read path. Legacy TV POST routes and their write permissions are retired at
deployment; CLI legacy save-series/save-episode commands are removed. Production rollout is incomplete until this all-game verification
has run with deployment credentials; code/test completion does not imply data backfill.

Legacy `/tv-series` and `/tv-episodes` API routes remain GET-only for recovery; their
Lambda has no write permissions and the CLI no longer exposes their save commands.
New episode creation and edits use the Episode/Scene endpoints exclusively.

### Map scenes

An episode-owned Scene may use `type: map` and optional `mapAssetKey`. Title-only scene
creation remains valid; generating a map scene requires an explicitly selected same-game
PNG, JPEG or WebP image from the bounded materialized catalog. Ordinary map references need
no invented generation history. Internal, processing, unresolved-lineage and non-raster assets
are excluded. Existing scene revisions remain unchanged; no geographic or map association is
inferred for earlier scenes.

Submission freezes the scene revision plus `selectedMap` version 1: immutable asset key,
SHA-256, byte count and content type. The worker verifies the downloaded image and attaches
it to each subscription-backed video planning stage. Generation packets contain a structured
`mapGenerationPacket` version 1 with `mode: image-to-video`, exact `firstFrame`, frozen
`sceneRef`, prompt and `sourceKeys`. This binding travels with the packet; it does not require
another map selection. The prompt treats the image as a map, preserves its geography and
labels, and animates a red starting dot and red footprints toward the requested destination.
Unreadable or unidentified locations remain explicit planning uncertainties.

All derived planning assets include the map in immutable `sourceKeys`; private references
and image bytes remain outside Git. Provider/model/rights/budget authorization is still
required before actual paid image-to-video submission. Map selection or completed planning
alone never triggers a paid request.
