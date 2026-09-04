# Repository Agent Instructions

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
