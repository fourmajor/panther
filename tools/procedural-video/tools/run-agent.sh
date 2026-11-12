#!/bin/zsh
# Build/iterate a session with Claude Code headless, under the usage guard.
#   BRIEF   prompt file for the agent (game-specific; keep it with the session, not in the repo)
#   MODEL   model id or alias (e.g. claude-fable-5-2)        START_MAX  refuse to start at/above this % (default 50)
#   LIMIT   kill the run at this % (default 55)              CLAUDE_BIN Claude Code CLI path (default: claude)
# Subscription auth only: API-key env vars are unset so usage bills to the plan, never to an API key.
set -e
cd "$(dirname "$0")/.."
: "${BRIEF:?set BRIEF}"; : "${MODEL:?set MODEL}"
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL
C=${CLAUDE_BIN:-claude}; START_MAX=${START_MAX:-50}; export LIMIT=${LIMIT:-55}
U=$(tools/claude-usage-probe.sh); echo "usage at start: ${U}%"
[ "$U" -ge 0 ] && [ "$U" -lt "$START_MAX" ] || { echo "refusing to start (usage ${U}%, max ${START_MAX}%)"; exit 1; }
"$C" -p "$(cat "$BRIEF")" --model "$MODEL" --permission-mode acceptEdits \
  --allowedTools Read Write Edit Glob Grep Bash --output-format stream-json --verbose > agent-run.jsonl 2> agent-run.err &
sleep 5
PROBE=tools/claude-usage-probe.sh MATCH="claude -p .*--model $MODEL" tools/usage-guard.sh &
wait
