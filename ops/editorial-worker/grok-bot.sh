#!/usr/bin/env bash
# Grok Bot routine entry point on the box. Starts the editorial worker when it is not running,
# then prints the editorial calls waiting for an answer as JSON. No LLM runs here.
#   PANTHER   panther CLI (default: ~/panther-editorial/venv/bin/panther)
#   WORK_DIR  private worker directory outside Git (default: ~/panther-editorial/jobs)
set -euo pipefail
# The box has no OS keyring: use the opt-in encrypted file store (key in ~/.secrets/).
export PANTHER_SESSION_STORE=${PANTHER_SESSION_STORE:-box-file}
PANTHER=${PANTHER:-$HOME/panther-editorial/venv/bin/panther}
WORK_DIR=${WORK_DIR:-$HOME/panther-editorial/jobs}
mkdir -p -m 700 "$WORK_DIR"
running() { "$PANTHER" editorial agent-requests --work-dir "$WORK_DIR" | grep -q '"workerRunning": true'; }
if ! running; then
  nohup "$PANTHER" editorial worker --work-dir "$WORK_DIR" >>"$WORK_DIR/worker.log" 2>&1 </dev/null &
  sleep 5
fi
exec "$PANTHER" editorial agent-requests --work-dir "$WORK_DIR"
