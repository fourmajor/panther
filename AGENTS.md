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
- No project-owned CI runner is currently available. Home-owned self-hosted runners are a future
  option, not a current dependency.
- If cloud CI is needed before a home runner exists, use a manually triggered GitHub-hosted runner
  within the GitHub free tier. Do not enable automatic hosted CI without explicit approval.
- Avoid always-on hosted compute solely to reduce build latency.
- AWS infrastructure is defined with AWS CDK and committed alongside the application.

## Cost posture

- Prefer architectures with near-zero compute cost while Panther is inactive.
- Avoid always-on infrastructure such as NAT Gateways, EC2 instances, load balancers, conventional
  provisioned databases, and persistent hosted CI runners unless explicitly justified and approved.
