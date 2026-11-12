#!/usr/bin/env bash
# Fast local deploy, and the command the main-branch GitHub workflow runs.
# Code-only changes hotswap. Infrastructure changes use a full CloudFormation deploy.
set -euo pipefail
cd "$(dirname "$0")/.."

classify() {
  local mode=hotswap
  local domain=0
  local line
  while IFS= read -r line; do
    case "$line" in
      "" ) ;;
      infra/lib/panther-domain-stack.ts)
        mode=full
        domain=1
        ;;
      infra/lib/*|infra/bin/*|infra/cdk.json|infra/package.json|infra/package-lock.json|__FULL__)
        mode=full
        ;;
    esac
  done
  if [[ "${PANTHER_DEPLOY_BASE:-}" == 0000000* ]]; then
    mode=full
    domain=1
  fi
  printf '%s %s\n' "$mode" "$domain"
}

if [[ "${1:-}" == "--decide" ]]; then
  classify
  exit 0
fi

collect_changes() {
  if [[ -n "${PANTHER_DEPLOY_BASE:-}" ]]; then
    if [[ "${PANTHER_DEPLOY_BASE}" == 0000000* ]]; then
      printf '__FULL__\n'
      return
    fi
    if ! git cat-file -e "${PANTHER_DEPLOY_BASE}^{commit}" >/dev/null 2>&1; then
      printf '__FULL__\n'
      return
    fi
    git diff --name-only "${PANTHER_DEPLOY_BASE}" HEAD || true
    return
  fi
  if git rev-parse --verify origin/main >/dev/null 2>&1; then
    git diff --name-only origin/main...HEAD || true
  fi
  git diff --name-only HEAD || true
  git ls-files --others --exclude-standard
}

requested=auto
dry=0
for arg in "$@"; do
  case "$arg" in
    --full) requested=full ;;
    --hotswap) requested=hotswap ;;
    --dry-run) dry=1 ;;
    *)
      echo "Usage: ops/deploy.sh [--full|--hotswap|--dry-run]" >&2
      exit 2
      ;;
  esac
done

if [[ -z "${PANTHER_IDENTITIES_FILE:-}" ]]; then
  echo "Set PANTHER_IDENTITIES_FILE to the private identities file outside the repo." >&2
  exit 1
fi

account="${PANTHER_AWS_ACCOUNT_ID:-223663280572}"
changes="$(collect_changes)"
read -r detected domain < <(printf '%s\n' "$changes" | classify)
mode="$detected"
if [[ "$requested" == full ]]; then
  mode=full
elif [[ "$requested" == hotswap ]]; then
  mode=hotswap
  domain=0
fi

stacks=(PantherMediaExplorer)
flags=(--exclusively --require-approval never)
if [[ "$mode" == full ]]; then
  stacks+=(PantherGitHubDeploy)
  if [[ "$domain" == 1 ]]; then
    stacks+=(PantherDomain)
  fi
else
  flags+=(--hotswap-fallback)
fi

echo "panther deploy: mode=${mode} stacks=${stacks[*]}"
if [[ "$dry" == 1 ]]; then
  printf 'cdk deploy'
  printf ' %q' "${stacks[@]}" "${flags[@]}" --context "account=${account}"
  printf '\n'
  exit 0
fi

cd infra
npm run build
npx cdk deploy "${stacks[@]}" "${flags[@]}" --context "account=${account}"
