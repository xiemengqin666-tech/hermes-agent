#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
HERMES_REPO="${HERMES_REPO:-$HERMES_HOME/hermes-agent}"
PATCH="$ROOT/patches/0001-runtime-experience.patch"
PLUGIN_DIR="$HERMES_HOME/plugins/openclaw-lark-stream"
WEIXIN_PLUGIN_DIR="$HERMES_HOME/plugins/weixin-experience"
SKILL_DIR="$HERMES_HOME/skills/productivity/luckin-cli-ordering"
IONBRIDGE_TEMPLATE="$ROOT/skills/ionbridge-mcp/SKILL.md"
IONBRIDGE_DIR="$HERMES_HOME/skills/openclaw-imports/ionbridge-mcp"
IMPORTED_LARK_DOC_ALIAS="$HERMES_HOME/skills/openclaw-imports/openclaw-lark-doc"
SUPPRESSED="$ROOT/config/suppressed-skills.txt"
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
[[ -f "$WEIXIN_PLUGIN_DIR/__init__.py" && -f "$WEIXIN_PLUGIN_DIR/plugin.yaml" ]] \
  || fail "Hermes Weixin experience plugin is incomplete"
[[ -f "$SKILL_DIR/SKILL.md" ]] || fail "Luckin skill is missing"
[[ -f "$IONBRIDGE_TEMPLATE" ]] || fail "IonBridge recovery skill is missing"
grep -Fq 'configured locally under `mcp_servers.ionbridge`' "$IONBRIDGE_TEMPLATE" \
  || fail "IonBridge recovery skill is not secret-free"
[[ -f "$IONBRIDGE_DIR/SKILL.md" ]] || fail "IonBridge skill is missing"
if [[ -f "$IMPORTED_LARK_DOC_ALIAS/SKILL.md" ]]; then
  grep -Fq 'name: openclaw-lark-doc' "$IMPORTED_LARK_DOC_ALIAS/SKILL.md" \
    || fail "imported lark-doc alias is ambiguous"
fi
[[ ! -d "$HERMES_HOME/plugins/ponytail" ]] || fail "Ponytail plugin is still installed"

verify_suppression() {
  local profile_root="$1"
  local target="$profile_root/skills/.curator_suppressed"
  [[ -f "$target" ]] || fail "skill suppression file is missing at $target"
  while IFS= read -r skill; do
    grep -Fxq "$skill" "$target" || fail "$skill is not suppressed in $profile_root"
    [[ ! -f "$profile_root/skills/software-development/$skill/SKILL.md" ]] \
      || fail "$skill is still active in $profile_root"
  done < "$SUPPRESSED"
}

verify_suppression "$HERMES_HOME"
for profile_root in "$HERMES_HOME"/profiles/*; do
  [[ -d "$profile_root" ]] && verify_suppression "$profile_root"
done

PYTHON="$HERMES_REPO/venv/bin/python"
[[ -x "$PYTHON" ]] || PYTHON="$(command -v python3)"
[[ -n "$PYTHON" ]] || fail "python3 is required"

"$PYTHON" -m py_compile \
  "$PLUGIN_DIR/__init__.py" \
  "$WEIXIN_PLUGIN_DIR/__init__.py" \
  "$SKILL_DIR/scripts/prepare_luckin_order_fast.py" \
  "$SKILL_DIR/scripts/confirm_luckin_order_fast.py" \
  "$SKILL_DIR/scripts/create_luckin_order_fast.py" \
  "$SKILL_DIR/scripts/watch_luckin_order.py"

if [[ -f "$HERMES_HOME/workspace/AGENTS.md" ]]; then
  "$PYTHON" "$ROOT/scripts/normalize_workspace_rules.py" --check \
    "$HERMES_HOME/workspace/AGENTS.md"
fi

if "$PYTHON" -c 'import pytest' >/dev/null 2>&1; then
  TESTS=(
    "$HERMES_REPO/tests/agent/test_account_usage.py"
    "$HERMES_REPO/tests/gateway/test_feishu.py"
    "$HERMES_REPO/tests/gateway/test_incomplete_gateway_turns.py"
    "$HERMES_REPO/tests/gateway/test_weixin.py"
    "$HERMES_REPO/tests/gateway/test_stream_consumer.py"
    "$HERMES_REPO/tests/gateway/test_stream_consumer_tool_progress.py"
    "$HERMES_REPO/tests/gateway/test_stream_consumer_wecom_native.py"
    "$HERMES_REPO/tests/gateway/test_wecom_double_send.py"
    "$HERMES_REPO/tests/gateway/test_wecom_per_turn.py"
    "$HERMES_REPO/tests/gateway/test_wecom_stream_dup_fix.py"
    "$HERMES_REPO/tests/gateway/test_approval_boundary.py"
    "$HERMES_REPO/tests/gateway/test_update_command.py"
    "$HERMES_REPO/tests/gateway/test_update_streaming.py"
    "$HERMES_REPO/tests/gateway/test_update_cron_drain.py"
    "$HERMES_REPO/tests/cron/test_cron_incidents.py"
    "$HERMES_REPO/tests/cron/test_cron_drift_alert_once.py"
    "$HERMES_REPO/tests/hermes_cli/test_update_contract.py"
    "$HERMES_REPO/tests/hermes_cli/test_update_restart_recovery.py"
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
