#!/usr/bin/env python3
"""Query GPT/Codex account usage through Hermes' native usage helper."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    try:
        hermes_root = Path.home() / ".hermes/hermes-agent"
        sys.path.insert(0, str(hermes_root))
        from agent.account_usage import fetch_account_usage, render_account_usage_lines
    except Exception as exc:
        print(f"GPT/Codex 用量查询失败：无法加载 Hermes 用量模块：{exc}")
        return 1

    try:
        snapshot = fetch_account_usage("openai-codex")
    except Exception as exc:
        print(f"GPT/Codex 用量查询失败：{exc}")
        return 1

    lines = render_account_usage_lines(snapshot)
    if not lines:
        print("GPT/Codex 用量：未返回用量数据")
        return 0
    print("\n".join(lines))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
