#!/usr/bin/env python3
"""Restore the local cron safety rules without embedding delivery IDs."""

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
        "browser",
        "terminal",
        "file",
        "code_execution",
        "vision",
        "skills",
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
        "只允许加载 `china-hot-video-curation`",
        "\n\n【恢复约束：上下文预算，优先级最高】\n"
        "只允许加载 `china-hot-video-curation`，不得加载其他 skill；仅在具体 "
        "fallback 命中时读取一份相关 reference。",
    ),
    DEV_JOB_ID: (
        "git log -n 20",
        "\n\n【恢复约束：有界更新检查，优先级最高】\n"
        "更新检查只能使用 `git log -n 20`、"
        "`git diff --name-only HEAD..origin/main | head -n 80` 和 "
        "`git diff --shortstat HEAD..origin/main`；禁止输出完整提交、完整 diff 或完整文件列表。",
    ),
}


def _usable_target(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or value.lower() in {"local", "origin", "none"}:
        return None
    return value


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
        if job_id in jobs:
            updates[job_id] = {"failure_deliver": failure_target}

    if "88f721888bfa" in jobs:
        updates["88f721888bfa"]["deliver"] = failure_target
    for job_id, toolsets in TOOLSETS.items():
        if job_id in jobs:
            updates[job_id]["enabled_toolsets"] = toolsets
    for job_id, (required, guard) in PROMPT_GUARDS.items():
        job = jobs.get(job_id)
        if not job:
            continue
        prompt = str(job.get("prompt") or "")
        if required not in prompt:
            updates[job_id]["prompt"] = prompt.rstrip() + guard
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
    print(
        "Cron guardrails verified."
        if not drift
        else "Cron guardrails restored for " + ", ".join(drift) + "."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
