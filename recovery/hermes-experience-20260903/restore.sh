#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
HERMES_REPO="${HERMES_REPO:-$HERMES_HOME/hermes-agent}"
PATCH="$ROOT/patches/0001-runtime-experience.patch"
PLUGIN_SOURCE="$ROOT/plugins/openclaw-lark-stream"
PLUGIN_DIR="$HERMES_HOME/plugins/openclaw-lark-stream"
WEIXIN_PLUGIN_SOURCE="$ROOT/plugins/weixin-experience"
WEIXIN_PLUGIN_DIR="$HERMES_HOME/plugins/weixin-experience"
SKILL_DIR="$HERMES_HOME/skills/productivity/luckin-cli-ordering"
IONBRIDGE_SOURCE="$ROOT/skills/ionbridge-mcp"
IONBRIDGE_DIR="$HERMES_HOME/skills/openclaw-imports/ionbridge-mcp"
IMPORTED_LARK_DOC="$HERMES_HOME/skills/openclaw-imports/lark-doc"
IMPORTED_LARK_DOC_ALIAS="$HERMES_HOME/skills/openclaw-imports/openclaw-lark-doc"
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

if git -C "$HERMES_REPO" apply --check --reverse "$PATCH" >/dev/null 2>&1; then
  printf 'Hermes runtime overlay is already applied.\n'
elif git -C "$HERMES_REPO" apply --check "$PATCH" >/dev/null 2>&1; then
  git -C "$HERMES_REPO" apply "$PATCH"
  printf 'Applied Hermes runtime overlay.\n'
else
  fail "runtime overlay does not match this checkout; refusing a forced apply"
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
for profile_root in "$HERMES_HOME"/profiles/*; do
  [[ -d "$profile_root" ]] || continue
  profile_ionbridge="$profile_root/skills/openclaw-imports/ionbridge-mcp"
  mkdir -p "$profile_ionbridge"
  rsync -a --delete "$IONBRIDGE_SOURCE/" "$profile_ionbridge/"
done

if [[ -d "$IMPORTED_LARK_DOC" && ! -e "$IMPORTED_LARK_DOC_ALIAS" ]]; then
  mv "$IMPORTED_LARK_DOC" "$IMPORTED_LARK_DOC_ALIAS"
fi
if [[ -f "$IMPORTED_LARK_DOC_ALIAS/SKILL.md" ]]; then
  perl -0pi -e 's/^name:\s*lark-doc\s*$/name: openclaw-lark-doc/m' \
    "$IMPORTED_LARK_DOC_ALIAS/SKILL.md"
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
    rm -rf \
      "$profile_root/skills/software-development/$skill" \
      "$profile_root/skills/imported-agent-skills/$skill"
  done < "$SUPPRESSED"
}

install_suppression "$HERMES_HOME"
for profile_root in "$HERMES_HOME"/profiles/*; do
  [[ -d "$profile_root" ]] && install_suppression "$profile_root"
done
rm -rf "$HERMES_HOME/plugins/ponytail"
rm -f "$HERMES_HOME/workspace/ponytail_append.md"
if [[ -f "$HERMES_HOME/workspace/AGENTS.md" ]]; then
  python3 "$ROOT/scripts/normalize_workspace_rules.py" \
    "$HERMES_HOME/workspace/AGENTS.md"
fi

printf 'Restored messaging overlays, skills, aliases, and workspace rules.\n'
HERMES_HOME="$HERMES_HOME" HERMES_REPO="$HERMES_REPO" "$ROOT/verify.sh"
printf 'Restore verified. Gateway was not restarted.\n'
