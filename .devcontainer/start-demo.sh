#!/usr/bin/env bash
# postStartCommand (P28 track PD; REQ-FND-04): start the public demo's supervisor in the background, detached from
# this short-lived shell, with its output in ~/demo.log. Idempotent: a supervisor that is already running is kept.
# Each boot starts from empty data with new throwaway secrets (infra/demo/space/run.py).
set -euo pipefail

run_py=/opt/infra/demo/space/run.py
log="${HOME}/demo.log"
pidfile="${HOME}/run.pid"

if [ -f "$pidfile" ]; then
  pid="$(cat "$pidfile")"
  if [ -r "/proc/${pid}/cmdline" ] && tr '\0' ' ' < "/proc/${pid}/cmdline" | grep -q "$run_py"; then
    echo "demo: already running (pid ${pid}); log: ${log}"
    exit 0
  fi
fi

setsid nohup python3 "$run_py" >> "$log" 2>&1 < /dev/null &
echo "demo: starting in the background (about a minute until the site answers); follow it with: tail -f ${log}"
