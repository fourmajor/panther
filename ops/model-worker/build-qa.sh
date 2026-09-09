#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
# Build from a reviewed checkout only. No personal folders, auth files, or Docker socket are copied.
docker --context desktop-linux build --tag panther-model-qa:local \
  --file "$repo_dir/ops/model-worker/Dockerfile" "$repo_dir"
