#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
HERMES_REPO="${HERMES_REPO:-$HERMES_HOME/hermes-agent}"
PATCHES=(
  "$ROOT/patches/0001-runtime-experience-f98f5e7.patch"
  "$ROOT/patches/0002-runtime-experience-c3e9b28.patch"
)
PLUGIN_DIR="$HERMES_HOME/plugins/openclaw-lark-stream"
WEIXIN_PLUGIN_DIR="$HERMES_HOME/plugins/weixin-experience"
SKILL_DIR="$HERMES_HOME/skills/productivity/luckin-cli-ordering"
IONBRIDGE_TEMPLATE="$ROOT/skills/ionbridge-mcp/SKILL.md"
IONBRIDGE_DIR="$HERMES_HOME/skills/openclaw-imports/ionbridge-mcp"
AI_NEWS_DIR="$HERMES_HOME/skills/openclaw-imports/ai-news-workflow"
IMPORTED_LARK_DOC_ALIAS="$HERMES_HOME/skills/openclaw-imports/openclaw-lark-doc"
SUPPRESSED="$ROOT/config/suppressed-skills.txt"
PLUGIN_COMMIT="$(tr -d '\r\n' < "$ROOT/plugins/openclaw-lark-stream/UPSTREAM_COMMIT")"

fail() {
  printf 'Verification failed: %s\n' "$*" >&2
  exit 1
}

(cd "$ROOT" && shasum -a 256 -c checksums.sha256)

PATCH=""
for candidate in "${PATCHES[@]}"; do
  if git -C "$HERMES_REPO" apply --check --reverse "$candidate" >/dev/null 2>&1; then
    PATCH="$candidate"
    break
  fi
done
[[ -n "$PATCH" ]] || fail "no supported Hermes runtime patch is fully applied"
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
[[ -f "$AI_NEWS_DIR/SKILL.md" ]] || fail "AI news workflow skill is missing"
grep -Fq '不得主动拆成多条消息' "$AI_NEWS_DIR/SKILL.md" \
  || fail "AI news workflow lost its single-card delivery rule"
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

PYTHON="${HERMES_PYTHON:-$HERMES_REPO/venv/bin/python}"
if [[ ! -x "$PYTHON" && -x "$HERMES_HOME/hermes-agent/venv/bin/python" ]]; then
  PYTHON="$HERMES_HOME/hermes-agent/venv/bin/python"
fi
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

if [[ -f "$HERMES_HOME/cron/jobs.json" ]]; then
  HERMES_HOME="$HERMES_HOME" PYTHONPATH="$HERMES_REPO" \
    "$PYTHON" "$ROOT/scripts/normalize_cron_jobs.py" --check \
    --hermes-repo "$HERMES_REPO"
fi

if "$PYTHON" -c 'import pytest' >/dev/null 2>&1; then
  TEST_CANDIDATES=(
    "$HERMES_REPO/tests/agent/test_account_usage.py"
    "$HERMES_REPO/tests/gateway/test_feishu.py"
    "$HERMES_REPO/tests/gateway/test_incomplete_gateway_turns.py"
    "$HERMES_REPO/tests/gateway/test_weixin.py"
    "$HERMES_REPO/tests/gateway/test_weixin_typing.py"
    "$HERMES_REPO/tests/gateway/test_update_command.py"
    "$HERMES_REPO/tests/gateway/test_update_streaming.py"
    "$HERMES_REPO/tests/gateway/test_update_cron_drain.py"
    "$HERMES_REPO/tests/cron/test_cron_failure_deliver.py"
    "$HERMES_REPO/tests/hermes_cli/test_companion_cli_updates.py"
    "$SKILL_DIR/tests/test_delivery_manifest.py"
  )
  TESTS=()
  for candidate in "${TEST_CANDIDATES[@]}"; do
    [[ -f "$candidate" ]] && TESTS+=("$candidate")
  done
  if grep -Fq 'test_failed_job_uses_explicit_failure_delivery_target' \
    "$HERMES_REPO/tests/cron/test_scheduler.py" 2>/dev/null; then
    TESTS+=(
      "$HERMES_REPO/tests/cron/test_scheduler.py::TestSilentDelivery::test_failed_job_uses_explicit_failure_delivery_target"
    )
  fi
  if [[ -f "$HERMES_HOME/plugins/weixin-experience/tests/test_luckin_qr_recovery.py" ]]; then
    TESTS+=("$HERMES_HOME/plugins/weixin-experience/tests/test_luckin_qr_recovery.py")
  fi
  PYTEST_ARGS=(-q)
  if grep -Fq 'test_concurrent_dedup_persists_land_in_order' \
    "$HERMES_REPO/tests/gateway/test_feishu.py" 2>/dev/null; then
    # This upstream test clears HOME/HERMES_HOME and consequently reads the
    # operator's real ~/.hermes dedup state. Keep runtime tests hermetic by
    # excluding only that environment-isolation defect.
    PYTEST_ARGS+=(
      "--deselect=tests/gateway/test_feishu.py::TestDedupTTL::test_concurrent_dedup_persists_land_in_order"
    )
  fi
  TEST_HOME="$(mktemp -d)"
  trap 'rm -rf "$TEST_HOME"' EXIT
  (
    cd "$HERMES_REPO"
    HERMES_HOME="$TEST_HOME" PYTHONPATH="$HERMES_REPO" \
      "$PYTHON" -m pytest "${PYTEST_ARGS[@]}" "${TESTS[@]}"
  )
else
  printf 'pytest is unavailable; syntax and integrity checks passed.\n'
fi

printf 'All available recovery checks passed.\n'
