#!/usr/bin/env bash
# One-time, with admin credentials (AWS_PROFILE=panther-sso-admin).
# Creates the GitHub OIDC provider and PantherGitHubDeploy.
# After this, merges to main can deploy without an SSO login.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -z "${PANTHER_IDENTITIES_FILE:-}" ]]; then
  echo "Set PANTHER_IDENTITIES_FILE. The CDK app loads it while synthesizing." >&2
  exit 1
fi

account="${PANTHER_AWS_ACCOUNT_ID:-223663280572}"
role="arn:aws:iam::${account}:role/PantherGitHubDeploy"
cd infra
npm run build
npx cdk deploy PantherGitHubDeploy --require-approval never --exclusively \
  --context "account=${account}"
# The CDK bootstrap roles already trust this account root, so an admin role in the
# account can assume them. No re-bootstrap (and no --trust) is needed.
echo "GitHub can assume ${role} after the next push to main."
echo "If the OIDC provider already exists, deploy again with --context githubOidcProviderArn=ARN."
