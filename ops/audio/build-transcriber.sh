#!/usr/bin/env bash
set -euo pipefail
audio_ops_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
docker --context desktop-linux build --tag panther-audio:local "$audio_ops_dir"
docker --context desktop-linux image inspect panther-audio:local --format '{{.Id}}'
