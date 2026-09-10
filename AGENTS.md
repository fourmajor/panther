# Repository Agent Instructions

## Panther CLI and game assets

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
- Merge the pull request when the change is ready. Do not ask for routine manual approval unless the
  user explicitly requests an approval gate or a substantive unresolved decision requires input.
- After merging, update the local `main` branch when practical.

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
- CI remains manually triggered by the owner on reviewed `main` or `codex/` branches in this repo.
  Do not dispatch untrusted contributor code, including code copied from forks. Never enable
  automatic fork/PR execution on a personal runner. Containers are not a complete security boundary.
- Do not mount personal directories, AWS credentials, or the Docker socket into the runner.
- Prefer this owned compute over GitHub-hosted runners; do not enable automatic hosted CI without
  explicit approval. Continue deploying from the laptop with short-lived AWS credentials.
- Avoid always-on hosted compute solely to reduce build latency.
- AWS infrastructure is defined with AWS CDK and committed alongside the application.

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
  $50 total budget guard described in `docs/fal-video-comparison.md`. This is a narrow paid-video
  integration, never an editorial/Blender inference fallback. Do not call fal generation directly,
  erase/reinitialize its ledger to recover budget, infer model/rights approval, or enable top-ups.
  Unknown submissions retain their reservation and block new submissions. The generation key and
  the separate read-only-use admin billing key remain in the OS credential store, never prompts,
  Git, AWS, browser code or the CI runner. This local guard cannot govern dashboard/other-device spend.

- Model-workflow AI runs through Codex CLI on the owner's laptop using ChatGPT subscription
  authentication. Never introduce API-key inference, paid generation providers, automatic credit
  purchases, or usage-reset redemption as a fallback. Pause/checkpoint on limits. AWS coordinates
  jobs and stores data; the agent and Blender run locally, while OpenAI hosts the model inference.
- Prefer architectures with near-zero compute cost while Panther is inactive.
- Avoid always-on infrastructure such as NAT Gateways, EC2 instances, load balancers, conventional
  provisioned databases, and persistent hosted CI runners unless explicitly justified and approved.
