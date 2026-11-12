#!/usr/bin/env bash
# One-time, with admin credentials (AWS_PROFILE=panther-sso-admin).
# Creates the GitHub OIDC provider and PantherGitHubDeploy, then trusts that
# role from the existing CDK bootstrap roles in us-west-2 and us-east-1.
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
npx cdk bootstrap "aws://${account}/us-west-2" "aws://${account}/us-east-1" \
  --trust "$role" --trust-for-lookup "$role" \
  --context "account=${account}"
echo "GitHub can assume ${role} after the next push to main."
echo "If the OIDC provider already exists, deploy again with --context githubOidcProviderArn=ARN."
