#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
HERMES_REPO="${HERMES_REPO:-$HERMES_HOME/hermes-agent}"
PATCHES=(
  "$ROOT/patches/0003-runtime-experience-d20a8e4.patch"
  "$ROOT/patches/0001-runtime-experience-f98f5e7.patch"
  "$ROOT/patches/0002-runtime-experience-f58fcc8.patch"
)
PLUGIN_DIR="$HERMES_HOME/plugins/openclaw-lark-stream"
WEIXIN_PLUGIN_DIR="$HERMES_HOME/plugins/weixin-experience"
SKILL_DIR="$HERMES_HOME/skills/productivity/luckin-cli-ordering"
IONBRIDGE_TEMPLATE="$ROOT/skills/ionbridge-mcp/SKILL.md"
IONBRIDGE_DIR="$HERMES_HOME/skills/openclaw-imports/ionbridge-mcp"
RUNTIME_SCRIPTS_DIR="$HERMES_HOME/scripts"
LEGACY_COLLAB_PROFILES=(agencydev agencyresearch agencyreview agencysynth)
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
[[ ! -d "$HERMES_HOME/plugins/ponytail" ]] || fail "Ponytail plugin is still installed"
for profile in "${LEGACY_COLLAB_PROFILES[@]}"; do
  [[ ! -e "$HERMES_HOME/profiles/$profile" ]] \
    || fail "legacy collaboration profile is still installed: $profile"
done

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

PYTHON="${HERMES_PYTHON:-$HERMES_REPO/venv/bin/python}"
if [[ ! -x "$PYTHON" && -x "$HERMES_HOME/hermes-agent/venv/bin/python" ]]; then
  PYTHON="$HERMES_HOME/hermes-agent/venv/bin/python"
fi
[[ -x "$PYTHON" ]] || PYTHON="$(command -v python3)"
[[ -n "$PYTHON" ]] || fail "python3 is required"

"$PYTHON" "$ROOT/scripts/normalize_profile_settings.py" \
  --home "$HERMES_HOME" --check

"$PYTHON" "$ROOT/scripts/configure_skills.py" --check \
  --home "$HERMES_HOME" --hermes-repo "$HERMES_REPO"

"$PYTHON" "$ROOT/scripts/verify_browser_routing.py" \
  --home "$HERMES_HOME" --hermes-repo "$HERMES_REPO"

"$PYTHON" -m py_compile \
  "$PLUGIN_DIR/__init__.py" \
  "$WEIXIN_PLUGIN_DIR/__init__.py" \
  "$RUNTIME_SCRIPTS_DIR/ai_news_rss.py" \
  "$RUNTIME_SCRIPTS_DIR/codex_usage_query.py" \
  "$RUNTIME_SCRIPTS_DIR/horizon_ai_news_collect.py" \
  "$RUNTIME_SCRIPTS_DIR/horizon_ai_news_context.py" \
  "$RUNTIME_SCRIPTS_DIR/horizon_ai_news_context_fast.py" \
  "$RUNTIME_SCRIPTS_DIR/horizon_company_news_context.py" \
  "$RUNTIME_SCRIPTS_DIR/us_stock_market_data.py" \
  "$SKILL_DIR/scripts/prepare_luckin_order_fast.py" \
  "$SKILL_DIR/scripts/confirm_luckin_order_fast.py" \
  "$SKILL_DIR/scripts/create_luckin_order_fast.py" \
  "$SKILL_DIR/scripts/watch_luckin_order.py"
bash -n \
  "$RUNTIME_SCRIPTS_DIR/horizon_ai_news_precompute.sh" \
  "$RUNTIME_SCRIPTS_DIR/horizon_ai_news_precompute_detached.sh"
for source in "$ROOT"/runtime-scripts/*; do
  target="$RUNTIME_SCRIPTS_DIR/$(basename "$source")"
  cmp -s "$source" "$target" \
    || fail "runtime script differs from the recovery copy: $(basename "$source")"
done

if [[ -f "$HERMES_HOME/workspace/AGENTS.md" ]]; then
  "$PYTHON" "$ROOT/scripts/normalize_workspace_rules.py" --check \
    "$HERMES_HOME/workspace/AGENTS.md" --souls-home "$HERMES_HOME"
fi

if [[ -f "$HERMES_HOME/cron/jobs.json" ]]; then
  HERMES_HOME="$HERMES_HOME" PYTHONPATH="$HERMES_REPO" \
    "$PYTHON" "$ROOT/scripts/normalize_cron_jobs.py" --check \
    --hermes-repo "$HERMES_REPO"
fi

if "$PYTHON" -c 'import pytest' >/dev/null 2>&1; then
  TEST_CANDIDATES=(
    "$HERMES_REPO/tests/agent/transports/test_codex_transport.py"
    "$HERMES_REPO/tests/agent/test_account_usage.py"
    "$HERMES_REPO/tests/agent/test_coding_context.py"
    "$HERMES_REPO/tests/agent/test_runtime_cwd.py"
    "$HERMES_REPO/tests/agent/test_system_prompt.py"
    "$HERMES_REPO/tests/agent/test_verification_evidence.py"
    "$HERMES_REPO/tests/agent/test_verification_stop.py"
    "$HERMES_REPO/tests/gateway/test_stream_consumer.py"
    "$HERMES_REPO/tests/gateway/test_channel_compression_override.py"
    "$HERMES_REPO/tests/gateway/test_feishu.py"
    "$HERMES_REPO/tests/gateway/test_incomplete_gateway_turns.py"
    "$HERMES_REPO/tests/gateway/test_weixin.py"
    "$HERMES_REPO/tests/gateway/test_weixin_typing.py"
    "$HERMES_REPO/tests/gateway/test_update_command.py"
    "$HERMES_REPO/tests/gateway/test_update_streaming.py"
    "$HERMES_REPO/tests/gateway/test_update_cron_drain.py"
    "$HERMES_REPO/tests/gateway/test_run_progress_topics.py"
    "$HERMES_REPO/tests/gateway/test_queued_native_image_session_key.py"
    "$HERMES_REPO/tests/cron/test_cron_failure_deliver.py"
    "$HERMES_REPO/tests/hermes_cli/test_companion_cli_updates.py"
    "$HERMES_REPO/tests/hermes_cli/test_gateway_proc_fallback.py"
    "$HERMES_REPO/tests/hermes_cli/test_restart_plan_reconciliation.py"
    "$HERMES_REPO/tests/hermes_cli/test_tui_resume_flow.py"
    "$HERMES_REPO/tests/hermes_cli/test_update_inventory.py"
    "$HERMES_REPO/tests/tools/test_delegate_sync_platform.py"
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
  if [[ -f "$HERMES_REPO/tests/hermes_cli/test_update_fleet_restart_pending.py" ]]; then
    TESTS+=(
      "$HERMES_REPO/tests/hermes_cli/test_update_fleet_restart_pending.py::test_pending_restart_does_not_stop_fresh_supervised_gateway"
      "$HERMES_REPO/tests/hermes_cli/test_update_fleet_restart_pending.py::test_pending_restart_stops_only_original_survivor"
    )
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
  trap 'find "$TEST_HOME" -depth -delete 2>/dev/null || true' EXIT
  (
    cd "$HERMES_REPO"
    HERMES_HOME="$TEST_HOME" PYTHONPATH="$HERMES_REPO" \
      "$PYTHON" -m pytest "${PYTEST_ARGS[@]}" "${TESTS[@]}"
  )
else
  printf 'pytest is unavailable; syntax and integrity checks passed.\n'
fi

printf 'All available recovery checks passed.\n'
