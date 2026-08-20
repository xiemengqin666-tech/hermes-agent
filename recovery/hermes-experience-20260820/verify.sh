#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
HERMES_REPO="${HERMES_REPO:-$HERMES_HOME/hermes-agent}"
PATCH="$ROOT/patches/0001-runtime-experience.patch"
PLUGIN_DIR="$HERMES_HOME/plugins/openclaw-lark-stream"
SKILL_DIR="$HERMES_HOME/skills/productivity/luckin-cli-ordering"
PLUGIN_COMMIT="$(tr -d '\r\n' < "$ROOT/plugins/openclaw-lark-stream/UPSTREAM_COMMIT")"

fail() {
  printf 'Verification failed: %s\n' "$*" >&2
  exit 1
}

(cd "$ROOT" && shasum -a 256 -c checksums.sha256)

git -C "$HERMES_REPO" apply --check --reverse "$PATCH" >/dev/null 2>&1 \
  || fail "Hermes runtime patch is not fully applied"
[[ -d "$PLUGIN_DIR/.git" ]] || fail "Feishu stream source is missing"
[[ "$(git -C "$PLUGIN_DIR" rev-parse HEAD)" == "$PLUGIN_COMMIT" ]] \
  || fail "Feishu stream source is not pinned to $PLUGIN_COMMIT"
[[ -f "$PLUGIN_DIR/__init__.py" && -f "$PLUGIN_DIR/plugin.yaml" ]] \
  || fail "Hermes Feishu wrapper is incomplete"
[[ -f "$SKILL_DIR/SKILL.md" ]] || fail "Luckin skill is missing"

PYTHON="$HERMES_REPO/venv/bin/python"
[[ -x "$PYTHON" ]] || PYTHON="$(command -v python3)"
[[ -n "$PYTHON" ]] || fail "python3 is required"

"$PYTHON" -m py_compile \
  "$PLUGIN_DIR/__init__.py" \
  "$SKILL_DIR/scripts/create_luckin_order_fast.py" \
  "$SKILL_DIR/scripts/watch_luckin_order.py"

if "$PYTHON" -c 'import pytest' >/dev/null 2>&1; then
  TESTS=(
    "$HERMES_REPO/tests/gateway/test_feishu.py"
    "$HERMES_REPO/tests/gateway/test_weixin.py"
    "$HERMES_REPO/tests/gateway/test_update_command.py"
    "$HERMES_REPO/tests/hermes_cli/test_update_wedged_gateway.py"
    "$HERMES_REPO/tests/agent/test_account_usage.py"
    "$SKILL_DIR/tests/test_delivery_manifest.py"
  )
  if [[ -f "$HERMES_HOME/plugins/weixin-experience/tests/test_luckin_qr_recovery.py" ]]; then
    TESTS+=("$HERMES_HOME/plugins/weixin-experience/tests/test_luckin_qr_recovery.py")
  fi
  (cd "$HERMES_REPO" && PYTHONPATH="$HERMES_REPO" "$PYTHON" -m pytest -q "${TESTS[@]}")
else
  printf 'pytest is unavailable; syntax and integrity checks passed.\n'
fi

printf 'All available recovery checks passed.\n'
