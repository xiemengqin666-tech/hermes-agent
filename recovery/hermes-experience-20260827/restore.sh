#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
HERMES_REPO="${HERMES_REPO:-$HERMES_HOME/hermes-agent}"
PATCH="$ROOT/patches/0001-runtime-experience.patch"
PLUGIN_SOURCE="$ROOT/plugins/openclaw-lark-stream"
PLUGIN_DIR="$HERMES_HOME/plugins/openclaw-lark-stream"
SKILL_DIR="$HERMES_HOME/skills/productivity/luckin-cli-ordering"
SUPPRESSED="$ROOT/config/suppressed-skills.txt"

fail() {
  printf 'Restore failed: %s\n' "$*" >&2
  exit 1
}

command -v git >/dev/null 2>&1 || fail "git is required"
command -v rsync >/dev/null 2>&1 || fail "rsync is required"
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
mkdir -p "$SKILL_DIR"
rsync -a --delete --exclude '__pycache__/' --exclude '*.pyc' \
  "$ROOT/skills/luckin-cli-ordering/" "$SKILL_DIR/"

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

printf 'Restored messaging overlay, Feishu wrapper, Luckin workflow, and skill suppressions.\n'
HERMES_HOME="$HERMES_HOME" HERMES_REPO="$HERMES_REPO" "$ROOT/verify.sh"
printf 'Restore verified. Gateway was not restarted.\n'
