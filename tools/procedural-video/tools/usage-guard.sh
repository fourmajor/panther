#!/bin/sh
# Usage guard for long unattended agent runs: poll a usage probe, log it, and stop the run at a threshold.
#   PROBE   command that prints the current usage as a single percentage (required)
#   MATCH   pgrep/pkill -f pattern identifying the run to stop (required)
#   LIMIT   percentage at which the run is killed (default 55)     EVERY  seconds between probes (default 150)
#   LOG     markdown log file (default usage-log.md)
# Example: PROBE=./my-usage-probe.sh MATCH='my-agent -p' LIMIT=55 tools/usage-guard.sh &
: "${PROBE:?set PROBE to a command that prints a usage percentage}"; : "${MATCH:?set MATCH to a process pattern}"
LIMIT=${LIMIT:-55}; EVERY=${EVERY:-150}; LOG=${LOG:-usage-log.md}; seen=0
while :; do
  P=$($PROBE 2>/dev/null | tr -dc '0-9.' | cut -d. -f1); P=${P:--1}
  echo "| $(date '+%Y-%m-%d %H:%M:%S') | ${P}% |" >> "$LOG"
  if [ "$P" -ge "$LIMIT" ] 2>/dev/null; then pkill -f "$MATCH"; echo "| $(date '+%H:%M:%S') | KILLED at ${P}% (limit ${LIMIT}%) |" >> "$LOG"; exit 1; fi
  if pgrep -f "$MATCH" >/dev/null; then seen=1; elif [ "$seen" = 1 ]; then echo "| $(date '+%H:%M:%S') | run finished; guard exiting |" >> "$LOG"; exit 0; fi
  sleep "$EVERY"
done
