#!/usr/bin/env bash
set -euo pipefail

# Registration runs separately over stdin: no token in Docker environment or image.
for attempt in {1..120}; do
  if [[ -f /home/runner/.configured ]]; then
    exec ./run.sh
  fi
  sleep 1
done
echo 'Runner registration did not finish within two minutes.' >&2
exit 1
