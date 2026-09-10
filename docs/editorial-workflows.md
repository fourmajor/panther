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

The versioned plan is bundled in the CLI and used by CDK. Every row below is one or more named
Step Functions callback states, not one giant prompt. Each stage gets a fresh AI session and saves
JSON provenance plus a readable Markdown artifact. Version 2 resolves routine editorial uncertainty
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
fal by default**, explicitly including dialogue and city/urban establishing shots. Use **Kling 3 Pro
through fal for battle/action shots**. These are production preferences, not universal quality claims.

Apply the choice per shot: action in a city still uses Kling; a dialogue close-up between combat
beats uses Veo. For an inseparable mixed shot, use Kling when battle/action drives the shot,
otherwise Veo. Record the selected model and rationale in the production plan. New model versions,
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
running. The table of contents shows one chapter per source session, using the newest run's
completed edition. Sessions are ordered by their first run's creation time; this is an initial
ordering convention, not a user-edited book/volume structure. Each edition has a stable URL at
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
records, `game-context`, sources marked `reference`/`canonical-source`, and future kinds explicitly
marked `extra.contextUse: evidence`. Use `extra.contextUse: exclude` for a held-out script; never upload
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
