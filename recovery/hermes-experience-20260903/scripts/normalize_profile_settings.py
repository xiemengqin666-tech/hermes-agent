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
    "model.default": "gpt-5.6-sol",
    "model.provider": "openai-codex",
    "agent.max_turns": 200,
    "agent.service_tier": "normal",
    "agent.reasoning_effort": "high",
    "compression.enabled": True,
    "compression.threshold": 0.75,
    "compression.target_ratio": 0.2,
    "auxiliary.compression.provider": "openai-codex",
    "auxiliary.compression.model": "gpt-5.6-sol",
    "auxiliary.title_generation.provider": "openai-codex",
    "auxiliary.title_generation.model": "gpt-5.6-sol",
    "auxiliary.triage_specifier.provider": "openai-codex",
    "auxiliary.triage_specifier.model": "gpt-5.6-sol",
    "auxiliary.kanban_decomposer.provider": "openai-codex",
    "auxiliary.kanban_decomposer.model": "gpt-5.6-sol",
    "delegation.provider": "openai-codex",
    "delegation.model": "gpt-5.6-sol",
    "delegation.reasoning_effort": "high",
    "goals.max_turns": 200,
    "approvals.mode": "off",
    "session_reset.mode": "none",
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


def _collect_errors(home: Path) -> list[str]:
    yaml = YAML(typ="safe")
    errors: list[str] = []
    for path in _config_paths(home):
        data = yaml.load(path.read_text(encoding="utf-8")) or {}
        for dotted, wanted in EXPECTED.items():
            value = _get(data, dotted)
            if value != wanted:
                errors.append(f"{path}: {dotted}={value!r}, expected {wanted!r}")

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
