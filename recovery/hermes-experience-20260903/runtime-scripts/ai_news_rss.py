#!/usr/bin/env python3
"""AI news RSS collector.

Outputs a single JSON object to stdout. Operational logs go to stderr so cron/agents
can parse stdout reliably. This script intentionally does not send Feishu messages;
OpenClaw cron `announce` handles delivery.
"""

from __future__ import annotations

import email.utils
import html
import json
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET

WINDOW_HOURS = 36
NOW = datetime.now().astimezone()
CUTOFF = NOW - timedelta(hours=WINDOW_HOURS)

SOURCES = [
    # Domestic source is useful, but keep global/overseas feeds overweighted in selection.
    ("https://www.36kr.com/feed", "36氪"),
    ("https://techcrunch.com/category/artificial-intelligence/feed/", "TechCrunch AI"),
    ("https://techcrunch.com/category/robotics/feed/", "TechCrunch Robotics"),
    ("https://techcrunch.com/category/startups/feed/", "TechCrunch Startups"),
    ("https://venturebeat.com/category/ai/feed/", "VentureBeat AI"),
    ("https://www.artificialintelligence-news.com/feed/", "AI News"),
    ("https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "The Verge AI"),
    ("https://www.technologyreview.com/feed/", "MIT Technology Review"),
    ("https://www.therobotreport.com/feed/", "Robot Report"),
    ("https://spectrum.ieee.org/rss/robotics/fulltext", "IEEE Spectrum Robotics"),
    ("https://www.robotics247.com/rss", "Robotics 24/7"),
    ("https://news.google.com/rss/search?q=AI%20OR%20%22artificial%20intelligence%22%20when%3A2d&hl=en-US&gl=US&ceid=US:en", "Google News Global AI"),
    # Focused Chinese vendor/model feed: broad English AI news misses domestic model launches like MiniMax M3.
    ("https://news.google.com/rss/search?q=%28MiniMax%20OR%20%22MiniMax%20M3%22%20OR%20%E6%99%BA%E8%B0%B1%20OR%20GLM%20OR%20DeepSeek%20OR%20Kimi%20OR%20Qwen%20OR%20%E8%B1%86%E5%8C%85%29%20%28%E6%A8%A1%E5%9E%8B%20OR%20%E5%A4%A7%E6%A8%A1%E5%9E%8B%20OR%20LLM%20OR%20%E5%8F%91%E5%B8%83%29%20when%3A3d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans", "Google News China AI Models"),
    ("https://news.google.com/rss/search?q=%28robotics%20OR%20humanoid%20robot%20OR%20embodied%20AI%29%20%28funding%20OR%20raises%20OR%20investment%20OR%20valuation%29%20when%3A7d&hl=en-US&gl=US&ceid=US:en", "Google News Robot Funding"),
    # Focused Chinese robotics valuation feeds: needed for the valuation ranking section. Generic robot feeds miss domestic valuation/IPO stories.
    ("https://news.google.com/rss/search?q=%28%E5%AE%87%E6%A0%91%20OR%20Unitree%20OR%20%E6%99%BA%E5%85%83%E6%9C%BA%E5%99%A8%E4%BA%BA%20OR%20Agibot%20OR%20%E4%BC%98%E5%BF%85%E9%80%89%20OR%20UBTECH%20OR%20%E5%B8%95%E8%A5%BF%E5%B0%BC%20OR%20PaXini%20OR%20%E9%80%90%E9%99%85%E5%8A%A8%E5%8A%9B%20OR%20LimX%20OR%20%E5%82%85%E5%88%A9%E5%8F%B6%20OR%20Fourier%20OR%20%E9%AD%94%E6%B3%95%E5%8E%9F%E5%AD%90%20OR%20MagicLab%20OR%20%E6%98%9F%E5%8A%A8%E7%BA%AA%E5%85%83%20OR%20Robot%20Era%29%20%28%E4%BC%B0%E5%80%BC%20OR%20%E8%9E%8D%E8%B5%84%20OR%20IPO%20OR%20%E5%B8%82%E5%80%BC%20OR%20valuation%20OR%20funding%29%20when%3A30d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans", "Google News China Robot Valuation"),
    ("https://news.google.com/rss/search?q=%28%E4%BA%BA%E5%BD%A2%E6%9C%BA%E5%99%A8%E4%BA%BA%20OR%20%E5%85%B7%E8%BA%AB%E6%99%BA%E8%83%BD%20OR%20humanoid%20robot%20OR%20embodied%20AI%29%20%28%E8%9E%8D%E8%B5%84%20OR%20%E4%BC%B0%E5%80%BC%20OR%20IPO%20OR%20investment%20OR%20valuation%29%20%28%E4%B8%AD%E5%9B%BD%20OR%20China%29%20when%3A30d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans", "Google News China Humanoid Funding"),
]

FOREIGN_SOURCES = {name for _, name in SOURCES if name != "36氪"}

AI_KW = {
    "AI", "人工智能", "大模型", "LLM", "GPT", "Claude", "Gemini", "Agent", "AIGC",
    "GenAI", "生成式", "多模态", "模型", "算力", "AI芯片", "推理", "智能体",
    "OpenAI", "Anthropic", "DeepSeek", "MiniMax", "智谱", "GLM", "Gemma", "Qwen",
    "通义", "豆包", "Kimi", "Sora", "Runway", "Perplexity", "NVIDIA", "英伟达",
}
ROBOT_KW = {
    "机器人", "具身", "人形", "机械臂", "无人机", "自动驾驶", "robot", "robotics",
    "humanoid", "embodied", "bipedal", "autonomous", "drone", "AMR", "AGV", "四足",
    "灵巧手", "宇树", "智元", "Figure", "MagicLab", "逐际", "傅利叶", "开普勒",
    "帕西尼", "PaXini", "星动纪元", "Robot Era", "有鹿", "千寻", "白犀牛", "无界动力",
    "银河通用", "Galbot", "自变量机器人", "X Square", "众擎", "EngineAI", "乐聚", "优必选", "UBTECH",
}
COMPANY_KW = {
    "Anthropic", "OpenAI", "MiniMax", "GLM", "智谱", "DeepSeek", "Google", "Gemini",
    "Meta", "Microsoft", "微软", "Apple", "苹果", "字节", "百度", "阿里", "腾讯", "华为",
}
IMPORTANT_KW = {"融资", "IPO", "上市", "收购", "发布", "开源", "投资", "亿美元", "独角兽", "估值", "合作", "监管", "安全"}
MARKET_NOISE_KW = {"盘前", "盘后", "涨超", "跌超", "中概股", "港股", "A股", "收盘", "开盘", "指数"}
INVESTMENT_NEWS_KW = {
    "融资", "投资", "基金", "股价", "股票", "市值", "估值", "IPO", "上市", "收购",
    "并购", "财报", "营收", "利润", "亏损", "美元", "亿元", "亿美元", "独角兽",
    "证券", "券商", "研报", "受益", "板块", "个股", "概念股", "目标价", "评级",
    "买入", "增持", "减持", "持仓", "$",
    "funding", "fundraise", "fundraising", "raises", "raised", "investment",
    "invests", "invested", "investor", "valuation", "venture capital", "vc",
    "ipo", "acquisition", "acquires", "merger", "stock", "shares", "earnings",
    "revenue", "profit",
}
ROBOT_FINANCING_KW = INVESTMENT_NEWS_KW | {
    "seed", "series a", "series b", "series c", "round", "backed", "capital",
    "raises", "raised", "funding", "financing", "valuation", "venture", "startup",
}

VENDOR_EMOJI = {
    "Anthropic": "🔴", "OpenAI": "🟠", "Google": "🔵", "Gemini": "🔵", "DeepSeek": "🟡",
    "MiniMax": "🔵", "智谱": "🟣", "GLM": "🟣", "字节": "🔵", "百度": "🟢", "阿里": "🟣",
    "腾讯": "🟢", "华为": "🔵", "Apple": "🔵", "苹果": "🔵", "NVIDIA": "🟢", "英伟达": "🟢",
    "Figure": "🦾", "宇树": "🦾", "智元": "🦾", "MagicLab": "🦾", "逐际": "🦾",
}


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", file=sys.stderr)


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def parse_date(raw: str) -> datetime | None:
    raw = clean_text(raw)
    if not raw:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone()
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.astimezone()
            return dt.astimezone()
        except Exception:
            continue
    return None


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def child_text(elem: ET.Element, names: set[str]) -> str:
    for child in list(elem):
        if local_name(child.tag) in names:
            return clean_text("".join(child.itertext()))
    return ""


def parse_feed(data: str, source: str) -> list[dict]:
    items: list[ET.Element] = []
    try:
        root = ET.fromstring(data)
        for elem in root.iter():
            if local_name(elem.tag) in {"item", "entry"}:
                items.append(elem)
    except ET.ParseError:
        # Regex fallback for feeds with minor XML issues.
        blocks = re.findall(r"<(item|entry)[^>]*>(.*?)</\1>", data, re.I | re.S)
        parsed = []
        for _, block in blocks:
            title = re.search(r"<title[^>]*>(.*?)</title>", block, re.I | re.S)
            link = re.search(r"<link[^>]*href=['\"]([^'\"]+)", block, re.I) or re.search(r"<link[^>]*>(.*?)</link>", block, re.I | re.S)
            date = re.search(r"<(pubDate|published|updated)[^>]*>(.*?)</\1>", block, re.I | re.S)
            desc = re.search(r"<(description|summary|content:encoded)[^>]*>(.*?)</\1>", block, re.I | re.S)
            parsed.append({
                "title": clean_text(title.group(1) if title else ""),
                "link": clean_text(link.group(1) if link else ""),
                "date_raw": clean_text(date.group(2) if date else ""),
                "desc": clean_text(desc.group(2) if desc else ""),
                "source": source,
            })
        return parsed

    parsed = []
    for item in items:
        title = child_text(item, {"title"})
        link = child_text(item, {"link"})
        if not link:
            for child in list(item):
                if local_name(child.tag) == "link" and child.attrib.get("href"):
                    link = child.attrib["href"]
                    break
        date_raw = child_text(item, {"pubdate", "published", "updated", "date"})
        desc = child_text(item, {"description", "summary", "encoded", "content"})
        if title:
            parsed.append({"title": title, "link": link, "date_raw": date_raw, "desc": desc[:500], "source": source})
    return parsed


def fetch(url: str, source: str) -> tuple[list[dict], str | None]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (OpenClaw AI News Cron)"})
        with urllib.request.urlopen(req, timeout=18) as resp:
            data = resp.read().decode("utf-8", "ignore")
        return parse_feed(data, source), None
    except Exception as exc:
        return [], str(exc)


def match_terms(text: str, terms: set[str]) -> list[str]:
    low = text.lower()
    return sorted([term for term in terms if term.lower() in low], key=str.lower)


def is_investment_news(text: str) -> bool:
    return bool(match_terms(text, INVESTMENT_NEWS_KW))


def is_robot_financing(text: str, robot_terms: list[str]) -> bool:
    return bool(robot_terms) and bool(match_terms(text, ROBOT_FINANCING_KW))


def enrich(item: dict) -> dict | None:
    text = f"{item.get('title', '')} {item.get('desc', '')}"
    title_text = item.get("title", "")
    ai_terms = match_terms(text, AI_KW)
    robot_terms = match_terms(text, ROBOT_KW)
    company_terms = match_terms(text, COMPANY_KW)
    important_terms = match_terms(text, IMPORTANT_KW)
    market_noise = match_terms(title_text, MARKET_NOISE_KW)

    # Drop pure market flashes unless the title/description contains explicit AI/robot/company substance.
    if market_noise and not (ai_terms or robot_terms or company_terms):
        return None

    score = len(ai_terms) * 2 + len(robot_terms) * 3 + len(company_terms) + len(important_terms)
    if market_noise:
        score -= 2
    if score <= 0:
        return None

    if any(term in important_terms for term in ["融资", "IPO", "上市", "收购", "投资", "亿美元", "估值"]):
        priority = "💰"
    elif len(company_terms) >= 2 or (company_terms and important_terms):
        priority = "🔥"
    elif robot_terms:
        priority = "🦾"
    elif len(ai_terms) >= 2:
        priority = "🤖"
    else:
        priority = "📱"

    vendor = "⚪"
    for key, emoji in VENDOR_EMOJI.items():
        if key.lower() in text.lower():
            vendor = emoji
            break

    dt = parse_date(item.get("date_raw", ""))
    robot_financing = is_robot_financing(text, robot_terms)

    return {
        "title": item.get("title", ""),
        "link": item.get("link", ""),
        "date": dt.isoformat() if dt else item.get("date_raw", ""),
        "desc": item.get("desc", "")[:280],
        "source": item.get("source", ""),
        "priority": priority,
        "vendor": vendor,
        "score": score,
        "investment_news": is_investment_news(text),
        "robot_financing": robot_financing,
        "is_foreign_source": item.get("source", "") in FOREIGN_SOURCES,
        "tags": sorted(set(ai_terms + robot_terms + company_terms + important_terms), key=str.lower)[:10],
    }


def dedup(items: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out = []
    for item in items:
        key = re.sub(r"\W+", "", item["title"].lower())[:40]
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def sort_news(items: list[dict]) -> list[dict]:
    priority_order = {"🔥": 0, "💰": 1, "🦾": 2, "🤖": 3, "📱": 4, "⚪": 5}
    return sorted(items, key=lambda n: (priority_order.get(n.get("priority"), 9), -int(n.get("score", 0)), n.get("source", "")))


def select_global_ai_news(items: list[dict], limit: int = 10, min_foreign: int = 6) -> list[dict]:
    candidates = [n for n in items if n["priority"] != "🦾" and not n.get("investment_news")]
    foreign = [n for n in candidates if n.get("is_foreign_source")]
    domestic = [n for n in candidates if not n.get("is_foreign_source")]
    selected: list[dict] = []
    for item in foreign[:min_foreign]:
        selected.append(item)
    for item in candidates:
        if len(selected) >= limit:
            break
        if item not in selected:
            selected.append(item)
    # If foreign feeds are plentiful, avoid domestic feed flooding by filling from foreign first.
    if len(foreign) >= min_foreign:
        selected = []
        for item in foreign[:limit]:
            selected.append(item)
        for item in domestic:
            if len(selected) >= limit:
                break
            selected.append(item)
    return selected[:limit]


def sort_robot_news(items: list[dict]) -> list[dict]:
    return sorted(items, key=lambda n: (0 if n.get("robot_financing") else 1, -int(n.get("score", 0)), n.get("source", "")))


def main() -> None:
    log("🚀 RSS抓取开始")
    raw_items: list[dict] = []
    source_stats = []
    for url, name in SOURCES:
        items, error = fetch(url, name)
        recent = []
        for item in items:
            dt = parse_date(item.get("date_raw", ""))
            if dt is None or dt >= CUTOFF:
                recent.append(item)
        raw_items.extend(recent)
        source_stats.append({"name": name, "url": url, "count": len(recent), "error": error})
        log(f"📡 {name}: {len(recent)}条" + (f" ({error})" if error else ""))

    enriched = [n for item in raw_items if (n := enrich(item))]
    enriched = sort_news(dedup(enriched))

    ai_news = select_global_ai_news(enriched, limit=10, min_foreign=6)
    robot_news = sort_robot_news([n for n in enriched if n["priority"] == "🦾" or any(t in ROBOT_KW for t in n.get("tags", []))])[:10]
    company_news = [n for n in enriched if any(t in COMPANY_KW for t in n.get("tags", []))][:10]

    result = {
        "generated_at": NOW.isoformat(),
        "window_hours": WINDOW_HOURS,
        "sources": source_stats,
        "counts": {
            "raw_recent": len(raw_items),
            "filtered_total": len(enriched),
            "investment_excluded_from_ai_news": sum(1 for n in enriched if n.get("investment_news") and n["priority"] != "🦾"),
            "foreign_ai_news": sum(1 for n in ai_news if n.get("is_foreign_source")),
            "robot_financing_news": sum(1 for n in robot_news if n.get("robot_financing")),
            "AI_NEWS": len(ai_news),
            "ROBOT_NEWS": len(robot_news),
            "COMPANY_NEWS": len(company_news),
        },
        "AI_NEWS": ai_news,
        "ROBOT_NEWS": robot_news,
        "COMPANY_NEWS": company_news,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
