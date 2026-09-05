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
CURRENT_BROWSER = (
    "- 浏览器只用 Microsoft Edge；禁止启动或连接 Chrome/Chromium、批准 Chrome 远程调试、使用自动发现的默认浏览器。"
    "Hermes 保持 `browser.backend: 'off'`，使用内置浏览器工具和已固定的 Edge 路径；该设置不禁用浏览器功能。"
    "终端浏览器也必须显式指定 Edge，并在结束时仅关闭本任务的 session，保留登录配置。"
)
LEGACY_DEBUG = "- **每次回答前都加载并使用 PUA Debugging：常驻应用先查后答、主动执行、端到端验证和不轻言放弃；只有连续失败 ≥2 次、明显卡住、缺少关键验证、准备把工作交还用户，或用户明确要求继续深挖时，才启用 PUA 标签、压力话术和升级清单。**"
CURRENT_DEBUG = "- 排障技能按需加载：仅在连续失败两次以上、明显卡住或用户要求深入排障时使用 PUA Debugging；普通回答和已知修复不强制加载，不使用压力话术。"
CODING_RULES = """## 编程工作流（2026-09-05）

以下规则仅用于编程、代码审查和工程排障；普通聊天、瑞幸点单及其他业务流程保持原流程。

- 先读目标仓库的 AGENTS.md、相关代码和 git status；CodeGraph 用于符号与调用关系，rg 用于字面文本。遵守项目已有工具链和约定。
- 默认直接把任务做到实现、验证和交付。简单修复不分派、不因“帮我”或回复长度触发子助理；只有独立且有收益的工作才用 Hermes 的 delegate_task，收齐必要结果后再结束。
- 修改使用 patch/write_file，不用聊天中的代码块代替落盘；保留用户已有更改，只改本任务相关文件。未被要求不提交、推送或重启服务。
- 使用真实终端执行适合改动范围的测试、构建或检查；失败先定位根因再修复。UI 改动用 Microsoft Edge 查看实际效果，禁止 Chrome/Chromium。
- 长任务用 todo_list 跟踪，进度只总结当前动作、结果和阻塞。飞书进度交给同一流式卡片，微信保持已收到提示和合并正文，不额外发消息或手动设置完成表情。
- 最终简洁说明修改、验证结果及未解决项。必要子任务或测试还在运行时不得声称完成；只在用户要求时展示代码块。
"""


def normalize_soul(text: str) -> str:
    text = text.replace("使用 sessions_spawn 并行", "使用 Hermes 的 delegate_task 并行")
    if CODING_RULES not in text:
        text = text.rstrip() + "\n\n" + CODING_RULES
    return text


def normalize(text: str) -> str:
    text = text.replace(LEGACY_SEARCH, CURRENT_SEARCH)
    text = text.replace(LEGACY_DEBUG, CURRENT_DEBUG)
    if CURRENT_BROWSER not in text:
        marker = "### Pigger's Preferences\n"
        if marker in text:
            text = text.replace(marker, marker + CURRENT_BROWSER + "\n", 1)
        else:
            text = text.rstrip() + "\n\n" + CURRENT_BROWSER + "\n"
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
    parser.add_argument("--souls-home", type=Path)
    args = parser.parse_args()

    original = args.path.read_text(encoding="utf-8")
    updated = normalize(original)
    if args.check:
        if original != updated or LEGACY_SEARCH in original:
            raise SystemExit("workspace rules are not normalized")
    elif updated != original:
        args.path.write_text(updated, encoding="utf-8")
    if args.souls_home:
        paths = [args.souls_home / "SOUL.md", *sorted((args.souls_home / "profiles").glob("*/SOUL.md"))]
        for path in paths:
            original = path.read_text(encoding="utf-8")
            updated = normalize_soul(original)
            if args.check and updated != original:
                raise SystemExit(f"coding workflow is not normalized: {path}")
            if updated != original:
                path.write_text(updated, encoding="utf-8")


if __name__ == "__main__":
    main()
