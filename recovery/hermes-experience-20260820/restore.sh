#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
HERMES_REPO="${HERMES_REPO:-$HERMES_HOME/hermes-agent}"
PATCH="$ROOT/patches/0001-runtime-experience.patch"
PLUGIN_SOURCE="$ROOT/plugins/openclaw-lark-stream"
PLUGIN_DIR="$HERMES_HOME/plugins/openclaw-lark-stream"
SKILL_DIR="$HERMES_HOME/skills/productivity/luckin-cli-ordering"
PATCH_DIR="$HERMES_HOME/update-patches"

fail() {
  printf 'Restore failed: %s\n' "$*" >&2
  exit 1
}

command -v git >/dev/null 2>&1 || fail "git is required"
command -v rsync >/dev/null 2>&1 || fail "rsync is required"
git -C "$HERMES_REPO" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
  || fail "$HERMES_REPO is not a Hermes git checkout"

mkdir -p "$PATCH_DIR"
cp "$PATCH" "$PATCH_DIR/0001-runtime-experience.patch"

if git -C "$HERMES_REPO" apply --check --reverse "$PATCH" >/dev/null 2>&1; then
  printf 'Hermes runtime patch is already applied.\n'
elif git -C "$HERMES_REPO" apply --check "$PATCH" >/dev/null 2>&1; then
  git -C "$HERMES_REPO" apply "$PATCH"
  printf 'Applied Hermes runtime patch.\n'
else
  fail "runtime patch does not match this checkout; refusing a forced apply"
fi

PLUGIN_REPO="$(tr -d '\r\n' < "$PLUGIN_SOURCE/UPSTREAM_REPOSITORY")"
PLUGIN_COMMIT="$(tr -d '\r\n' < "$PLUGIN_SOURCE/UPSTREAM_COMMIT")"
mkdir -p "$(dirname "$PLUGIN_DIR")"

if [[ ! -d "$PLUGIN_DIR/.git" ]]; then
  if [[ -e "$PLUGIN_DIR" ]]; then
    fail "$PLUGIN_DIR exists but is not a git checkout"
  fi
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
rsync -a --delete \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  "$ROOT/skills/luckin-cli-ordering/" "$SKILL_DIR/"

printf 'Restored Feishu wrapper and Luckin ordering skill.\n'
HERMES_HOME="$HERMES_HOME" HERMES_REPO="$HERMES_REPO" "$ROOT/verify.sh"
printf 'Restore verified. Gateway was not restarted.\n'
