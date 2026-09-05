#!/usr/bin/env python3
"""Explicitly restore public rule snapshots; never touch private memory or sessions."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import tempfile


TEMPLATES = Path(__file__).resolve().parents[1] / "rules"


def restore_rules(path: Path, home: Path | None, *, check: bool = False) -> list[Path]:
    targets = {path: "AGENTS.md"}
    if home is not None:
        targets.update({
            home / "SOUL.md": "SOUL.md",
            home / "UPDATE_GUARDRAILS.md": "UPDATE_GUARDRAILS.md",
            path.parent / "docs" / "MESSAGING.md": "MESSAGING.md",
            path.parent / "docs" / "RULES.md": "RULES.md",
        })
    # Read all templates before any writes, including backups.
    contents = {target: (TEMPLATES / name).read_text(encoding="utf-8")
                for target, name in targets.items()}
    changed = [target for target, content in contents.items()
               if not target.exists() or target.read_text(encoding="utf-8") != content]
    if check and changed:
        raise ValueError("Rule snapshot differs or is missing: " + ", ".join(map(str, changed)))
    if check or not changed:
        return changed

    existing = [target for target in changed if target.exists()]
    if existing:
        backup_root = (home if home is not None else path.parent) / "backups"
        backup_root.mkdir(parents=True, exist_ok=True)
        backup = Path(tempfile.mkdtemp(prefix="rules-before-restore-", dir=backup_root))
        for target in existing:
            shutil.copy2(target, backup / targets[target])
        print(f"Previous rules saved locally: {backup}")
    for target in changed:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents[target], encoding="utf-8")
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="Target workspace/AGENTS.md")
    parser.add_argument("--check", action="store_true", help="Compare only; never write")
    parser.add_argument("--souls-home", type=Path, help="Restore identity and runbooks too")
    args = parser.parse_args()
    try:
        changed = restore_rules(args.path, args.souls_home, check=args.check)
    except (ValueError, OSError) as exc:
        raise SystemExit(str(exc)) from exc
    print("Rule snapshot matches." if args.check else f"Restored {len(changed)} rule files.")


if __name__ == "__main__":
    main()
