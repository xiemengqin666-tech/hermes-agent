#!/usr/bin/env python3
"""Collect Horizon AI-news artifacts for the Hermes daily AI news cron.

- Runs Horizon locally (no external message sending).
- Parses the latest Chinese summary into compact JSON for a downstream LLM.
- Runs the legacy RSS collector as fallback/context.

No secrets are printed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

HORIZON_ROOT = Path.home() / ".hermes" / "apps" / "horizon"
RSS_SCRIPT = Path.home() / ".hermes" / "scripts" / "ai_news_rss.py"

AI_KEYWORDS = [
    "ai", "artificial intelligence", "llm", "large language model", "agent", "agents",
    "openai", "anthropic", "claude", "gpt", "gemini", "deepseek", "qwen", "glm",
    "minimax", "model", "inference", "rag", "multimodal", "robot", "robotics",
    "humanoid", "embodied", "vllm", "llama", "mcp", "cuda", "nvidia", "hugging face",
    "人工智能", "大模型", "模型", "智能体", "推理", "多模态", "机器人", "具身",
]
INVESTMENT_KEYWORDS = [
    "funding", "fundraise", "raises", "raised", "investment", "valuation", "ipo",
    "stock", "shares", "earnings", "revenue", "acquisition", "融资", "投资", "估值",
    "上市", "IPO", "股价", "财报", "收购", "并购",
]
ROBOT_KEYWORDS = [
    "robot", "robotics", "humanoid", "embodied", "drone", "机器人", "具身", "人形", "无人机",
    "宇树", "智元", "figure", "magiclab", "逐际", "傅利叶", "开普勒", "帕西尼",
]


def load_env_file(path: Path) -> dict[str, str]:
    env = os.environ.copy()
    if not path.exists():
        return env
    for line in path.read_text(errors="ignore").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, value = line.split("=", 1)
        env.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return env


def run_command(cmd: list[str], cwd: Path, timeout: int, env: dict[str, str] | None = None) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout_tail": tail(proc.stdout, 4000),
            "stderr_tail": tail(proc.stderr, 4000),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "returncode": None,
            "timeout": timeout,
            "stdout_tail": tail(exc.stdout or "", 4000),
            "stderr_tail": tail(exc.stderr or "", 4000),
            "error": f"timeout after {timeout}s",
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "returncode": None, "error": repr(exc), "stdout_tail": "", "stderr_tail": ""}


def tail(text: str | bytes, max_chars: int) -> str:
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    text = text or ""
    return text[-max_chars:]


def latest_summary() -> Path | None:
    candidates = list((HORIZON_ROOT / "data" / "summaries").glob("*-zh.md"))
    candidates += list((HORIZON_ROOT / "docs" / "_posts").glob("*summary-zh.md"))
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def strip_frontmatter(text: str) -> str:
    return re.sub(r"^---\n.*?\n---\n\n?", "", text, flags=re.S)


def has_any(text: str, terms: list[str]) -> bool:
    low = text.lower()
    return any(term.lower() in low for term in terms)


def parse_horizon_items(markdown: str, max_items: int) -> list[dict[str, Any]]:
    text = strip_frontmatter(markdown)
    pattern = re.compile(
        r"(?:^|\n)## \[(?P<title>[^\]]+)\]\((?P<url>[^)]+)\)\s*⭐️?\s*(?P<score>[0-9.]+|\?)/10\n(?P<body>.*?)(?=\n---\n\n(?:<a id=\"item-|$)|\Z)",
        re.S,
    )
    items: list[dict[str, Any]] = []
    for m in pattern.finditer(text):
        body = m.group("body").strip()
        lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
        source_line = ""
        for ln in lines:
            if " · " in ln and ("hackernews" in ln.lower() or "reddit" in ln.lower() or "rss" in ln.lower() or "github" in ln.lower() or "telegram" in ln.lower() or "ossinsight" in ln.lower()):
                source_line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", ln)
                break
        tags_match = re.search(r"\*\*标签\*\*:\s*(.+)", body)
        tags = re.findall(r"`#?([^`]+)`", tags_match.group(1)) if tags_match else []
        title = m.group("title").strip()
        combined = f"{title}\n{body}"
        items.append(
            {
                "title": title,
                "url": m.group("url").strip(),
                "score": float(m.group("score")) if m.group("score") != "?" else None,
                "source_line": source_line,
                "tags": tags[:8],
                "is_ai_related_by_keyword": has_any(combined, AI_KEYWORDS),
                "is_investment_related": has_any(combined, INVESTMENT_KEYWORDS),
                "is_robotics_related": has_any(combined, ROBOT_KEYWORDS),
                "excerpt": re.sub(r"\n{3,}", "\n\n", body)[:1800],
            }
        )
        if len(items) >= max_items:
            break
    return items


def run_rss_fallback() -> dict[str, Any]:
    if not RSS_SCRIPT.exists():
        return {"ok": False, "error": f"missing {RSS_SCRIPT}"}
    result = run_command(["python3", str(RSS_SCRIPT)], cwd=RSS_SCRIPT.parent, timeout=90)
    if not result["ok"]:
        return {"ok": False, **result}
    try:
        data = json.loads(result["stdout_tail"])
    except Exception:
        # stdout_tail can be truncated if the legacy script grows; run again with direct capture size is avoided here.
        try:
            proc = subprocess.run(["python3", str(RSS_SCRIPT)], cwd=str(RSS_SCRIPT.parent), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
            data = json.loads(proc.stdout)
            result["stderr_tail"] = tail(proc.stderr, 4000)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"RSS JSON parse failed: {exc}", **result}
    return {
        "ok": True,
        "generated_at": data.get("generated_at"),
        "window_hours": data.get("window_hours"),
        "counts": data.get("counts"),
        "sources": data.get("sources"),
        "AI_NEWS": data.get("AI_NEWS", [])[:10],
        "ROBOT_NEWS": data.get("ROBOT_NEWS", [])[:10],
        "COMPANY_NEWS": data.get("COMPANY_NEWS", [])[:10],
        "stderr_tail": result.get("stderr_tail", ""),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=36)
    parser.add_argument("--timeout", type=int, default=420)
    parser.add_argument("--max-items", type=int, default=12)
    parser.add_argument("--skip-horizon-run", action="store_true", help="Parse the latest existing Horizon summary without running Horizon")
    args = parser.parse_args()

    started_dt = datetime.now().astimezone()
    started_at = started_dt.isoformat()
    env = load_env_file(HORIZON_ROOT / ".env")
    # Cron-safe defaults: avoid the slow 2nd enrichment pass and stream logs promptly.
    env.setdefault("HORIZON_SKIP_ENRICHMENT", "true")
    env.setdefault("PYTHONUNBUFFERED", "1")

    previous_summary = latest_summary()
    previous_signature = (
        (str(previous_summary), previous_summary.stat().st_mtime)
        if previous_summary and previous_summary.exists()
        else None
    )

    horizon_run: dict[str, Any] = {"ok": True, "skipped": True}
    if not args.skip_horizon_run:
        horizon_run = run_command(["uv", "run", "horizon", "--hours", str(args.hours)], HORIZON_ROOT, args.timeout, env)

    summary_path = latest_summary()
    summary_signature = (
        (str(summary_path), summary_path.stat().st_mtime)
        if summary_path and summary_path.exists()
        else None
    )
    summary_is_fresh = bool(args.skip_horizon_run) or (
        bool(summary_signature)
        and summary_signature != previous_signature
        and datetime.fromtimestamp(summary_path.stat().st_mtime).astimezone() >= started_dt
    )
    summary_text = ""
    items: list[dict[str, Any]] = []
    if summary_path and summary_path.exists() and summary_is_fresh:
        summary_text = summary_path.read_text(encoding="utf-8", errors="ignore")
        items = parse_horizon_items(summary_text, args.max_items)

    rss = run_rss_fallback()

    horizon_ai_news = [item for item in items if item["is_ai_related_by_keyword"] and not item["is_investment_related"]]
    horizon_robot_news = [item for item in items if item["is_robotics_related"]]
    company_terms = ["openai", "anthropic", "minimax", "claude", "gpt", "qwen", "gemini", "deepseek", "阿里", "通义", "智谱"]
    horizon_company_news = [
        item for item in items
        if has_any(f"{item['title']}\n{item['excerpt']}", company_terms)
    ]

    payload = {
        "generated_at": started_at,
        "collector": "horizon_ai_news_collect.py",
        "editorial_input": {
            "primary_ai_news": horizon_ai_news[:10],
            "robot_news": horizon_robot_news[:10],
            "company_news": horizon_company_news[:10],
            "legacy_rss_ai_news": rss.get("AI_NEWS", [])[:10] if rss.get("ok") else [],
            "legacy_rss_robot_news": rss.get("ROBOT_NEWS", [])[:10] if rss.get("ok") else [],
            "legacy_rss_company_news": rss.get("COMPANY_NEWS", [])[:10] if rss.get("ok") else [],
            "quality": {
                "horizon_items": len(items),
                "horizon_ai_items": len(horizon_ai_news),
                "horizon_robot_items": len(horizon_robot_news),
                "horizon_company_items": len(horizon_company_news),
                "rss_counts": rss.get("counts") if rss.get("ok") else None,
            },
        },
        "horizon": {
            "ok": bool(horizon_run.get("ok")) and bool(summary_path) and summary_is_fresh,
            "run": horizon_run,
            "summary_path": str(summary_path) if summary_path else None,
            "summary_mtime": datetime.fromtimestamp(summary_path.stat().st_mtime).astimezone().isoformat() if summary_path else None,
            "summary_is_fresh": summary_is_fresh,
            "items_count": len(items),
            "items": items,
            "note": "Horizon is primary; legacy RSS below is fallback and helps fill robot/vendor sections.",
        },
        "rss_fallback": rss,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    # Return 0 if at least one collector produced usable data, so cron can still continue on Horizon-only/RSS-only partial success.
    return 0 if (items or rss.get("ok")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
