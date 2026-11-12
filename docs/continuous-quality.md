# Continuous quality

Panther is a hobby project. Rapid development beats a large test suite. The policy lives in
`AGENTS.md`.

The smoke set is `tests/test_smoke.py` and `infra/test/github-deploy.test.ts`. It covers pipeline
hand-offs, the fal spend cap, the session budget, and recovery that reuses finished stages. It runs
after a push to `main`, does not block that deploy, and does not block merges. Do not add tests by
default, and do not restore a Playwright or nightly gate.

Do not copy owner credentials, speech, identities, or game media into CI. Do not invent completed
jobs, names, or media to make a check pass. Unknown billing stays unknown.

A merge to `main` deploys with GitHub OIDC. See `docs/aws-foundation-runbook.md`.
