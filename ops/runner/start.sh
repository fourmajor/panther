#!/usr/bin/env bash
set -euo pipefail

# Explicit context prevents accidentally starting the runner on a remote engine.
runner_context="${PANTHER_DOCKER_CONTEXT:-desktop-linux}"
runner_name="panther-local-$(date +%s)-$RANDOM"
runner_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
docker --context "$runner_context" info >/dev/null
docker --context "$runner_context" build --tag panther-runner:local "$runner_dir"
docker --context "$runner_context" run --detach --init --name "$runner_name" \
  --label app=panther-runner --cpus 2 --memory 4g --pids-limit 512 \
  --cap-drop ALL --security-opt no-new-privileges \
  panther-runner:local >/dev/null

cleanup_failed_registration() {
  docker --context "$runner_context" rm --force "$runner_name" >/dev/null
}
trap cleanup_failed_registration ERR
gh api --method POST repos/fourmajor/panther/actions/runners/registration-token --jq .token \
  | docker --context "$runner_context" exec --interactive "$runner_name" bash -c '
      set -euo pipefail
      read -r registration_token
      ./config.sh --unattended --ephemeral --url https://github.com/fourmajor/panther \
        --token "$registration_token" --name "$1" --labels panther-local --work _work
      unset registration_token
      touch /home/runner/.configured
    ' -- "$runner_name"
trap - ERR
echo "Started $runner_name (one trusted job, then exits)."
echo "Logs: docker --context $runner_context logs --follow $runner_name"
echo "After completion: docker --context $runner_context rm $runner_name"
