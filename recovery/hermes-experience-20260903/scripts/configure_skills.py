#!/usr/bin/env python3
"""Keep official Hermes/Lark skills plus the two selected local skills."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap


ALLOWED_CUSTOM = {
    "openclaw-imports/ionbridge-mcp",
    "productivity/luckin-cli-ordering",
}
REQUIRED_LARK = {"lark-doc", "lark-im", "lark-shared"}
REQUIRED_MCP = {"dji-mini3", "ionbridge", "luckin"}


def _skill_dirs(root: Path) -> set[str]:
    if not root.is_dir():
        return set()
    return {
        path.parent.relative_to(root).as_posix()
        for path in root.rglob("SKILL.md")
    }


def _lark_dirs(agents_home: Path) -> list[Path]:
    root = agents_home / "skills"
    return sorted(
        path.resolve()
        for path in root.glob("lark-*")
        if path.is_dir() and (path / "SKILL.md").is_file()
    )


def _state(home: Path, repo: Path, agents_home: Path) -> tuple[list[Path], set[str]]:
    lark_dirs = _lark_dirs(agents_home)
    lark_names = {path.name for path in lark_dirs}
    missing_lark = REQUIRED_LARK - lark_names
    if missing_lark:
        raise RuntimeError(
            "official Lark skills are incomplete: " + ", ".join(sorted(missing_lark))
        )

    official = _skill_dirs(repo / "skills")
    active = _skill_dirs(home / "skills")
    missing_custom = ALLOWED_CUSTOM - active
    if missing_custom:
        raise RuntimeError(
            "selected custom skills are missing: " + ", ".join(sorted(missing_custom))
        )
    return lark_dirs, active - official - ALLOWED_CUSTOM


def _configured_external_dirs(config_path: Path) -> list[str]:
    data = YAML(typ="safe").load(config_path.read_text(encoding="utf-8")) or {}
    skills = data.get("skills") or {}
    return list(skills.get("external_dirs") or [])


def _write_external_dirs(config_path: Path, paths: list[Path]) -> None:
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096
    with config_path.open(encoding="utf-8") as handle:
        data = yaml.load(handle) or CommentedMap()
    skills = data.get("skills")
    if not isinstance(skills, dict):
        skills = CommentedMap()
        data["skills"] = skills
    skills["external_dirs"] = [str(path) for path in paths]
    with config_path.open("w", encoding="utf-8") as handle:
        yaml.dump(data, handle)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--hermes-repo", type=Path, required=True)
    parser.add_argument("--agents-home", type=Path, default=Path.home() / ".agents")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    config_path = args.home / "config.yaml"
    if not config_path.is_file():
        raise RuntimeError(f"Hermes config is missing: {config_path}")

    config = YAML(typ="safe").load(config_path.read_text(encoding="utf-8")) or {}
    configured_mcp = set((config.get("mcp_servers") or {}).keys())
    missing_mcp = REQUIRED_MCP - configured_mcp
    if missing_mcp:
        raise RuntimeError(
            "selected MCP servers are missing: " + ", ".join(sorted(missing_mcp))
        )

    lark_dirs, unexpected = _state(args.home, args.hermes_repo, args.agents_home)
    wanted_external = [str(path) for path in lark_dirs]
    external_drift = _configured_external_dirs(config_path) != wanted_external

    if args.check:
        errors = []
        if unexpected:
            errors.append("unexpected custom skills: " + ", ".join(sorted(unexpected)))
        if external_drift:
            errors.append("skills.external_dirs is not the official Lark-only list")
        if errors:
            raise RuntimeError("; ".join(errors))
    else:
        skills_root = args.home / "skills"
        for relpath in sorted(unexpected, key=lambda item: (item.count("/"), item), reverse=True):
            shutil.rmtree(skills_root / relpath)
        if external_drift:
            _write_external_dirs(config_path, lark_dirs)

    _, remaining = _state(args.home, args.hermes_repo, args.agents_home)
    if remaining:
        raise RuntimeError("custom skill pruning failed: " + ", ".join(sorted(remaining)))
    if _configured_external_dirs(config_path) != wanted_external:
        raise RuntimeError("official Lark external skill configuration was not saved")

    print(
        f"Skills verified: {len(lark_dirs)} official Lark skills; "
        "custom skills are Luckin and IonBridge (DJI remains an MCP server)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
