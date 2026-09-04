# Repository Agent Instructions

## Panther CLI and game assets

- Before organizing or uploading game assets, run `panther instructions`. The guide is bundled in
  `src/panther_journal/agent-instructions.md` and ships with the CLI, not just this repository.
- Follow its object layout, kind/category distinctions, metadata schema, and provenance rules.
- Use the Panther CLI for supported application operations. Do not bypass its no-overwrite or
  authorization limits with direct S3 writes. Keep all actual game files and metadata outside Git.
- Update the bundled guide and CLI tests when changing asset organization or metadata behavior.

## Change workflow

- Make all repository changes on a branch and deliver them through a pull request.
- Never push changes directly to `main`.
- Use the `codex/` branch prefix unless the task requires a different name.
- Run relevant local checks before opening the pull request.
- After opening a pull request, inspect its diff and available checks.
- Automatic CI is intentionally deferred; local verification is the normal readiness gate for now.
- Merge the pull request when the change is ready. Do not ask for routine manual approval unless the
  user explicitly requests an approval gate or a substantive unresolved decision requires input.
- After merging, update the local `main` branch when practical.

## Frontend verification

- Playwright is a required readiness gate for changes that affect the frontend, including UI,
  styling, navigation, browser authentication, asset loading, and backend/infrastructure changes
  that alter browser behavior (such as API contracts, CSP, CORS, or static hosting).
- Add or update focused Playwright regression tests for the affected user behavior; do not rely
  only on the existing suite when it does not exercise the change. Run `npm run test:browser` from
  `infra/` before declaring the change ready to merge. Install Chromium with
  `npx playwright install chromium` when needed.
- Use isolated test browsers launched through the CLI, never the user's personal browser or
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
- CI remains manually triggered, restricted to trusted `main` and the owner. Never enable
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

- Prefer architectures with near-zero compute cost while Panther is inactive.
- Avoid always-on infrastructure such as NAT Gateways, EC2 instances, load balancers, conventional
  provisioned databases, and persistent hosted CI runners unless explicitly justified and approved.
