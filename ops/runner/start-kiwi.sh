#!/usr/bin/env bash
set -Eeuo pipefail

# Run from a reviewed Panther checkout on Kiwi. A short-lived registration
# token arrives on stdin; no GitHub credential is persisted on the host.
[[ "$(hostname -s)" == kiwi ]] || { echo 'This runner is only for Kiwi.' >&2; exit 1; }
[[ "$(uname -m)" == x86_64 ]] || { echo 'Kiwi runner expects x86-64.' >&2; exit 1; }
[[ -t 0 ]] && { echo 'Pass a short-lived runner registration token on stdin.' >&2; exit 1; }
runner_name=panther-kiwi-ci
runner_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
docker info >/dev/null
if docker container inspect "$runner_name" >/dev/null 2>&1; then
  echo "Runner container already exists: $runner_name" >&2
  exit 1
fi

nice -n 10 docker build --build-arg TARGETARCH=amd64 --tag panther-runner:kiwi "$runner_dir"
docker run --detach --init --name "$runner_name" --restart unless-stopped \
  --label app=panther-runner --label host=kiwi \
  --cpus 2 --memory 4g --pids-limit 512 \
  --cap-drop ALL --security-opt no-new-privileges \
  panther-runner:kiwi >/dev/null

cleanup_failed_registration() {
  docker rm --force "$runner_name" >/dev/null
}
trap cleanup_failed_registration ERR
docker exec --interactive "$runner_name" bash -c '
  set -euo pipefail
  read -r registration_token
  [[ -n "$registration_token" ]]
  ./config.sh --unattended --url https://github.com/fourmajor/panther \
    --token "$registration_token" --name panther-kiwi-ci \
    --labels panther-local,kiwi --work _work
  unset registration_token
  touch /home/runner/.configured
'
trap - ERR
echo "Runner registered on Kiwi: $runner_name"
