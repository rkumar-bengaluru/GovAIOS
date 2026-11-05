#!/bin/bash
# Rows 13, 14, 27 probe: PreToolUse command hook. Logs tool name, timing, and whether it can read a
# path that is in sandbox.filesystem.denyRead; then behaves per the "mode" file next to it:
#   log (exit 0) | block (exit 2) | crash (exit 1) | segv (kill -SEGV self) | hang (sleep 30, > timeout)
DIR="$(cd "$(dirname "$0")" && pwd)"
t0=$(python3 -c 'import time; print(time.time())')
input=$(cat)
tool=$(printf '%s' "$input" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("tool_name"), "agent_id=" + str(d.get("agent_id")), "agent_type=" + str(d.get("agent_type")))')
if cat "$DIR/secret.txt" >/dev/null 2>&1; then deny="readable"; else deny="DENIED"; fi
mode=$(cat "$DIR/mode" 2>/dev/null || echo log)
echo "$t0 mode=$mode tool=$tool denyRead_path=$deny ppid=$PPID" >> "$DIR/hook.log"
printf '%s\n' "$input" >> "$DIR/hook-stdin.jsonl"
case "$mode" in
  block) echo "probe: blocked by exit 2" >&2; exit 2 ;;
  crash) exit 1 ;;
  segv) kill -SEGV $$ ;;
  hang) sleep 30 ;;
esac
exit 0
