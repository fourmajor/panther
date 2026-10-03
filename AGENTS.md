# Repository Agent Instructions

## Application and UI contracts

- The game selector owns the current game. Dashboard links to actual recent records; Settings
  contains editable game details/defaults without redundant introductory banners. Account is a
  separate page. Do not add repeated system labels, slogans, environment badges or technical
  migration/provenance setup copy to ordinary user workflows.
- Sessions consolidates recording, playback and transcripts. Keep prior Audio/Transcripts routes
  as navigation redirects, not duplicate libraries. Recording state belongs to its recording
  controls; do not show it on unrelated pages. Open transcript details in a dialog or nested view,
  preserving the list position and selection.
- Videos uses episodes containing ordered, owned scenes, not an extra Video Project entity or
  reusable scenes across episodes. Creating a scene requires its title only; other direction is
  optional and multiline. Typed scenes may select appropriate real assets (including a pinned map).
  Episode playback uses actual selected rendered outputs, never fabricated completion.
- Assets have open-ended types and user tags. Use tags for user organization rather than imposing
  opinionated category choices. Preserve existing structured storage/metadata facts and historical
  categories during migrations; hiding an implementation detail is not permission to erase it.
- Use the shared React/Radix/Tailwind components and TanStack Query cache/invalidation for new UI.
  Use standard shadcn/ui components with Tailwind CSS 4 for controls and compositions; do not
  invent replacement comboboxes, popup positioning, focus management or other widget behavior.
  Prefer the official registry components and their documented composition patterns.
  Avoid unnecessary reloads, page spinners and refresh buttons. Loading placeholders should pulse
  without changing layout; errors must have useful recovery and reflect the operation that failed.
- Keep primary actions compact and consistently at the top right of section headings/toolbars.
  Use concise labels, visible controls and honest empty/progress states. Do not hide normal workflows
  in accordions or add instructional boilerplate when an indicator/control communicates the state.
  Verify keyboard access, actual hit areas, desktop/mobile layouts and unobstructed actions.

## Persistent local development

- The loopback server (`tools/dev_server.py`) uses SQLite outside Git. App reads must come from the
  database, never hardcoded preview datasets. Development demo regeneration is an explicit write
  operation and must preserve user-created records, assets and history. Keep fixtures synthetic.
- Use the project virtual environment, install dependencies with
  `.venv/bin/python -m pip install -e ".[dev]"`, and build React with
  `npm ci --prefix web/ui`, configure the private gitignored `.env`, then run
  `.venv/bin/python tools/dev.py` for the complete API/UI/nine-worker stack. The launcher
  builds React and requires fresh processor heartbeats before exposing the app. Use
  `tools/dev_server.py` alone only for an intentionally API-only development session.
  See `docs/local-development.md`.
- Continuous browser-recording playback is a separate local worker:
  `.venv/bin/python tools/dev_playback_worker.py --database PRIVATE_DB --work-dir PRIVATE_DIR`.
  It needs FFmpeg/ffprobe, verifies explicit completed immutable source sets, and publishes real
  MP3/manifest outputs into the same database. Keep assembly out of the browser/uploader/server
  request handler. Preserve capture warnings and exact source lineage; never overwrite originals.
- Local editorial generation uses the direct OpenAI Responses API with a server-side key from
  gitignored `.env` or the worker environment. Do not route local app requests through Codex CLI.
  Preserve exact requests, responses, actual model/token usage and unknown billing outcomes.
  Do not automatically repeat requests after ambiguous paid failures. The full local stack includes
  editorial, images, transcription, summaries, playback, scene video, narration and episode assembly.
  Optional transcript/context inputs are preprocessed into evidence-backed scene prompts. Narration
  direction becomes bounded ElevenLabs v3 performance cues without rewriting approved spoken words.
  Persist real requests and show unavailable/waiting/failure states honestly. Never synthesize successful jobs,
  invented output data, identities or summaries to make a preview seem functional. A separate local
  database/identity must not grant production access or bypass authenticated production operations.

## Private account data

- Specific account identities, emails, account rosters and capability assignments are private
  deployment/application data, not repository content. Never add real users to source code,
  fixtures, docs, issues, PR descriptions or CI artifacts. Use fictional identities in tests/examples.
- CDK still owns infrastructure and provisioning definitions. Supply actual account configuration
  from an owner-only file outside the repository using `PANTHER_IDENTITIES_FILE`; see
  `docs/private-account-configuration.md`. Never commit that file, synthesized production templates,
  deployment diffs or account inventories. Missing configuration must fail closed.
- Preserve existing account/resource identities, passwords and access when changing how configuration
  is stored; verify no user deletion/recreation or privilege expansion in the deployment diff.
  Keep Player identities separate from login accounts. Formal member/admin roles are separate work.
- Removing data from the current tree does not erase Git/PR history. Report that limitation; do not
  rewrite shared history or claim historical erasure without a separately authorized cleanup.

## Panther CLI and game assets

- Keep browsing off the source-storage scan path. Maintain the versioned materialized catalog for
  uploads and metadata changes; query bounded game/section pages. New asset contracts must update
  the projection and all-game rebuild/verification. Never silently fall back to scanning S3 on a
  page view or present an incomplete index as a complete library. See `docs/asset-browse-index.md`.

- Record structured generation metadata for every asset using `docs/generation-metadata.md`:
  actual model/version when known, provider, inference location distinct from local coordination,
  tools, and evidence-backed cost status. Unknown is not zero; subscriptions and budget reservations
  are not per-asset billed charges. Backfill older assets through the same versioned migration,
  preserving original bytes/provenance; never guess model identity from appearance or tool names.

- Every asset has an explicit semantic version record (`metadata.extra.version`), separate from
  S3 object versions and source lineage. New revisions are new immutable assets uploaded with
  `panther upload --new-version-of`; never overwrite previous content. Official character
  portraits/models also retain profile-backed selection history so users can view earlier
  appearances. Use the all-game migration and verification in `docs/asset-versions.md` for
  earlier assets; do not infer a version family from similar filenames or images.

- Physical storage organization is a versioned application contract. Use the shared server path
  builder and the migration requirements in `docs/asset-storage.md`; never hand-assemble new S3 destinations.
  Group content by game, character/session/shared library, media kind, and immutable asset revision;
  keep workflow internals separate from finished media. Support new kinds through structured metadata.
  Stable asset references and physical storage locations are distinct: never rewrite raw evidence,
  workflow checksum pins, or every downstream document just because a file moves. Every asset must
  use the same location catalog after cutover, without old-path fallbacks. A rollout remains incomplete
  until all games are migrated, verified, and temporary modes/old write permissions are removed.

- Evolving standards require migrations, not permanent legacy exceptions. Whenever an asset/data
  contract or organizational rule changes, update producers and validators, provide a versioned,
  repeatable migration, backfill all affected existing data, verify the full inventory, and remove
  obsolete compatibility branches before calling the change complete. Apply this to every game,
  not only new uploads or the current test fixture. Temporary rollout compatibility must have an
  explicit removal step; do not leave non-compliant assets as a supported alternative format.
  Preserve original bytes, prior metadata/revisions and exact provenance in recoverable history.
  Use Panther-authenticated migration operations with dry runs, conflict guards and audit records,
  not ad hoc S3 writes. Unknown facts stay explicitly unknown; never invent identity, consent,
  canon, or derivation to pass validation. Report any genuinely unresolvable records as migration
  blockers rather than quietly exempting them. Keep private inventories and migration reports out
  of Git; commit migration code, schema changes, tests and reusable operational instructions.

- Recording chunks are grouped by a structured chunk-set identity. Only an explicitly completed,
  server-verified uploaded set triggers the playback workflow, never individual uploads or a quiet
  period. Assemble listening derivatives in the separate laptop workflow, not the uploader. Browser
  playback must be continuous; preserve lossless source chunks and capture warnings for reprocessing.

- Every derived asset must record its exact immutable inputs using `sourceKeys`; large structured
  provenance can additionally use `inputArtifacts` keyed references in its JSON document. Asset
  views expose Inputs and reverse-linked Outputs across media types. Never overwrite inputs, guess
  missing historical lineage, or duplicate mutable output lists onto source assets. Preserve related
  exports/parts under their asset identity, distinct from directional derivation relationships.
  User-facing Inputs/Outputs show finished assets only, traversing hidden processing steps without
  changing stored provenance. Group explicit audio parts/listening copies and paired transcript
  exports; never show manifests, plans, drafts or review reports as ordinary finished connections.

- Prefer explicit, versioned structured data types for application facts. Player is a stable
  person identity, separate from a login account, Character, and a per-game membership/role.
  Transcripts identify players; in-character speech and table chatter are later annotations,
  never grounds for changing the speaker's identity or deleting the source utterance.
- Before organizing or uploading game assets, run `panther instructions`. The guide is bundled in
  `src/panther_journal/agent-instructions.md` and ships with the CLI, not just this repository.
- Follow its object layout, kind/category distinctions, metadata schema, and provenance rules.
- Use the Panther CLI for supported application operations. Do not bypass its no-overwrite or
  authorization limits with direct S3 writes. Keep all actual game files and metadata outside Git.
- Whenever asking the user to sign in to AWS for an asset or other game-related operation, also
  offer to extend the Panther CLI so future operations of that type use Panther authentication
  without requiring direct AWS access. Check existing CLI capabilities first; explain any missing
  capability and distinguish game operations from infrastructure deployment. An offer is not
  authorization to broaden permissions or implement an unrelated feature. Infrastructure changes
  still use CDK and AWS administrative authentication, including deployments that enable CLI features.
- Update the bundled guide and CLI tests when changing asset organization or metadata behavior.
- For held-out audio tests, create the initial transcript through `panther recording transcribe
  --blind`. Keep the reading script outside recording inputs and uploads. Never use script text
  from files or conversation memory to generate/correct that first transcript. Compare against
  the script only after preserving the unaltered recognizer output and transcript version.

## Editorial workflows

- Completed recording sets automatically enter the owned-compute session finalization workflow
  in `docs/session-automation.md`, then the corrected-transcript, novel and screen-planning branches.
  Paid session video generation must wait for owner approval of the exact script/storyboard.
  The owner-authorized ceiling is $10 per session using the established fal models, including
  other generated media in that project. Never treat Stop, preflight, or this cap as approval
  of an unseen plan, paid retries, credit purchases, cloning or provider changes.

- High-quality speech is a standing production requirement. Use ElevenLabs Eleven v3 through
  fal for separately generated narration/voice performances via `panther narration`; see
  `docs/narration-workflow.md`. Do not use Chatterbox, macOS/system TTS, or another cheaper
  fallback, even for previews. Preserve existing historical assets and honest provenance;
  this is a forward production policy, not authority to regenerate or relabel history.
  Cast an appropriate voice and direct its performance; model choice alone is not quality
  approval. Trailer narration needs deliberate dramatic pacing, not a neutral reading.
  Present a separate short audition when voice approval is requested, then pin the accepted
  voice for full narration. Never substitute a narrated slideshow for a storyboard review.
  Each paid project needs explicit model/text-sharing/budget approval. No automatic paid
  retries, credit purchases, cloning, or fallback. Keep narration and video within the same
  owner-approved total by protecting the other-media allowance in the local budget ledger.

- Video production uses the separate completed-manifest local workflow in `docs/video-production.md`.
  Pin selected appearance revisions and prepared shot frames; review generated footage for face,
  costume, weapon-hand, prop, motion and cross-shot continuity. Preserve the original take and
  actual edit/review history. Keep dialogue/music/effects/ambience independently editable when
  genuine stems exist; a native mixed soundtrack is not isolated speech. Finish with measured
  sound, color adjustment, editable captions, clean master, browser delivery and final QC.
  Routine defects yield explicit working drafts, never invented repairs or implicit paid retries.
  Frame-sampled visual checks and technical sound checks must disclose their coverage limits.

- Video production model policy: default to Veo 3.1 Fast through fal, explicitly for city shots;
  use MiniMax H3 Max (not Turbo) through fal for dialogue and Kling 3 Pro through fal for battle/action.
  Apply per shot, with action taking precedence over city setting and separate dialogue close-ups
  using H3 Max. Follow the mixed-shot
  guidance and exact profiles in `docs/fal-video-comparison.md#production-model-selection`.
  Record the choice in new executable plans; this is not automatic routing or spending approval.
  Do not silently upgrade/fallback models or rewrite historical comparison provenance.

- Novel link previews are separate read-time projections, never manuscript edits. Support hover,
  keyboard focus and touch; keep navigation usable when a preview fails. Use descriptions or clearly
  labeled excerpts, not invented facts, and only explicitly associated same-game preview images.
  Apply the same projection to existing and future records. Keep optional richer summaries structured
  and source-attributed; hovering must not trigger paid inference or media generation.

- Character appearances use explicit asset `characterIds`, not player or provenance inference.
  Narrative navigation uses typed same-game references with subtle reading styles. Keep annotations
  separate from manuscript text; ambiguous names remain unlinked. New entity pages should extend the
  reader's typed resolver, never permit arbitrary artifact-supplied URLs.

- Editorial workflows use fresh subscription-backed Codex stages; never replace the raw transcript
  with corrected or dramatized text. Preserve correction evidence, player IDs, uncertainty and capture
  warnings. Novel/video artifacts are adaptations, not new factual context. Read
  `docs/editorial-workflows.md` before changing those pipelines. Video generation remains unauthorized
  until the user explicitly chooses provider/model, budget and required permissions.

## Local Blender work

- For local Blender modeling, refinement, or rendering, use the repository skill at
  `.agents/skills/panther-blender-local/SKILL.md` (invoke as `$panther-blender-local`).
- The skill and generalized lessons belong in Git; character-specific modeling scripts,
  references, renders, models, and provenance remain outside the application repository.

## Change workflow

- Editorial workflows must resolve routine ambiguity autonomously using AI decisions, actual
  revisions and re-review. Do not stop for owner approval of creative or transcription choices.
  Preserve raw evidence, decision/revision history and explicit uncertainty; use conservative
  transcript fallbacks and labeled working drafts when bounded review does not converge. Later
  owner corrections create new versions. This does not authorize spending, video generation,
  voice cloning without consent, or bypassing authentication and source-integrity guards.

- Make all repository changes on a branch and deliver them through a pull request.
- Never push changes directly to `main`.
- Use the `codex/` branch prefix unless the task requires a different name.
- Run relevant local checks before opening the pull request.
- After opening a pull request, inspect its diff and available checks.
- Automatic CI is intentionally deferred; local verification is the normal readiness gate except
  for frontend-affecting changes, which also require self-hosted Playwright verification below.
- Follow the operator's current merge policy: when green, assign the PR to the owner; do not merge
  unless the user explicitly authorizes merging. This supersedes the former automatic-merge rule.
- Commit/push ready changes on the trusted branch without a routine permission question. In a shared
  checkout inspect `git diff --cached` first so another agent's staged files are not swept in.
- Run `yarn review:smart` before every push (`--staged` for the index; `--offline` without model access).
  It is advisory and does not replace required tests or readiness gates.
- Push all current changes before marking a draft Ready for Review. Shepherd the resulting checks
  on the exact current SHA with `shepherd-pr` and background `yarn shepherd:wait --pr N`; fix failures
  rather than stopping at the first red check. Do not replace this with timed checks polling.
- Do not automatically run review reflection after a merge. Batch reflection is a separately
  requested/scheduled task; individual feedback is not automatic authority to change project rules.
- After an explicitly authorized merge, update local `main` when practical.

## Frontend verification

- Playwright is a required readiness gate for changes that affect the frontend, including UI,
  styling, navigation, browser authentication, asset loading, and backend/infrastructure changes
  that alter browser behavior (such as API contracts, CSP, CORS, or static hosting).
- Add or update focused Playwright regression tests for the affected user behavior; do not rely
  only on the existing suite when it does not exercise the change.
- Run Playwright on the project's self-hosted Docker runner, not directly on the laptop host or
  GitHub-hosted runners. The manual `ci.yml` workflow installs Chromium and runs
  `npm run test:browser` from `infra/` inside the runner.
- Review the branch diff before dispatching CI. Push the trusted `codex/` branch, then dispatch
  `gh workflow run ci.yml --repo fourmajor/panther --ref BRANCH`. Wait for a successful run on the
  PR's latest commit before declaring it ready to merge; rerun after frontend/test changes.
  Record the run URL in the PR. Start a fresh runner when needed using `ops/runner/start.sh`.
- Use isolated test browsers inside that runner, never the user's personal browser or
  profile. Use synthetic fixtures and test credentials; keep private game assets out of Git.
- For visual/layout changes, verify relevant desktop and mobile sizes, inspect rendered output,
  and assert actual visibility and usability. Do not let automatic scrolling or forced clicks
  conceal clipping, overlays, or otherwise inaccessible controls.
- If a required browser test cannot run, report the blocker and do not claim frontend verification
  or routine merge readiness. Static checks and mocked API tests alone are not substitutes.
- The manual CI workflow already runs Playwright. This requirement does not enable automatic CI
  or require CI runs for documentation-only or unrelated backend changes.

## Tooling and CI/CD

- Prefer command-line tools and APIs. Do not operate the user's browser for repository work.
- Avoid running CI unless it adds material confidence beyond the relevant local checks.
- A Docker-based, repository-scoped runner can run on the owner's MacBook. Start it with
  `bash ops/runner/start.sh`; it accepts one job and exits. See `docs/self-hosted-runner.md`.
- CI remains manually triggered by trusted collaborators with repository write access on reviewed
  `main` or `codex/` branches in this repo.
  Do not dispatch untrusted contributor code, including code copied from forks. Never enable
  automatic fork/PR execution on a personal runner. Containers are not a complete security boundary.
- Do not mount personal directories, AWS credentials, or the Docker socket into the runner.
- Prefer this owned compute over GitHub-hosted runners; do not enable automatic hosted CI without
  explicit approval. Continue deploying from the laptop with short-lived AWS credentials.
- Avoid always-on hosted compute solely to reduce build latency.
- AWS infrastructure is defined with AWS CDK and committed alongside the application.
- Owner-approved unattended laptop administration uses the CDK-managed IAM Roles Anywhere
  setup in `docs/laptop-aws-access.md` and the `panther-laptop-admin` AWS profile. Prefer this
  renewable, Keychain-backed profile for infrastructure operations once verified; preserve SSO
  as recovery. Never create permanent IAM access keys, export the certificate key, put credentials
  in runners, or weaken Keychain controls. This is administrator-equivalent access, not additional
  authorization for deployments, spending, or bypassing the Panther CLI for game operations.

## AWS infrastructure changes

- Treat CDK as the authoritative and default path for every AWS resource, policy, permission,
  configuration, and integration that CDK or CloudFormation can represent.
- Do not create, modify, or delete AWS resources with manual console actions or direct AWS CLI/API
  mutation commands when the change can be implemented in CDK.
- Before any manual AWS write, verify that CDK and CloudFormation do not support the required
  resource or operation. Use the smallest possible manual bootstrap action only when no CDK path
  exists or CDK itself cannot yet run.
- Document every unavoidable manual AWS action and why CDK cannot perform it in the applicable
  repository runbook. Keep all resources created after the bootstrap boundary under CDK control.
- Preview account changes with `cdk diff` and confirm the target account and region before each
  deployment.
- Use `us-west-2` as Panther's default and primary AWS region. Define regional CDK resources there
  unless an AWS service is global or the user explicitly approves a different-region requirement.
- Document every resource that must live outside `us-west-2` and the AWS constraint that requires
  the exception.
- Known bootstrap exception: AWS does not expose organization-level IAM Identity Center enablement
  through CloudFormation, CDK, or a public API. After CDK creates the one-account Organization, that
  enablement is a documented console step; its users, permission sets, and assignments remain CDK
  managed.
- Known user-activation exception: Identity Center users created through its API have no initial
  password, and AWS exposes the email-OTP setting only in the Identity Center console. Enabling that
  setting and completing the user's initial password and MFA enrollment are documented console
  steps; do not recreate the user manually.

## Cost posture

- Explicitly owner-approved fal video comparisons use `panther video` and the persistent local
  budget guard. The initial $50 ceiling supports a narrowly bounded, explicitly owner-approved
  one-time $51 extension through `panther video budget extend`; retain its audit and all history.
  Never use the extension without explicit approval, mutate the ledger directly, or treat it as
  permission for other spending or top-ups. See `docs/fal-video-comparison.md`.
  This is a narrow paid-video
  integration, never an editorial/Blender inference fallback. Do not call fal generation directly,
  erase/reinitialize its ledger to recover budget, infer model/rights approval, or enable top-ups.
  Unknown submissions retain their reservation and block new submissions. The generation key and
  the separate read-only-use admin billing key remain in the OS credential store, never prompts,
  Git, AWS, browser code or the CI runner. This local guard cannot govern dashboard/other-device spend.

- User-authorized browser room transcription is a narrow exception: use `gpt-transcribe` only
  through an explicitly configured server-side OpenAI secret. Preserve audio and provider
  responses, keep uncertain billed outcomes unknown, and never automatically repeat paid requests.
  This does not authorize API inference as a fallback for any other workflow. See
  `docs/browser-recording.md`.

- The user has authorized direct server-side OpenAI API inference for local application generation.
  This replaces the subscription-only rule for those local jobs. Explicit local scene/narration
  generation also uses the configured fal/ElevenLabs keys; do not require a read-only billing/admin
  key or the comparison CLI ledger for those authorized browser requests. Keep exact model/input
  provenance and unknown costs honest. This does not authorize voice cloning, credit purchases,
  automatic paid retries or provider fallbacks. Existing cloud model-workflow workers remain
  subscription-backed until migrated explicitly. Never use automatic credit purchases or usage-reset redemption. Pause/checkpoint on limits. AWS coordinates
  jobs and stores data; the agent and Blender run locally, while OpenAI hosts the model inference.
- Prefer architectures with near-zero compute cost while Panther is inactive.
- Avoid always-on infrastructure such as NAT Gateways, EC2 instances, load balancers, conventional
  provisioned databases, and persistent hosted CI runners unless explicitly justified and approved.
