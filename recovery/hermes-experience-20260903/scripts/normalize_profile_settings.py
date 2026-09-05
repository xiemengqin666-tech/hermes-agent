#!/usr/bin/env python3
"""Normalize secret-free Hermes profile settings preserved by this snapshot."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from dotenv import dotenv_values, set_key
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap


EXPECTED: dict[str, Any] = {
    "model.default": "gpt-6-astra",
    "model.provider": "openai-codex",
    "agent.max_turns": 200,
    "agent.service_tier": "normal",
    "agent.reasoning_effort": "medium",
    "agent.coding_context": "auto",
    "agent.task_completion_guidance": True,
    "agent.parallel_tool_call_guidance": True,
    "agent.environment_probe": True,
    "agent.verify_on_stop": "auto",
    "agent.max_verify_nudges": 2,
    "agent.verify_guidance": False,
    "agent.coding_instructions": (
        "For coding tasks, read the repository instructions and git status first. "
        "Use explicit absolute paths and terminal cwd for the target repository; "
        "do not assume the CLI directory changes the configured terminal cwd. "
        "Use CodeGraph for indexed symbol/call-flow questions and rg for literal text. "
        "Implement narrow changes with patch tools, preserve unrelated user edits, "
        "and run focused tests before reporting completion. For UI changes, inspect "
        "the rendered result using Microsoft Edge only. Delegate only independent "
        "work and wait for required results; do not delegate simple fixes. Report "
        "actual changes, verification results and blockers concisely, without "
        "pasting code unless requested. After verification follow-ups, summarize "
        "the original task's changes as well as the checks. Never restart services or publish changes "
        "unless required by the user's task."
    ),
    "compression.enabled": True,
    "compression.threshold": 0.75,
    "compression.target_ratio": 0.2,
    "auxiliary.compression.provider": "openai-codex",
    "auxiliary.compression.model": "gpt-6-astra",
    "auxiliary.title_generation.provider": "openai-codex",
    "auxiliary.title_generation.model": "gpt-6-astra",
    "auxiliary.triage_specifier.provider": "openai-codex",
    "auxiliary.triage_specifier.model": "gpt-6-astra",
    "auxiliary.kanban_decomposer.provider": "openai-codex",
    "auxiliary.kanban_decomposer.model": "gpt-6-astra",
    "delegation.provider": "openai-codex",
    "delegation.model": "gpt-6-astra",
    "delegation.reasoning_effort": "medium",
    "goals.max_turns": 200,
    "approvals.mode": "off",
    "session_reset.mode": "none",
    # Unset backend selects Browser Use, which ignores the Edge executable pin.
    "browser.backend": "off",
    "browser.cloud_provider": "local",
    "browser.use_real_profile": False,
    "browser.cdp_url": "",
}

EDGE = "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
ENV_EXPECTED = {
    "HERMES_BROWSER_EDGE_ONLY": "true",
    "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1",
    "AGENT_BROWSER_EXECUTABLE_PATH": EDGE,
    "PUPPETEER_EXECUTABLE_PATH": EDGE,
    "CHROME_PATH": EDGE,
    "BROWSER": "open -a Microsoft Edge",
}


def _get(data: Any, dotted: str) -> Any:
    value = data
    for part in dotted.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    return value


def _set(data: CommentedMap, dotted: str, value: Any) -> None:
    current = data
    parts = dotted.split(".")
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = CommentedMap()
            current[part] = child
        current = child
    current[parts[-1]] = value


def _config_paths(home: Path) -> list[Path]:
    return [home / "config.yaml", *sorted((home / "profiles").glob("*/config.yaml"))]


def _conversation_routes(data: dict):
    roots = [data.get("feishu", {}), data.get("weixin", {})]
    for platform in (data.get("platforms") or {}).values():
        if isinstance(platform, dict):
            roots.extend((platform, platform.get("extra") or {}))
    for root in roots:
        if not isinstance(root, dict):
            continue
        for route in (root.get("channel_model_overrides") or {}).values():
            if isinstance(route, dict):
                yield route
        if isinstance(root.get("default_model"), dict):
            yield root["default_model"]


def _collect_errors(home: Path) -> list[str]:
    yaml = YAML(typ="safe")
    errors: list[str] = []
    for path in _config_paths(home):
        data = yaml.load(path.read_text(encoding="utf-8")) or {}
        for dotted, wanted in EXPECTED.items():
            value = _get(data, dotted)
            if value != wanted:
                errors.append(f"{path}: {dotted}={value!r}, expected {wanted!r}")
        for route in _conversation_routes(data):
            if route.get("model") != EXPECTED["model.default"] or route.get("provider") != "openai-codex":
                errors.append(f"{path}: a conversation route does not match the default model/provider")

        env_path = path.parent / ".env"
        values = dotenv_values(env_path)
        for key, wanted in ENV_EXPECTED.items():
            if values.get(key) != wanted:
                errors.append(f"{env_path}: {key}={values.get(key)!r}, expected {wanted!r}")
    return errors


def _normalize(home: Path) -> None:
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096
    for path in _config_paths(home):
        with path.open(encoding="utf-8") as handle:
            data = yaml.load(handle) or CommentedMap()
        changed = False
        for dotted, wanted in EXPECTED.items():
            if _get(data, dotted) != wanted:
                _set(data, dotted, wanted)
                changed = True
        for route in _conversation_routes(data):
            for key, wanted in (("model", EXPECTED["model.default"]), ("provider", "openai-codex")):
                if route.get(key) != wanted:
                    route[key] = wanted
                    changed = True
        if changed:
            with path.open("w", encoding="utf-8") as handle:
                yaml.dump(data, handle)

        env_path = path.parent / ".env"
        env_path.touch(exist_ok=True)
        values = dotenv_values(env_path)
        for key, wanted in ENV_EXPECTED.items():
            if values.get(key) != wanted:
                set_key(str(env_path), key, wanted, quote_mode="auto")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    if not args.check:
        _normalize(args.home)
    errors = _collect_errors(args.home)
    if errors:
        raise SystemExit("Profile alignment failed:\n" + "\n".join(errors))
    print(f"Profile alignment verified for {len(_config_paths(args.home))} configuration(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
