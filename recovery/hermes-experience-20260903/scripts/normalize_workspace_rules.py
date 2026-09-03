#!/usr/bin/env python3
"""Remove legacy workspace rules that slow deterministic connector workflows."""
from __future__ import annotations

import argparse
from pathlib import Path


LEGACY_SEARCH = "- **Always use browser search before answering questions** - 确保信息是最新的"
CURRENT_SEARCH = (
    "- 需要时效性或外部事实的问题优先搜索验证。已有权威本地数据源或专用连接器的操作流程直接使用对应工具；"
    "瑞幸点单只使用 `luckin-cli-ordering` 与 Luckin CLI/MCP，不启动浏览器、网页搜索或图片识别。"
)
CURRENT_USAGE = """### 📊 Skills 使用统计
- Hermes 已通过 `tools/skill_usage.py` 自动记录 skill 使用情况。
- 前台任务不得手工追加 `skills-usage-records.jsonl`，也不得为记账额外调用模型或终端。"""


def normalize(text: str) -> str:
    text = text.replace(LEGACY_SEARCH, CURRENT_SEARCH)
    usage_start = text.find("### 📊 Skills 使用统计")
    voice_start = text.find("\n**🎭 Voice Storytelling:**", max(usage_start, 0))
    if usage_start >= 0 and voice_start > usage_start:
        text = text[:usage_start] + CURRENT_USAGE + "\n" + text[voice_start:]
    elif CURRENT_USAGE not in text:
        marker = "\n**🎭 Voice Storytelling:**"
        if marker in text:
            text = text.replace(marker, f"\n{CURRENT_USAGE}\n{marker}", 1)
        else:
            text = text.rstrip() + "\n\n" + CURRENT_USAGE + "\n"
    if CURRENT_SEARCH not in text:
        text = text.rstrip() + "\n\n" + CURRENT_SEARCH + "\n"
    return text


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    original = args.path.read_text(encoding="utf-8")
    updated = normalize(original)
    if args.check:
        if original != updated or LEGACY_SEARCH in original:
            raise SystemExit("workspace rules are not normalized")
        return
    if updated != original:
        args.path.write_text(updated, encoding="utf-8")


if __name__ == "__main__":
    main()
