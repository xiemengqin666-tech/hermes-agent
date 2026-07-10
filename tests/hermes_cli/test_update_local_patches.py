"""Tests for ``hermes update`` local patch overlays."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from hermes_cli import main as hermes_main


def test_apply_update_local_patches_noops_when_dir_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(hermes_main, "_update_local_patches_enabled", lambda: True)

    result = hermes_main._apply_update_local_patches(
        ["git"],
        tmp_path,
        tmp_path / "missing",
    )

    assert result["found"] == 0
    assert result["applied"] == 0
    assert result["skipped"] == 0


def test_apply_update_local_patches_applies_and_then_skips(monkeypatch, tmp_path):
    monkeypatch.setattr(hermes_main, "_update_local_patches_enabled", lambda: True)
    repo = tmp_path / "repo"
    patch_dir = tmp_path / "patches"
    repo.mkdir()
    patch_dir.mkdir()

    def git(*args):
        return subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        )

    git("init", "-q")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    target = repo / "example.txt"
    target.write_text("before\n", encoding="utf-8")
    git("add", "example.txt")
    git("commit", "-qm", "init")

    (patch_dir / "001-example.patch").write_text(
        """diff --git a/example.txt b/example.txt
index 802992c..81b5e71 100644
--- a/example.txt
+++ b/example.txt
@@ -1 +1 @@
-before
+after
""",
        encoding="utf-8",
    )

    first = hermes_main._apply_update_local_patches(["git"], repo, patch_dir)
    second = hermes_main._apply_update_local_patches(["git"], repo, patch_dir)

    assert target.read_text(encoding="utf-8") == "after\n"
    assert first["found"] == 1
    assert first["applied"] == 1
    assert first["skipped"] == 0
    assert second["found"] == 1
    assert second["applied"] == 0
    assert second["skipped"] == 1


def test_revert_update_local_patches_removes_applied_overlay(monkeypatch, tmp_path):
    monkeypatch.setattr(hermes_main, "_update_local_patches_enabled", lambda: True)
    repo = tmp_path / "repo"
    patch_dir = tmp_path / "patches"
    repo.mkdir()
    patch_dir.mkdir()

    def git(*args):
        return subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        )

    git("init", "-q")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    target = repo / "example.txt"
    target.write_text("before\n", encoding="utf-8")
    git("add", "example.txt")
    git("commit", "-qm", "init")
    (patch_dir / "001-example.patch").write_text(
        """diff --git a/example.txt b/example.txt
index 802992c..81b5e71 100644
--- a/example.txt
+++ b/example.txt
@@ -1 +1 @@
-before
+after
""",
        encoding="utf-8",
    )
    hermes_main._apply_update_local_patches(["git"], repo, patch_dir)

    result = hermes_main._revert_update_local_patches_if_applied(
        ["git"],
        repo,
        patch_dir,
    )

    assert result["found"] == 1
    assert result["reverted"] == 1
    assert target.read_text(encoding="utf-8") == "before\n"


def test_apply_update_local_patches_falls_back_to_three_way(monkeypatch, tmp_path):
    monkeypatch.setattr(hermes_main, "_update_local_patches_enabled", lambda: True)
    patch_dir = tmp_path / "patches"
    patch_dir.mkdir()
    (patch_dir / "001.patch").write_text("patch\n", encoding="utf-8")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        joined = " ".join(cmd)
        if "--reverse --check" in joined:
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        if "--check --whitespace=nowarn" in joined and "--3way" not in joined:
            return SimpleNamespace(returncode=1, stdout="", stderr="plain failed")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(hermes_main.subprocess, "run", fake_run)

    result = hermes_main._apply_update_local_patches(["git"], tmp_path, patch_dir)

    assert result["applied"] == 1
    assert any("--3way" in cmd for cmd in calls)


def test_apply_update_local_patches_raises_when_patch_cannot_apply(monkeypatch, tmp_path):
    monkeypatch.setattr(hermes_main, "_update_local_patches_enabled", lambda: True)
    patch_dir = tmp_path / "patches"
    patch_dir.mkdir()
    (patch_dir / "001.patch").write_text("patch\n", encoding="utf-8")

    def fake_run(cmd, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr(hermes_main.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="001.patch: boom"):
        hermes_main._apply_update_local_patches(["git"], tmp_path, patch_dir)


def test_cmd_update_reapplies_overlay_when_no_new_commits_after_pre_revert(
    monkeypatch,
    tmp_path,
):
    """No-update runs must not leave pre-reverted overlays removed."""
    (tmp_path / ".git").mkdir()
    events = []

    monkeypatch.setattr(hermes_main, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(hermes_main, "_run_pre_update_backup", lambda args: None)
    monkeypatch.setattr(hermes_main, "_pause_windows_gateways_for_update", lambda: None)
    monkeypatch.setattr(hermes_main, "_resume_windows_gateways_after_update", lambda token: None)
    monkeypatch.setattr(hermes_main, "_discard_lockfile_churn", lambda *args, **kwargs: None)
    monkeypatch.setattr(hermes_main, "_get_origin_url", lambda *args, **kwargs: hermes_main.OFFICIAL_REPO_URL)
    monkeypatch.setattr(
        hermes_main,
        "_revert_update_local_patches_if_applied",
        lambda *args, **kwargs: events.append("revert") or {"found": 2, "reverted": 2, "dir": "patches"},
    )
    monkeypatch.setattr(hermes_main, "_stash_local_changes_if_needed", lambda *args, **kwargs: None)
    monkeypatch.setattr(hermes_main, "_invalidate_update_cache", lambda: None)
    monkeypatch.setattr(
        hermes_main,
        "_apply_update_local_patches_or_exit",
        lambda *args, **kwargs: events.append("apply") or {"found": 2, "applied": 2, "skipped": 0},
    )
    monkeypatch.setattr(hermes_main, "_venv_core_imports_healthy", lambda: (True, "ok"))

    def fake_run(cmd, **kwargs):
        if cmd == ["git", "fetch", "origin", "main"]:
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        if cmd == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return SimpleNamespace(stdout="main\n", stderr="", returncode=0)
        if cmd == ["git", "rev-list", "HEAD..origin/main", "--count"]:
            return SimpleNamespace(stdout="0\n", stderr="", returncode=0)
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    with patch("shutil.which", return_value=None):
        monkeypatch.setattr(hermes_main.subprocess, "run", fake_run)
        hermes_main.cmd_update(SimpleNamespace())

    assert events == ["revert", "apply"]
