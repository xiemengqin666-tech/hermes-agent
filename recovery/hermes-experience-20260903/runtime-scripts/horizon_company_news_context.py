#!/usr/bin/env python3
"""Collect Horizon + fresh news context for daily company positive/negative news cron.

The cron agent receives this script's stdout before it writes the final report.
It intentionally stays fast: read latest Horizon summaries, then fetch Google
News RSS candidates for the tracked companies.
"""
from __future__ import annotations

import datetime as dt
import email.utils
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from zoneinfo import ZoneInfo

HORIZON_SUMMARY_DIR = Path.home() / ".hermes" / "apps" / "horizon" / "data" / "summaries"
MAX_HORIZON_FILES = 5
MAX_HORIZON_SNIPPETS_PER_COMPANY = 3
MAX_RSS_ITEMS_PER_COMPANY = 4
RSS_TIMEOUT_SECONDS = 12
MARKET_SCRIPT = Path.home() / ".hermes" / "scripts" / "us_stock_market_data.py"

COMPANIES: dict[str, list[str]] = {
    "NVIDIA": ["NVIDIA", "英伟达", "NVDA", "Jensen Huang", "黄仁勋", "Blackwell", "CUDA"],
    "台积电": ["TSMC", "台积电", "Taiwan Semiconductor", "2330.TW"],
    "特斯拉": ["Tesla", "特斯拉", "TSLA", "Elon Musk", "马斯克", "Optimus", "FSD"],
    "AMD": ["AMD", "超威", "Advanced Micro Devices", "MI300", "MI350", "Instinct"],
    "Intel": ["Intel", "英特尔", "INTC", "Gaudi", "Intel Foundry"],
    "美光": ["Micron", "美光", "MU", "HBM", "DRAM", "NAND"],
    "高通": ["Qualcomm", "高通", "QCOM", "Snapdragon", "骁龙"],
    "Meta": ["Meta", "Facebook", "Instagram", "WhatsApp", "Zuckerberg", "扎克伯格", "Reality Labs"],
}

COMPANY_TICKERS = {
    "NVIDIA": "NVDA",
    "台积电": "TSM",  # 美股 ADR
    "特斯拉": "TSLA",
    "AMD": "AMD",
    "Intel": "INTC",
    "美光": "MU",
    "高通": "QCOM",
    "Meta": "META",
}


def compact_line(line: str, limit: int = 520) -> str:
    line = re.sub(r"\s+", " ", line.strip())
    return line[:limit]


def alias_regex(aliases: list[str]) -> re.Pattern[str]:
    parts: list[str] = []
    for alias in aliases:
        escaped = re.escape(alias)
        # Avoid noisy substring hits such as Intel -> intelligence or MU -> humanoid.
        if re.fullmatch(r"[A-Za-z0-9.]+", alias):
            parts.append(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])")
        else:
            parts.append(escaped)
    return re.compile("|".join(parts), re.IGNORECASE)


def print_horizon_context() -> None:
    print("\n## Horizon summaries considered")
    files = sorted(HORIZON_SUMMARY_DIR.glob("horizon-*-zh.md"), reverse=True)[:MAX_HORIZON_FILES]
    if not files:
        print("- ⚠️ No Horizon summary files found.")
        return
    for p in files:
        print(f"- {p.name}")

    docs: list[tuple[Path, list[str]]] = []
    for p in files:
        try:
            docs.append((p, p.read_text(encoding="utf-8", errors="replace").splitlines()))
        except Exception as exc:  # pragma: no cover - defensive in cron
            print(f"- failed_to_read {p}: {exc}")

    print("\n## Horizon matched snippets by company")
    for company, aliases in COMPANIES.items():
        pattern = alias_regex(aliases)
        snippets: list[str] = []
        seen: set[str] = set()
        for path, lines in docs:
            for idx, line in enumerate(lines):
                if not pattern.search(line):
                    continue
                start = max(0, idx - 2)
                end = min(len(lines), idx + 3)
                block_lines = [compact_line(x) for x in lines[start:end] if compact_line(x)]
                block = " / ".join(block_lines)
                key = re.sub(r"\W+", "", block.lower())[:180]
                if key in seen:
                    continue
                seen.add(key)
                snippets.append(f"- {path.name}: {block}")
                if len(snippets) >= MAX_HORIZON_SNIPPETS_PER_COMPANY:
                    break
            if len(snippets) >= MAX_HORIZON_SNIPPETS_PER_COMPANY:
                break
        print(f"\n### {company}")
        if snippets:
            print("\n".join(snippets))
        else:
            print("- Horizon最近摘要未命中。")


def google_news_url(company: str, aliases: list[str]) -> str:
    # Keep queries broad enough for Google News but bounded to recent items.
    important_aliases = aliases[:4]
    quoted = [f'"{a}"' if " " in a or re.search(r"[\u4e00-\u9fff]", a) else a for a in important_aliases]
    query = f"({' OR '.join(quoted)}) when:2d"
    params = urllib.parse.urlencode({
        "q": query,
        "hl": "en-US",
        "gl": "US",
        "ceid": "US:en",
    })
    return f"https://news.google.com/rss/search?{params}"


def fetch_google_news(company: str, aliases: list[str]) -> list[dict[str, str]]:
    url = google_news_url(company, aliases)
    req = urllib.request.Request(url, headers={"User-Agent": "HermesCompanyNewsCron/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=RSS_TIMEOUT_SECONDS) as resp:
            raw = resp.read(512_000)
    except Exception as exc:
        return [{"error": f"fetch_failed: {exc}", "url": url}]

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        return [{"error": f"parse_failed: {exc}", "url": url}]

    items: list[dict[str, str]] = []
    seen_titles: set[str] = set()
    for item in root.findall("./channel/item"):
        title = compact_line(item.findtext("title") or "", 240)
        link = item.findtext("link") or ""
        pub_date = item.findtext("pubDate") or ""
        source = item.findtext("source") or "Google News"
        if not title:
            continue
        title_key = re.sub(r"\W+", "", title.lower())[:160]
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)
        iso_date = pub_date
        try:
            parsed = email.utils.parsedate_to_datetime(pub_date)
            if parsed:
                iso_date = parsed.astimezone().isoformat(timespec="minutes")
        except Exception:
            pass
        items.append({"title": title, "source": source, "published": iso_date, "link": link})
        if len(items) >= MAX_RSS_ITEMS_PER_COMPANY:
            break
    return items


def fetch_stock_snapshot(symbol: str) -> dict[str, object]:
    url = "https://query1.finance.yahoo.com/v8/finance/chart/{}?range=1y&interval=1d".format(
        urllib.parse.quote(symbol, safe="")
    )
    req = urllib.request.Request(url, headers={"User-Agent": "HermesCompanyNewsCron/1.0"})
    with urllib.request.urlopen(req, timeout=RSS_TIMEOUT_SECONDS) as resp:
        payload = json.load(resp)
    results = payload.get("chart", {}).get("result") or []
    if not results:
        raise RuntimeError(f"Yahoo无数据: {symbol}")

    result = results[0]
    meta = result.get("meta", {})
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    closes = [float(x) for x in quote.get("close", []) if x is not None]
    if len(closes) < 2:
        raise RuntimeError(f"Yahoo收盘序列不足: {symbol}")

    price = float(meta.get("regularMarketPrice") or closes[-1])
    previous_close = float(meta.get("previousClose") or closes[-2])
    low_52w, high_52w = min(closes), max(closes)
    span = high_52w - low_52w
    market_time = int(meta.get("regularMarketTime") or 0)
    timezone_name = meta.get("exchangeTimezoneName") or "America/New_York"
    quoted_at = (
        dt.datetime.fromtimestamp(market_time, dt.timezone.utc)
        .astimezone(ZoneInfo(timezone_name))
        .strftime("%Y-%m-%d %H:%M %Z")
        if market_time else "未知"
    )
    return {
        "price": round(price, 2),
        "change_pct": round((price - previous_close) / previous_close * 100, 2),
        "ma20": round(sum(closes[-20:]) / min(20, len(closes)), 2),
        "ma50": round(sum(closes[-50:]) / min(50, len(closes)), 2),
        "high_52w": round(high_52w, 2),
        "low_52w": round(low_52w, 2),
        "position_52w_pct": round((price - low_52w) / span * 100, 1) if span else 50.0,
        "quoted_at": quoted_at,
        "currency": meta.get("currency") or "USD",
        "source": "Yahoo Finance chart API",
    }


def print_market_context() -> None:
    print("\n## Broad market technical snapshot")
    try:
        completed = subprocess.run(
            [sys.executable, str(MARKET_SCRIPT), "--json"],
            capture_output=True,
            text=True,
            timeout=45,
            check=True,
        )
        rows = json.loads(completed.stdout)
    except Exception as exc:
        print(f"- ⚠️ broad_market_failed: {exc}")
    else:
        for row in rows:
            if "error" in row:
                print(f"- {row.get('name', row.get('symbol'))}: ⚠️ {row['error']}")
                continue
            print(
                f"- {row['name']}: {row['price']} ({row['change_pct']:+.2f}%), "
                f"52周 {row.get('low_52w', 'N/A')}–{row.get('high_52w', 'N/A')}, "
                f"报价时间 {row.get('update_time', '未知')}"
            )

    print("\n## Latest US stock snapshot by company")
    for company, symbol in COMPANY_TICKERS.items():
        try:
            row = fetch_stock_snapshot(symbol)
        except Exception as exc:
            print(f"- {company} ({symbol}): ⚠️ quote_failed: {exc}")
            continue
        print(
            f"- {company} ({symbol}): {row['currency']} {row['price']} ({row['change_pct']:+.2f}%), "
            f"MA20 {row['ma20']}, MA50 {row['ma50']}, "
            f"52周位置 {row['position_52w_pct']}% ({row['low_52w']}–{row['high_52w']}), "
            f"报价时间 {row['quoted_at']}, 来源 {row['source']}"
        )


def print_google_news_context() -> None:
    print("\n## Fresh Google News RSS candidates by company (last ~2 days)")
    for company, aliases in COMPANIES.items():
        print(f"\n### {company}")
        items = fetch_google_news(company, aliases)
        if not items:
            print("- 未抓到候选新闻。")
            continue
        for item in items:
            if "error" in item:
                print(f"- ⚠️ {item['error']} | {item.get('url', '')}")
                continue
            print(f"- {item['title']} | {item['source']} | {item['published']}")


def main() -> None:
    now = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    print("# Horizon-enhanced company positive/negative news context")
    print(f"generated_at: {now}")
    print(f"summary_dir: {HORIZON_SUMMARY_DIR}")
    print("companies: " + ", ".join(COMPANIES.keys()))
    print_market_context()
    print_horizon_context()
    print_google_news_context()
    print("\n## Cron usage note")
    print("- Use Horizon snippets for AI/semiconductor context and Google News RSS for freshness.")
    print("- Classify news as positive or negative based on business impact, not headline sentiment.")
    print("- If a company has no material positive/negative update, say 暂无高置信度重点新闻, do not invent.")


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(0)
