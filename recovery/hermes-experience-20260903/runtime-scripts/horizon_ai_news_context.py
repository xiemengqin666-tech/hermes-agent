#!/usr/bin/env python3
"""Collect Horizon + legacy RSS context for Hermes daily AI news cron.

This script intentionally does not send messages. It prints one JSON object to
stdout so the cron agent can synthesize the final Feishu-delivered report.
"""
from __future__ import annotations

import argparse
import email.utils
import html
import json
import os
import re
import signal
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

HORIZON_DIR = Path.home() / ".hermes" / "apps" / "horizon"
RSS_SCRIPT = Path.home() / ".hermes" / "scripts" / "ai_news_rss.py"
AI_NEWS_OUTPUT_DIR = Path.home() / ".hermes" / "cron" / "output" / "ae8b36822205"
REPORT_HISTORY_LIMIT = 7
BLOCKED_TOPICS = (
    "llama.cpp",
    "ai safety", "safety risk", "security risk", "security incident",
    "prompt injection", "red team", "red-team", "alignment",
    "安全", "提示注入", "红队", "对齐风险", "模型治理", "人工智能治理",
)

_GENERIC_EVENT_TOKEN_STOP = {
    "ai", "openai", "google", "microsoft", "meta", "model", "models",
    "robot", "robots", "robotics", "release", "released", "update", "updated",
}

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_DUPLICATE_EVENT_PATTERNS = [
    ("GPT-5.6 / OpenAI rollout", ("gpt-5.6", "openai"), ("gpt-5.6", "openai")),
    ("OpenAI custom inference chip", ("openai", "jalape"), ("openai", "芯片")),
    ("OpenAI custom inference chip", ("openai", "jalape"), ("openai", "chip")),
    ("SGLang v0.5.14", ("sglang",), ("sglang",)),
    ("prompt-injection red-team experiment", ("hack my ai assistant",), ("prompt", "injection")),
    ("Tesla China + Doubao/DeepSeek", ("tesla", "deepseek"), ("特斯拉", "deepseek")),
    ("Tesla China + Doubao/DeepSeek", ("特斯拉", "deepseek"), ("特斯拉", "deepseek")),
    ("General Intuition funding", ("general intuition",), ("general intuition",)),
    ("AI chip arms race", ("openai", "spacex", "chips"), ("openai", "spacex", "芯片")),
]

_EVENT_ENTITY_ALIASES = {
    "openai": ("openai",),
    "google": ("google", "谷歌"),
    "deepseek": ("deepseek",),
    "unitree": ("unitree", "宇树"),
    "anthropic": ("anthropic",),
    "huggingface": ("hugging face", "huggingface"),
    "avatar-robotics": ("avatar robotics",),
    "glm": ("glm", "智谱"),
    "astra": ("astra",),
}

_EVENT_KIND_TERMS = {
    "funding": ("融资", "入股", "投资", "seed round", "funding", "invest", "valuation", "估值"),
    "pricing": ("调价", "涨价", "降价", "pricing", "price increase", "price cut"),
    "org-change": ("人才", "高层", "架构调整", "组织调整", "shake-up", "new role", "reorganization"),
    "hardware": ("硬件", "设备", "终端", "gadget", "device", "hardware"),
    "release": ("发布", "上线", "开源", "launch", "release", "open-source"),
}


def _tail(text: str, max_chars: int = 8000) -> str:
    if not text:
        return ""
    return text[-max_chars:] if len(text) > max_chars else text


def _read_text(path: Path, max_chars: int = 18000) -> str:
    text = path.read_text(encoding="utf-8", errors="ignore")
    if len(text) > max_chars:
        return text[:max_chars] + f"\n\n...[TRUNCATED {len(text) - max_chars} chars]"
    return text


def _sanitize_for_cron_context(value):
    """Remove local-only addresses/paths before stdout is injected into an LLM cron run."""
    if isinstance(value, dict):
        sanitized = {}
        for key, child in value.items():
            # Local implementation details are useful for debugging logs but must not be available
            # to the report-writing model; otherwise they can leak into Feishu messages.
            if key in {"summary_path", "stdout_tail", "stderr_tail"}:
                continue
            sanitized[key] = _sanitize_for_cron_context(child)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_for_cron_context(child) for child in value]
    if isinstance(value, str):
        value = re.sub(r"/Users/[^\s\])}>\"'，。；、]*", "[local-path-redacted]", value)
        value = re.sub(r"file://[^\s\])}>\"'，。；、]*", "[local-file-redacted]", value)
        value = re.sub(r"https?://(?:localhost|127\.0\.0\.1)(?::\d+)?[^\s\])}>\"'，。；、]*", "[local-url-redacted]", value)
        value = value.replace("localhost", "[local-host-redacted]").replace("127.0.0.1", "[local-host-redacted]")
        return value
    return value



def _previous_ai_news_report(today: str) -> tuple[str | None, str]:
    """Return the last week of delivered AI-news report text for deduplication."""
    if not AI_NEWS_OUTPUT_DIR.exists():
        return None, ""
    candidates = [
        path for path in AI_NEWS_OUTPUT_DIR.glob("*.md")
        if not path.name.startswith(today)
    ]
    if not candidates:
        return None, ""
    paths = sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)[:REPORT_HISTORY_LIMIT]
    reports = []
    for path in paths:
        text = _read_text(path, max_chars=60000)
        if "## Response" in text:
            text = text.split("## Response", 1)[1]
        reports.append(f"\n<!-- {path.name} -->\n{text}")
    return ", ".join(path.name for path in paths), "\n".join(reports)


def _norm_text(value: str) -> str:
    value = (value or "").lower()
    value = value.replace("jalapeño", "jalapeno")
    value = re.sub(r"\s+", " ", value)
    return value


def _blocked_topic(*values: str) -> bool:
    text = _norm_text("\n".join(values))
    return any(topic in text for topic in BLOCKED_TOPICS)


def _previous_report_titles(previous_text: str) -> list[str]:
    return [
        title.strip()
        for title in re.findall(r"(?m)^\s*(?:\d+\.|[-*])\s+.*?\*\*(.+?)\*\*", previous_text or "")
        if not _blocked_topic(title)
    ]


def _event_anchor_tokens(value: str) -> set[str]:
    tokens = set(re.findall(r"[a-z][a-z0-9.+-]*", _norm_text(value)))
    return {
        token for token in tokens
        if token not in _GENERIC_EVENT_TOKEN_STOP
        and (len(token) >= 3 or any(ch.isdigit() for ch in token))
    }


def _event_signature(value: str) -> tuple[set[str], set[str], set[str]]:
    text = _norm_text(value)
    entities = {
        entity for entity, aliases in _EVENT_ENTITY_ALIASES.items()
        if any(alias in text for alias in aliases)
    }
    kinds = {
        kind for kind, terms in _EVENT_KIND_TERMS.items()
        if any(term in text for term in terms)
    }
    versions = {
        token for token in _event_anchor_tokens(text)
        if any(ch.isdigit() for ch in token) and len(token) >= 4
    }
    return entities, kinds, versions


def _event_duplicate_reason(title: str, body: str, previous_text: str) -> str | None:
    """Heuristic event-level duplicate detector against recent delivered reports."""
    if not previous_text:
        return None
    cand = _norm_text(f"{title}\n{body}")
    prev = _norm_text(previous_text)
    for reason, cand_terms, prev_terms in _DUPLICATE_EVENT_PATTERNS:
        if all(term in cand for term in cand_terms) and all(term in prev for term in prev_terms):
            return reason
    # Keep the fallback deliberately conservative. Broad token-overlap over-filters Chinese AI news
    # because names like OpenAI/DeepSeek/AI appear in many unrelated daily items. Only exact or
    # curated event-pattern duplicates are suppressed here; the prompt still receives the explicit
    # excluded list for editorial awareness.
    compact_title = re.sub(r"[^a-z0-9一-鿿]+", "", _norm_text(title))
    compact_prev = re.sub(r"[^a-z0-9一-鿿]+", "", prev)
    if len(compact_title) >= 18 and compact_title in compact_prev:
        return "exact title already appeared in previous report"
    candidate_anchors = _event_anchor_tokens(f"{title}\n{body}")
    candidate_entities, candidate_kinds, candidate_versions = _event_signature(f"{title}\n{body}")
    for previous_title in _previous_report_titles(previous_text):
        previous_entities, previous_kinds, previous_versions = _event_signature(previous_title)
        if candidate_versions & previous_versions:
            return "same versioned product already appeared in recent reports"
        shared_entities = candidate_entities & previous_entities
        if shared_entities and candidate_kinds & previous_kinds:
            required_entities = 2 if min(len(candidate_entities), len(previous_entities)) >= 2 else 1
            if len(shared_entities) >= required_entities:
                return "same entity and event type already appeared in recent reports"
        if len(candidate_anchors & _event_anchor_tokens(previous_title)) >= 2:
            return "same named event already appeared in recent reports"
    return None


def _extract_horizon_items(markdown: str) -> list[dict]:
    pattern = re.compile(
        r"(?:^|\n)<a id=\"item-(?P<num>\d+)\"></a>\n(?P<block>## \[(?P<title>[^\]]+)\]\((?P<url>[^)]+)\).*?)(?=\n---\n\n(?:<a id=\"item-|$)|\Z)",
        re.S,
    )
    out = []
    for m in pattern.finditer(markdown or ""):
        block = m.group("block").strip()
        source_line = ""
        for ln in block.splitlines():
            if " · " in ln and not ln.startswith("## "):
                source_line = ln.strip()
                break
        out.append({
            "num": int(m.group("num")),
            "title": m.group("title").strip(),
            "url": m.group("url").strip(),
            "block": block,
            "source_line": source_line,
        })
    return out


def _filter_horizon_markdown(summary: str | None, summary_day: str | None, previous_text: str) -> tuple[str | None, list[dict], list[dict], int]:
    if not summary:
        return summary, [], [], 0
    items = _extract_horizon_items(summary)
    if not items:
        return summary, [], [], 0
    kept = []
    excluded = []
    blocked_count = 0
    for item in items:
        if _blocked_topic(item["title"], item["block"], item["url"]):
            blocked_count += 1
            continue
        reason = _event_duplicate_reason(item["title"], item["block"], previous_text)
        if reason:
            excluded.append({"title": item["title"], "source_line": item["source_line"], "reason": reason})
        else:
            kept.append(item)
    header = f"# Horizon 每日速递 - {summary_day or datetime.now().astimezone().date().isoformat()}\n\n"
    header += f"> Filtered for novelty: {len(kept)} kept, {len(excluded)} excluded because they already appeared in the previous delivered report.\n\n---\n\n"
    toc = "".join(f"{idx}. [{item['title']}](#item-{idx})\n" for idx, item in enumerate(kept, start=1))
    blocks = []
    for idx, item in enumerate(kept, start=1):
        block = re.sub(r"<a id=\"item-\d+\"></a>", f"<a id=\"item-{idx}\"></a>", item["block"])
        blocks.append(block)
    filtered = header + toc + "\n---\n\n" + "\n\n---\n\n".join(blocks) + ("\n" if blocks else "")
    return filtered, kept, excluded, blocked_count


def _filter_rss_json_for_novelty(rss_json: dict, previous_text: str) -> tuple[dict, dict, int]:
    """Remove items already covered by yesterday's delivered report from RSS arrays."""
    if not isinstance(rss_json, dict):
        return rss_json, {}, 0
    filtered = dict(rss_json)
    excluded: dict[str, list[dict]] = {}
    blocked_count = 0
    for key in ("AI_NEWS", "ROBOT_NEWS", "COMPANY_NEWS"):
        kept = []
        drops = []
        for item in rss_json.get(key, []) or []:
            title = str(item.get("title", ""))
            body = "\n".join(str(item.get(k, "")) for k in ("desc", "source", "date"))
            if _blocked_topic(title, body, str(item.get("link", ""))):
                blocked_count += 1
                continue
            reason = _event_duplicate_reason(title, body, previous_text)
            if reason:
                drops.append({"title": title, "source": item.get("source"), "date": item.get("date"), "reason": reason})
            else:
                kept.append(item)
        filtered[key] = kept
        if drops:
            excluded[key] = drops
    return filtered, excluded, blocked_count


def _self_check() -> None:
    previous = (
        "1. 💰 **AMD拟向Anthropic投入最高50亿美元**\n"
        "2. 🔥 **Kimi K3冲击高性价比模型前列**\n"
        "- 💰 **Avatar Robotics 完成种子轮融资**\n"
        "- 🟣 **智谱 GLM-5.3 发布预热**\n"
        "- 🔵 **DeepSeek API 调价**\n"
        "- 🤖 **DeepSeek 入股宇树**\n"
        "- 🟠 **OpenAI 消费硬件设备推进**\n"
        "- 🔵 **Google AI 人才与架构调整**"
    )
    assert _event_duplicate_reason("AMD以Helios系统绑定Anthropic，最高投入50亿美元", "", previous)
    assert _event_duplicate_reason("Kimi K3发布，加剧开源模型竞争", "", previous)
    assert _event_duplicate_reason("Avatar Robotics raises seed round", "", previous)
    assert _event_duplicate_reason("GLM-5.3 release preview", "", previous)
    assert _event_duplicate_reason("DeepSeek price increase", "", previous)
    assert _event_duplicate_reason("DeepSeek invests in Unitree", "", previous)
    assert _event_duplicate_reason("OpenAI gadget takes shape", "new device hardware", previous)
    assert _event_duplicate_reason("Google AI shake-up", "Jeff Dean takes a new role", previous)
    assert not _event_duplicate_reason("DeepSeek launches a new model", "", "- 🔵 **DeepSeek API 调价**")
    assert not _event_duplicate_reason("OpenAI releases a new model", "", "- 🟠 **OpenAI 消费硬件设备推进**")
    assert _blocked_topic("llama.cpp updates CUDA kernels")
    assert _blocked_topic("OpenAI delays Astra over AI safety risk")
    assert not _blocked_topic("Anthropic launches a new model")


def _latest_horizon_summary() -> tuple[str | None, str | None, str | None]:
    candidates = list((HORIZON_DIR / "data" / "summaries").glob("*-zh.md"))
    candidates += list((HORIZON_DIR / "docs" / "_posts").glob("*summary-zh.md"))
    if not candidates:
        return None, None, None
    path = max(candidates, key=lambda p: p.stat().st_mtime)
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    return str(path), mtime, _read_text(path)


def _summary_date(path: str | None, summary: str | None) -> str | None:
    if summary:
        match = re.search(r"(?m)^date:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\s*$", summary)
        if match:
            return match.group(1)
    if path:
        match = re.search(r"([0-9]{4}-[0-9]{2}-[0-9]{2})", path)
        if match:
            return match.group(1)
    return None


def _age_days(summary_day: str | None, today: str) -> int | None:
    if not summary_day:
        return None
    try:
        return (date.fromisoformat(today) - date.fromisoformat(summary_day)).days
    except ValueError:
        return None


def _populate_github_token(env: dict[str, str]) -> str:
    """Ensure Horizon can use authenticated GitHub API calls without exposing secrets."""
    if env.get("GITHUB_TOKEN"):
        return "env:GITHUB_TOKEN"
    if env.get("GH_TOKEN"):
        env["GITHUB_TOKEN"] = env["GH_TOKEN"]
        return "env:GH_TOKEN"
    try:
        cp = subprocess.run(
            ["gh", "auth", "token"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except Exception:
        return "none"
    token = (cp.stdout or "").strip()
    if cp.returncode == 0 and token:
        env["GITHUB_TOKEN"] = token
        return "gh-cli"
    return "none"




def _clean_feed_text(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def _child_text(elem: ET.Element, names: set[str]) -> str:
    for child in list(elem):
        name = child.tag.rsplit("}", 1)[-1].lower()
        if name in names:
            return _clean_feed_text("".join(child.itertext()))
    return ""


def _fetch_google_news_items(query: str, source_name: str, *, limit: int = 8, timeout: int = 18) -> dict:
    """Fetch a small Google News RSS slice for robot valuation grounding.

    This intentionally returns titles/sources/dates only. It gives the report model
    explicit source breadcrumbs for the valuation ranking, without relying on stale
    hard-coded estimates.
    """
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({
        "q": query,
        "hl": "zh-CN",
        "gl": "CN",
        "ceid": "CN:zh-Hans",
    })
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Hermes AI News)"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read().decode("utf-8", "ignore")
        root = ET.fromstring(data)
        items = []
        for item in root.findall(".//item")[:limit]:
            title = _child_text(item, {"title"})
            pub = _child_text(item, {"pubdate", "published", "updated"})
            link = _child_text(item, {"link"})
            publisher = ""
            # Google News titles are usually "headline - publisher"; split only for display.
            if " - " in title:
                publisher = title.rsplit(" - ", 1)[-1]
            items.append({"title": title, "publisher": publisher, "date": pub, "link": link})
        return {"name": source_name, "url": url, "ok": True, "count": len(items), "items": items}
    except Exception as exc:  # noqa: BLE001
        return {"name": source_name, "url": url, "ok": False, "error": repr(exc), "items": []}


def _robot_valuation_sources() -> dict:
    queries = [
        (
            "Google News Unitree IPO Valuation",
            "宇树 IPO 估值 OR 市值 when:30d",
        ),
        (
            "Google News Agibot Valuation Funding",
            "智元机器人 估值 融资 when:60d",
        ),
        (
            "Google News PaXini IPO Valuation",
            "帕西尼 估值 融资 IPO when:60d",
        ),
        (
            "Google News China Embodied 200bn Valuation",
            "中国 具身智能 估值 200亿元 when:30d",
        ),
        (
            "Google News China Humanoid Funding",
            "(人形机器人 OR 具身智能 OR humanoid robot OR embodied AI) (融资 OR 估值 OR IPO OR investment OR valuation) (中国 OR China) when:30d",
        ),
    ]
    feeds = [_fetch_google_news_items(query, name) for name, query in queries]
    return {
        "feeds": feeds,
        "rules": [
            "估值排行必须优先引用 robot_valuation_sources / rss.ROBOT_NEWS / Horizon 中的公开来源；不要只用记忆或旧 skill 的固定数字。",
            "同一公司的估值如果多源冲突，写区间或写“媒体报道/融资后估值约…”，并标注来源；不要写成精确事实。",
            "T0/T1/T2 分层以公开市值、IPO进度、最近融资后估值、主流媒体估值报道为依据；没有源支撑的公司降级为“待核验/不列入”。",
            "优必选是已上市公司，优先写市值/二级市场参考，不写成未上市融资估值。",
        ],
    }

def _run(cmd: list[str], cwd: Path | None, timeout: int, env: dict[str, str] | None = None) -> dict:
    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd) if cwd else None,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        stdout, stderr = proc.communicate(timeout=timeout)
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": stdout,
            "stdout_tail": _tail(stdout),
            "stderr_tail": _tail(stderr),
        }
    except subprocess.TimeoutExpired:
        if proc is not None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                stdout, stderr = proc.communicate(timeout=10)
            except Exception:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except Exception:
                    pass
                stdout, stderr = "", ""
        else:
            stdout, stderr = "", ""
        return {
            "ok": False,
            "timeout": True,
            "returncode": None,
            "stdout_tail": _tail(stdout),
            "stderr_tail": _tail(stderr),
            "error": f"timeout after {timeout}s",
        }
    except Exception as exc:  # noqa: BLE001 - context collector must not crash if one source fails
        return {"ok": False, "returncode": None, "error": repr(exc), "stdout_tail": "", "stderr_tail": ""}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=36)
    parser.add_argument("--horizon-timeout", type=int, default=420)
    parser.add_argument("--rss-timeout", type=int, default=120)
    parser.add_argument("--skip-horizon", action="store_true", help="Only read latest existing Horizon summary")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        _self_check()
        print("self-check ok")
        return 0

    result: dict = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "strategy": "Horizon primary signal + legacy RSS supplement/fallback; no direct sending",
        "horizon": {"enabled": HORIZON_DIR.exists(), "ran": False},
        "rss": {"enabled": RSS_SCRIPT.exists(), "ran": False},
    }

    if HORIZON_DIR.exists() and not args.skip_horizon:
        env = os.environ.copy()
        # Keep the scheduled job under control: analysis + topic dedup + final summary are enough;
        # deep DDGS enrichment is useful but can exceed cron windows on MiniMax CN.
        env.setdefault("HORIZON_SKIP_ENRICHMENT", "1")
        env["HORIZON_SKIP_TOPIC_DEDUP"] = "0"
        env.setdefault("HORIZON_MAX_ANALYSIS_ITEMS", "60")
        env.setdefault("HORIZON_MAX_ITEMS_PER_SUBSOURCE", "18")
        env.setdefault("HORIZON_ANALYSIS_CONCURRENCY", "6")
        env.setdefault("HORIZON_ANALYSIS_TIMEOUT_SEC", "30")
        env.setdefault("HORIZON_TOPIC_DEDUP_TIMEOUT_SEC", "45")
        github_auth = _populate_github_token(env)
        result["horizon"]["github_auth"] = github_auth
        run = _run(
            ["uv", "run", "horizon", "--hours", str(args.hours)],
            cwd=HORIZON_DIR,
            timeout=args.horizon_timeout,
            env=env,
        )
        run.pop("stdout", None)
        result["horizon"].update({"ran": True, "run": run})

    summary_path, summary_mtime, summary = _latest_horizon_summary()
    today = datetime.now().astimezone().date().isoformat()
    previous_report_name, previous_report_text = _previous_ai_news_report(today)
    summary_day = _summary_date(summary_path, summary)
    summary_age_days = _age_days(summary_day, today)
    filtered_summary, kept_horizon_items, excluded_horizon_duplicates, blocked_horizon_count = _filter_horizon_markdown(
        summary, summary_day, previous_report_text
    )
    result["horizon"].update(
        {
            "summary_path": summary_path,
            "summary_mtime_utc": summary_mtime,
            "summary_date": summary_day,
            "summary_is_stale": bool(summary_age_days is not None and summary_age_days > 0),
            "summary_age_days": summary_age_days,
            "summary_markdown": filtered_summary,
            "summary_original_items_count": len(_extract_horizon_items(summary or "")),
            "summary_novel_items_count": len(kept_horizon_items),
            "excluded_previous_report_duplicates": excluded_horizon_duplicates,
            "blocked_topic_items_count": blocked_horizon_count,
        }
    )
    result["previous_report_dedupe"] = {
        "previous_report": previous_report_name,
        "recent_report_titles": _previous_report_titles(previous_report_text),
        "rule": "Compare against all recent_report_titles. Do not repeat an event from the last 7 reports unless today's source contains a concrete new development; fresh commentary or a rewritten headline is not a new development.",
    }
    result["content_filter"] = {
        "blocked_topic_items_count": blocked_horizon_count,
        "rule": "Items removed by the content filter must not be mentioned, including in summaries or source lists.",
    }
    result["dedupe_rules"] = [
        "同一事件只写一次；Horizon 与 RSS 重叠时优先采用 Horizon，并把 RSS 作为补充来源合并到同一条。",
        "严格对照 previous_report_dedupe.recent_report_titles；近7期已写过的事件不得重复，只有明确新增事实才能续写，换标题、换来源、评论或小版本更新不算新增事实。",
        "去重和内容过滤后不足 10 条就少写，宁缺毋滥；禁止为了凑满 Top 10 恢复旧闻、低价值安全新闻或编造条目。",
        "如果 horizon.summary_is_stale 为 true，Horizon 只能作为背景和补充，不要把旧日期内容当作今日 Top 新闻。",
        "【机器人板块融资情况】只写明确融资、订单、上市、估值或可验证商业化里程碑；政策、基金配置、研报观点不要放在这里。",
        "【厂商动态】不要复述 Top 10 已写过的事件；必要时用一句话引用“见 Top 10 第 N 条”。",
        "【国内机器人公司估值参考排行】必须优先使用 robot_valuation_sources / rss.ROBOT_NEWS / Horizon 的公开来源；无源支撑的估值不要写，冲突估值写区间或标注‘媒体报道约’。",
    ]
    result["robot_valuation_sources"] = _robot_valuation_sources()

    if RSS_SCRIPT.exists():
        run = _run([sys.executable, str(RSS_SCRIPT)], cwd=RSS_SCRIPT.parent, timeout=args.rss_timeout)
        stdout = run.pop("stdout", "") or ""
        result["rss"].update({"ran": True, "run": run})
        if run.get("ok"):
            try:
                rss_json = json.loads(stdout or "{}")
                filtered_rss_json, excluded_rss_duplicates, blocked_rss_count = _filter_rss_json_for_novelty(rss_json, previous_report_text)
                result["rss"]["json"] = filtered_rss_json
                result["rss"]["excluded_previous_report_duplicates"] = excluded_rss_duplicates
                result["rss"]["blocked_topic_items_count"] = blocked_rss_count
                result["content_filter"]["blocked_topic_items_count"] += blocked_rss_count
            except Exception as exc:  # noqa: BLE001
                result["rss"]["parse_error"] = repr(exc)

    result = _sanitize_for_cron_context(result)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
