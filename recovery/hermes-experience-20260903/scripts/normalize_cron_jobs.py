#!/usr/bin/env python3
"""Detach preserved cron jobs from deleted custom skills and stale paths."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


DEV_JOB_ID = "86d2f173467c"
KNOWN_JOB_IDS = (
    "88f721888bfa",
    "5d537faa89e4",
    "14d8a7a546c5",
    "2dfe7a3b13e1",
    DEV_JOB_ID,
    "4cdacd0ce308",
    "ae8b36822205",
    "7621f267d61c",
    "0564533fee39",
    "3b6de2deae77",
)
TOOLSETS = {
    "5d537faa89e4": ["terminal"],
    "14d8a7a546c5": ["terminal"],
    "3b6de2deae77": [
        "web",
        "terminal",
        "file",
        "code_execution",
        "vision",
        "todo",
        "xiaohongshu",
    ],
}
PROMPT_GUARDS = {
    "ae8b36822205": (
        "只返回一个完整最终正文",
        "\n\n【恢复约束：单卡片投递，优先级最高】\n"
        "只返回一个完整最终正文，不得主动拆成多条消息；正文中不得输出 done、"
        "发送状态或任务状态词。",
    ),
    "3b6de2deae77": (
        "不要加载任何 skill 或 SKILL.md",
        "\n\n【恢复约束：上下文预算，优先级最高】\n"
        "不要加载任何 skill 或 SKILL.md；只按需读取一份必要资料，禁止预读无关文件。",
    ),
    DEV_JOB_ID: (
        "git log -n 20",
        "\n\n【恢复约束：有界更新检查，优先级最高】\n"
        "更新检查只能使用 `git log -n 20`、"
        "`git diff --name-only HEAD..origin/main | head -n 80` 和 "
        "`git diff --shortstat HEAD..origin/main`；禁止输出完整提交、完整 diff 或完整文件列表。",
    ),
}
COMMON_REPLACEMENTS = (
    (
        "python3 ~/.hermes/workspace/skills/us-stock-analysis/fetch_data.py",
        "python3 ~/.hermes/scripts/us_stock_market_data.py",
    ),
    (
        "python3 ~/.hermes/workspace/skills/gpt-usage/query.py",
        "python3 ~/.hermes/scripts/codex_usage_query.py",
    ),
    (
        "只使用已注入的上下文、已预加载的 ai-news-workflow skill 和 terminal 工具；"
        "除 ai-news-workflow 之外，不要加载、读取或调用其他 SKILL.md / skill 工具。",
        "只使用已注入的上下文和 terminal 工具；不要加载、读取或调用任何 "
        "SKILL.md / skill 工具。",
    ),
)
CHINA_REPLACEMENTS = (
    (
        "完整热度门槛、聚类、去重、状态文件和输出格式遵循已附加的 "
        "`china-hot-video-curation` skill；本 prompt 的“只收运镜”范围优先级更高。",
        "完整热度门槛、聚类、去重、状态文件和输出格式均以本 prompt 为准。",
    ),
    (
        "【上下文与工具预算】只允许加载 `china-hot-video-curation`，不要加载其他 "
        "skill。先采集平台数据；只有命中特定 fallback 时才按需读取对应的一份 "
        "reference，禁止预读全部参考文件或大段无关文件。",
        "【上下文与工具预算】不要加载任何 skill 或 SKILL.md。先采集平台数据；"
        "只有命中特定 fallback 时才按需读取一份必要资料，禁止预读无关文件。",
    ),
    ("每期分别检索抖音、小红书、B站，并补查微博、快手；", "每期分别检索抖音、小红书、B站，并补查微博；"),
    ("   - 快手：`/Users/xiemengqin/.hermes/browser-states/kuaishou.json`\n", ""),
    ("   - 只允许使用三个固定 session：", "   - 只允许使用两个固定 session："),
    ("、`cron-trends-kuaishou`", ""),
    ("6. 微博、快手先加载各自 state", "6. 微博先加载对应 state"),
    ("对三个固定 session 执行 `close`", "对两个固定 session 执行 `close`"),
    ("分别执行三个固定 session 的 `close`", "分别执行两个固定 session 的 `close`"),
    ("抖音/小红书/B站/微博/快手状态", "抖音/小红书/B站/微博状态"),
    (
        "/Users/xiemengqin/.hermes/workspace/data/china-hot-video-motion-clusters-seen.json",
        "/Users/xiemengqin/.hermes/cron/state/china-hot-video-motion-clusters-seen.json",
    ),
)
FORBIDDEN_PROMPT_TEXT = (
    "workspace/skills",
    "ai-news-workflow",
    "china-hot-video-curation",
    "kuaishou",
    "快手",
)


def _usable_target(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or value.lower() in {"local", "origin", "none"}:
        return None
    return value


def _transform_prompt(job_id: str, prompt: str) -> str:
    for old, new in COMMON_REPLACEMENTS:
        prompt = prompt.replace(old, new)
    if job_id == "3b6de2deae77":
        for old, new in CHINA_REPLACEMENTS:
            prompt = prompt.replace(old, new)
    required, guard = PROMPT_GUARDS.get(job_id, (None, None))
    if required and required not in prompt:
        prompt = prompt.rstrip() + guard
    return prompt


def _desired_updates(jobs: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    dev_job = jobs.get(DEV_JOB_ID) or {}
    failure_target = _usable_target(dev_job.get("deliver"))
    if failure_target is None:
        for job in jobs.values():
            failure_target = _usable_target(job.get("failure_deliver"))
            if failure_target:
                break
    if failure_target is None:
        raise RuntimeError("cannot derive the developer-assistant delivery target")

    updates: dict[str, dict[str, Any]] = {}
    for job_id in KNOWN_JOB_IDS:
        job = jobs[job_id]
        update: dict[str, Any] = {
            "failure_deliver": failure_target,
            "skill": None,
            "skills": [],
        }
        if job.get("model"):
            update.update(model="gpt-6-astra", provider="openai-codex")
        prompt = _transform_prompt(job_id, str(job.get("prompt") or ""))
        if prompt != job.get("prompt"):
            update["prompt"] = prompt
        if job_id in TOOLSETS:
            update["enabled_toolsets"] = TOOLSETS[job_id]
        updates[job_id] = update

    updates["88f721888bfa"]["deliver"] = failure_target
    return updates


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--hermes-repo", type=Path, required=True)
    args = parser.parse_args()

    sys.path.insert(0, str(args.hermes_repo.resolve()))
    from cron.jobs import list_jobs, update_job

    jobs = {job["id"]: job for job in list_jobs(include_disabled=True)}
    missing = [job_id for job_id in KNOWN_JOB_IDS if job_id not in jobs]
    if missing:
        raise RuntimeError("missing expected cron jobs: " + ", ".join(missing))

    desired = _desired_updates(jobs)
    drift: list[str] = []
    for job_id, updates in desired.items():
        changed = {
            key: value
            for key, value in updates.items()
            if jobs[job_id].get(key) != value
        }
        if not changed:
            continue
        drift.append(job_id)
        if not args.check:
            update_job(job_id, changed)

    if args.check and drift:
        raise RuntimeError("cron guardrail drift: " + ", ".join(drift))

    refreshed = {job["id"]: job for job in list_jobs(include_disabled=True)}
    for job_id in KNOWN_JOB_IDS:
        job = refreshed[job_id]
        prompt = str(job.get("prompt") or "")
        found = [text for text in FORBIDDEN_PROMPT_TEXT if text in prompt]
        if found:
            raise RuntimeError(f"{job_id}: deleted dependency remains: {found}")
        if job.get("skill") or job.get("skills"):
            raise RuntimeError(f"{job_id}: custom skill binding remains")

    print(
        "Cron guardrails verified."
        if not drift
        else "Cron guardrails restored for " + ", ".join(drift) + "."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
