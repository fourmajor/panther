# Repository Agent Instructions

## Change workflow

- Make all repository changes on a branch and deliver them through a pull request.
- Never push changes directly to `main`.
- Use the `codex/` branch prefix unless the task requires a different name.
- Run relevant local checks before opening the pull request.
- After opening a pull request, inspect its diff and available checks.
- Merge the pull request when the change is ready. Do not ask for routine manual approval unless the
  user explicitly requests an approval gate or a substantive unresolved decision requires input.
- After merging, update the local `main` branch when practical.

## Tooling and CI/CD

- Prefer command-line tools and APIs. Do not operate the user's browser for repository work.
- GitHub Actions jobs run on project-owned self-hosted compute using the `panther` runner label.
- Do not introduce GitHub-hosted runners without explicit approval.
- Slow or queued CI is acceptable when the home runner is offline; avoid always-on hosted compute
  solely to reduce build latency.
- AWS infrastructure is defined with AWS CDK and committed alongside the application.

## Cost posture

- Prefer architectures with near-zero compute cost while Panther is inactive.
- Avoid always-on infrastructure such as NAT Gateways, EC2 instances, load balancers, conventional
  provisioned databases, and persistent hosted CI runners unless explicitly justified and approved.
