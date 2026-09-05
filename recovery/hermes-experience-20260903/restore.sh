#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
HERMES_REPO="${HERMES_REPO:-$HERMES_HOME/hermes-agent}"
PATCHES=(
  "$ROOT/patches/0001-runtime-experience-f98f5e7.patch"
  "$ROOT/patches/0002-runtime-experience-f58fcc8.patch"
)
PLUGIN_SOURCE="$ROOT/plugins/openclaw-lark-stream"
PLUGIN_DIR="$HERMES_HOME/plugins/openclaw-lark-stream"
WEIXIN_PLUGIN_SOURCE="$ROOT/plugins/weixin-experience"
WEIXIN_PLUGIN_DIR="$HERMES_HOME/plugins/weixin-experience"
SKILL_DIR="$HERMES_HOME/skills/productivity/luckin-cli-ordering"
IONBRIDGE_SOURCE="$ROOT/skills/ionbridge-mcp"
IONBRIDGE_DIR="$HERMES_HOME/skills/openclaw-imports/ionbridge-mcp"
RUNTIME_SCRIPTS_SOURCE="$ROOT/runtime-scripts"
RUNTIME_SCRIPTS_DIR="$HERMES_HOME/scripts"
LEGACY_COLLAB_PROFILES=(agencydev agencyresearch agencyreview agencysynth)
SUPPRESSED="$ROOT/config/suppressed-skills.txt"

fail() {
  printf 'Restore failed: %s\n' "$*" >&2
  exit 1
}

command -v git >/dev/null 2>&1 || fail "git is required"
command -v rsync >/dev/null 2>&1 || fail "rsync is required"
command -v python3 >/dev/null 2>&1 || fail "python3 is required"
git -C "$HERMES_REPO" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
  || fail "$HERMES_REPO is not a Hermes git checkout"

PATCH=""
PATCH_ALREADY_APPLIED=false
for candidate in "${PATCHES[@]}"; do
  if git -C "$HERMES_REPO" apply --check --reverse "$candidate" >/dev/null 2>&1; then
    PATCH="$candidate"
    PATCH_ALREADY_APPLIED=true
    break
  fi
done
if [[ -z "$PATCH" ]]; then
  for candidate in "${PATCHES[@]}"; do
    if git -C "$HERMES_REPO" apply --check "$candidate" >/dev/null 2>&1; then
      PATCH="$candidate"
      break
    fi
  done
fi
[[ -n "$PATCH" ]] \
  || fail "no verified runtime overlay matches this checkout; refusing a forced apply"

if [[ "$PATCH_ALREADY_APPLIED" == true ]]; then
  printf 'Hermes runtime overlay is already applied.\n'
else
  git -C "$HERMES_REPO" apply "$PATCH"
  printf 'Applied Hermes runtime overlay: %s\n' "$(basename "$PATCH")"
fi

PLUGIN_REPO="$(tr -d '\r\n' < "$PLUGIN_SOURCE/UPSTREAM_REPOSITORY")"
PLUGIN_COMMIT="$(tr -d '\r\n' < "$PLUGIN_SOURCE/UPSTREAM_COMMIT")"
mkdir -p "$(dirname "$PLUGIN_DIR")"

if [[ ! -d "$PLUGIN_DIR/.git" ]]; then
  [[ ! -e "$PLUGIN_DIR" ]] || fail "$PLUGIN_DIR exists but is not a git checkout"
  git clone "$PLUGIN_REPO" "$PLUGIN_DIR"
fi

if ! git -C "$PLUGIN_DIR" cat-file -e "$PLUGIN_COMMIT^{commit}" 2>/dev/null; then
  git -C "$PLUGIN_DIR" fetch origin "$PLUGIN_COMMIT"
fi

if [[ "$(git -C "$PLUGIN_DIR" rev-parse HEAD)" != "$PLUGIN_COMMIT" ]]; then
  [[ -z "$(git -C "$PLUGIN_DIR" status --porcelain --untracked-files=no)" ]] \
    || fail "tracked Feishu plugin files are modified; refusing to overwrite them"
  git -C "$PLUGIN_DIR" checkout --detach "$PLUGIN_COMMIT"
fi

cp "$PLUGIN_SOURCE/__init__.py" "$PLUGIN_DIR/__init__.py"
cp "$PLUGIN_SOURCE/plugin.yaml" "$PLUGIN_DIR/plugin.yaml"
mkdir -p "$WEIXIN_PLUGIN_DIR/tests"
cp "$WEIXIN_PLUGIN_SOURCE/__init__.py" "$WEIXIN_PLUGIN_DIR/__init__.py"
cp "$WEIXIN_PLUGIN_SOURCE/plugin.yaml" "$WEIXIN_PLUGIN_DIR/plugin.yaml"
cp "$WEIXIN_PLUGIN_SOURCE/tests/test_luckin_qr_recovery.py" \
  "$WEIXIN_PLUGIN_DIR/tests/test_luckin_qr_recovery.py"
mkdir -p "$SKILL_DIR"
rsync -a --delete --exclude '__pycache__/' --exclude '*.pyc' \
  "$ROOT/skills/luckin-cli-ordering/" "$SKILL_DIR/"
mkdir -p "$IONBRIDGE_DIR"
rsync -a --delete "$IONBRIDGE_SOURCE/" "$IONBRIDGE_DIR/"
mkdir -p "$RUNTIME_SCRIPTS_DIR"
rsync -a "$RUNTIME_SCRIPTS_SOURCE/" "$RUNTIME_SCRIPTS_DIR/"

for profile in "${LEGACY_COLLAB_PROFILES[@]}"; do
  profile_root="$HERMES_HOME/profiles/$profile"
  [[ ! -e "$profile_root" ]] || find "$profile_root" -depth -delete
done

if [[ ! -f "$HOME/.agents/skills/lark-shared/SKILL.md" \
   || ! -f "$HOME/.agents/skills/lark-doc/SKILL.md" \
   || ! -f "$HOME/.agents/skills/lark-im/SKILL.md" ]]; then
  command -v npx >/dev/null 2>&1 || fail "npx is required to install official Lark skills"
  npx -y skills add larksuite/cli -g -y
fi

install_suppression() {
  local profile_root="$1"
  local target="$profile_root/skills/.curator_suppressed"
  local merged
  mkdir -p "$(dirname "$target")"
  merged="$(mktemp)"
  { [[ -f "$target" ]] && cat "$target"; cat "$SUPPRESSED"; } \
    | awk 'NF && !seen[$0]++' | sort > "$merged"
  mv "$merged" "$target"
  while IFS= read -r skill; do
    for path in \
      "$profile_root/skills/software-development/$skill" \
      "$profile_root/skills/imported-agent-skills/$skill"; do
      [[ ! -e "$path" ]] || find "$path" -depth -delete
    done
  done < "$SUPPRESSED"
}

install_suppression "$HERMES_HOME"
[[ ! -e "$HERMES_HOME/plugins/ponytail" ]] \
  || find "$HERMES_HOME/plugins/ponytail" -depth -delete
find "$HERMES_HOME/workspace" -maxdepth 1 -type f -name ponytail_append.md -delete 2>/dev/null || true
if [[ -f "$HERMES_HOME/workspace/AGENTS.md" ]]; then
  python3 "$ROOT/scripts/normalize_workspace_rules.py" \
    "$HERMES_HOME/workspace/AGENTS.md" --souls-home "$HERMES_HOME"
fi

PYTHON="$HERMES_REPO/venv/bin/python"
[[ -x "$PYTHON" ]] || PYTHON="$(command -v python3)"
"$PYTHON" "$ROOT/scripts/normalize_profile_settings.py" --home "$HERMES_HOME"
"$PYTHON" "$ROOT/scripts/configure_skills.py" \
  --home "$HERMES_HOME" --hermes-repo "$HERMES_REPO"
if [[ -f "$HERMES_HOME/cron/jobs.json" ]]; then
  HERMES_HOME="$HERMES_HOME" PYTHONPATH="$HERMES_REPO" \
    "$PYTHON" "$ROOT/scripts/normalize_cron_jobs.py" \
    --hermes-repo "$HERMES_REPO"
fi

printf 'Restored messaging overlays, cron guardrails, selected skills, runtime scripts, and workspace rules.\n'
HERMES_HOME="$HERMES_HOME" HERMES_REPO="$HERMES_REPO" "$ROOT/verify.sh"
printf 'Restore verified. Gateway was not restarted.\n'
