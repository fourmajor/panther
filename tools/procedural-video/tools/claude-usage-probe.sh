#!/bin/zsh
# Prints the highest current Claude subscription usage percentage (weekly limits) without spending tokens.
# Uses the Claude Code CLI's `/usage` command in headless mode. CLAUDE_BIN overrides the CLI path.
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN
C=${CLAUDE_BIN:-claude}; O=$(mktemp); cd /tmp
"$C" -p "/usage" --output-format stream-json --verbose > $O 2>&1 & P=$!
for i in {1..40}; do grep -q '"type":"result"' $O && break; sleep 1; done
kill $P 2>/dev/null
python3 - $O <<'PY'
import json,sys
best=-1
for l in open(sys.argv[1]):
    try: d=json.loads(l)
    except Exception: continue
    for x in (d.get("usage_report",{}).get("rate_limits") or {}).get("limits",[]):
        best=max(best,x.get("percent") or -1)
print(best)
PY
rm -f $O
