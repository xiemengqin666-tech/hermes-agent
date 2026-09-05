#!/usr/bin/env bash
set -euo pipefail

RUN_DIR="$HOME/.hermes/run"
LOG_DIR="$HOME/.hermes/logs/horizon-precompute"
mkdir -p "$RUN_DIR" "$LOG_DIR"

STAMP="$(date +%Y%m%d_%H%M%S)"
LOG="$LOG_DIR/${STAMP}.log"
LOCK_DIR="$RUN_DIR/horizon_ai_news_precompute.lock"
SCRIPT="$HOME/.hermes/scripts/horizon_ai_news_precompute.sh"

if [ -d "$LOCK_DIR" ]; then
  echo "⚠️ Horizon AI news precompute already running"
  echo "lock=$LOCK_DIR"
  echo "latest_log=$(ls -t "$LOG_DIR"/*.log 2>/dev/null | head -1 || true)"
  exit 0
fi

PID="$(
  python3 - "$LOCK_DIR" "$SCRIPT" "$LOG" <<'PY'
import pathlib
import subprocess
import sys

lock_dir, script, log_path = sys.argv[1:]
pathlib.Path(log_path).parent.mkdir(parents=True, exist_ok=True)

cmd = [
    "/bin/bash",
    "-lc",
    r'''
set -euo pipefail
LOCK_DIR="$1"
SCRIPT="$2"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "⚠️ lock exists, another precompute is running: $LOCK_DIR"
  exit 0
fi
trap "rmdir \"$LOCK_DIR\" 2>/dev/null || true" EXIT
"$SCRIPT"
''',
    "_",
    lock_dir,
    script,
]

with open(log_path, "ab", buffering=0) as log:
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        close_fds=True,
    )
print(proc.pid)
PY
)"

echo "✅ Horizon AI news precompute started in background"
echo "pid=$PID"
echo "log=$LOG"
echo "lock=$LOCK_DIR"
