#!/usr/bin/env bash
# Row 13: hook start-up latency. Times N runs of the app binary directly; prints median.
set -euo pipefail
BIN="${1:-dist/gov-aios.app/Contents/MacOS/gov-aios}"
N="${2:-20}"
for _ in $(seq "$N"); do
  s=$(python3 -c 'import time; print(time.perf_counter_ns())')
  "$BIN" selftest lines 1 --dev >/dev/null
  e=$(python3 -c 'import time; print(time.perf_counter_ns())')
  echo $(( (e - s) / 1000000 ))
done | sort -n | awk '{a[NR]=$1} END {printf "runs=%d min=%dms median=%dms max=%dms\n", NR, a[1], (NR%2 ? a[(NR+1)/2] : (a[NR/2]+a[NR/2+1])/2), a[NR]}'
