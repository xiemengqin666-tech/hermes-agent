#!/usr/bin/env python3
"""
美股主要指数和资产数据抓取脚本 v3
使用新浪财经 API（国内直连，无需代理）
数据源：https://hq.sinajs.cn/list=gb_xxx
"""
import json
import re
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))

# 标的映射：Sina代码 → 显示名称 → Yahoo对照
TICKERS = {
    "gb_spy":  ("S&P 500 (SPY ETF)",       "^GSPC"),
    "gb_qqq":  ("NASDAQ 100 (QQQ ETF)",     "^IXIC"),
    "gb_dia":  ("道琼斯 (DIA ETF)",          "^DJI"),
    "gb_iwm":  ("罗素2000 (IWM ETF)",        "^RUT"),
    "gb_vxx":  ("VIX恐慌指数 (VXX ETF代理)", "^VIX"),
    "gb_gld":  ("黄金 (GLD ETF)",            "GC=F"),
    "gb_uso":  ("WTI原油 (USO ETF)",         "CL=F"),
    "gb_tlt":  ("20+年美债 (TLT ETF)",       "ZN=F"),
    "gb_uup":  ("美元指数 (UUP ETF)",        "DX-Y.NYB"),
}

SINA_URL = "https://hq.sinajs.cn/list={symbols}"
HEADERS = {
    'Referer': 'https://finance.sina.com.cn',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
}


def fetch_sina(symbols: list[str]) -> str:
    """从新浪获取行情原始数据"""
    url = SINA_URL.format(symbols=','.join(symbols))
    req = urllib.request.Request(url, headers=HEADERS)
    last_error = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read()
                # 新浪返回 GBK 编码，尝试解码
                for enc in ('gbk', 'gb2312', 'utf-8', 'latin-1'):
                    try:
                        return raw.decode(enc)
                    except (UnicodeDecodeError, LookupError):
                        continue
                return raw.decode('utf-8', errors='replace')
        except Exception as e:
            last_error = e
            if attempt < 2:
                time.sleep(1)
    raise last_error


def fetch_yahoo(symbol: str) -> dict:
    """新浪失败时，从 Yahoo Finance chart API 获取单个标的。"""
    url = "https://query1.finance.yahoo.com/v8/finance/chart/{}?range=5d&interval=1d".format(
        urllib.parse.quote(symbol, safe='')
    )
    req = urllib.request.Request(url, headers={'User-Agent': HEADERS['User-Agent']})
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = json.load(resp)

    result = payload.get('chart', {}).get('result') or []
    if not result:
        raise RuntimeError(f"Yahoo无数据: {symbol}")
    meta = result[0].get('meta', {})
    price = meta.get('regularMarketPrice')
    prev_close = meta.get('chartPreviousClose') or meta.get('previousClose')
    if price is None or prev_close in (None, 0):
        raise RuntimeError(f"Yahoo字段缺失: {symbol}")

    change_abs = price - prev_close
    return {
        "price": round(price, 2),
        "change_pct": round(change_abs / prev_close * 100, 2),
        "change_abs": round(change_abs, 2),
        "prev_close": round(prev_close, 2),
        "open": round(meta.get('regularMarketOpen') or prev_close, 2),
        "high_5d": round(meta.get('regularMarketDayHigh') or price, 2),
        "low_5d": round(meta.get('regularMarketDayLow') or price, 2),
        "high_52w": round(meta.get('fiftyTwoWeekHigh') or 0, 2),
        "low_52w": round(meta.get('fiftyTwoWeekLow') or 0, 2),
        "volume": int(meta.get('regularMarketVolume') or 0),
        "update_time": datetime.fromtimestamp(meta.get('regularMarketTime', 0), CST).strftime('%Y-%m-%d %H:%M:%S') if meta.get('regularMarketTime') else "",
        "source": "Yahoo Finance chart API（新浪失败后补采）",
    }


def parse_sina_line(line: str) -> dict | None:
    """
    解析新浪单条行情数据
    格式: var hq_str_gb_spy="名称,当前价,涨跌幅,时间,涨跌额,今开,最高,最低,52周高,52周低,...";
    """
    match = re.match(r'var hq_str_(\w+)="(.*)";', line.strip())
    if not match:
        return None

    code = match.group(1)
    raw = match.group(2)
    if not raw:
        return None

    fields = raw.split(',')
    if len(fields) < 10:
        return None

    try:
        name = fields[0]
        price = float(fields[1])
        change_pct = float(fields[2])
        update_time = fields[3]
        change_abs = float(fields[4])
        open_price = float(fields[5])
        high = float(fields[6])
        low = float(fields[7])
        high_52w = float(fields[8])
        low_52w = float(fields[9])
        prev_close = price - change_abs if change_abs != 0 else price
        # 成交量 (fields[11])
        volume = int(fields[11]) if len(fields) > 11 and fields[11].isdigit() else 0

        return {
            "code": code,
            "name": name,
            "price": round(price, 2),
            "change_pct": round(change_pct, 2),
            "change_abs": round(change_abs, 2),
            "prev_close": round(prev_close, 2),
            "open": round(open_price, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "high_52w": round(high_52w, 2),
            "low_52w": round(low_52w, 2),
            "volume": volume,
            "update_time": update_time,
            "high_5d": round(high, 2),   # 日内高低（新浪不提供5d，用日内代替）
            "low_5d": round(low, 2),
        }
    except (ValueError, IndexError) as e:
        return {"code": code, "error": f"解析失败: {e}"}


def get_market_data():
    """批量获取所有标的数据"""
    symbols = list(TICKERS.keys())
    print(f"  请求新浪 {len(symbols)} 个标的...", file=sys.stderr)

    try:
        raw = fetch_sina(symbols)
    except Exception as e:
        print(f"  ⚠️ 新浪请求失败，切换 Yahoo 备份源: {e}", file=sys.stderr)
        return get_market_data_from_yahoo()

    lines = [l for l in raw.strip().split('\n') if l.strip()]
    results = []

    for line in lines:
        parsed = parse_sina_line(line)
        if not parsed:
            continue

        code = parsed.get('code', '')
        if code in TICKERS:
            display_name, yahoo_symbol = TICKERS[code]
            entry = {
                "symbol": yahoo_symbol,
                "sina_code": code,
                "name": display_name,
            }
            if "error" in parsed:
                entry["error"] = parsed["error"]
            else:
                entry.update({
                    "price": parsed["price"],
                    "change_pct": parsed["change_pct"],
                    "change_abs": parsed["change_abs"],
                    "prev_close": parsed["prev_close"],
                    "open": parsed["open"],
                    "date": parsed["update_time"].split(' ')[0] if parsed.get("update_time") else "",
                    "high_5d": parsed["high"],
                    "low_5d": parsed["low"],
                    "high_52w": parsed["high_52w"],
                    "low_52w": parsed["low_52w"],
                    "volume": parsed["volume"],
                    "update_time": parsed["update_time"],
                })
            results.append(entry)

            if "error" not in entry:
                arrow = "▲" if entry['change_pct'] > 0 else ("▼" if entry['change_pct'] < 0 else "→")
                print(f"    ✅ {display_name}: {entry['price']:,.2f} {arrow} {entry['change_pct']:+.2f}%", file=sys.stderr)
            else:
                print(f"    ⚠️ {display_name}: {entry['error']}", file=sys.stderr)

    return results


def get_market_data_from_yahoo():
    """新浪不可用时的最小可用备份源。"""
    results = []
    for sina_code, (display_name, yahoo_symbol) in TICKERS.items():
        entry = {"symbol": yahoo_symbol, "sina_code": sina_code, "name": display_name}
        try:
            entry.update(fetch_yahoo(yahoo_symbol))
            arrow = "▲" if entry['change_pct'] > 0 else ("▼" if entry['change_pct'] < 0 else "→")
            print(f"    ✅ {display_name}: {entry['price']:,.2f} {arrow} {entry['change_pct']:+.2f}% [Yahoo]", file=sys.stderr)
        except Exception as e:
            entry["error"] = f"Yahoo备份源失败: {e}"
            print(f"    ⚠️ {display_name}: {entry['error']}", file=sys.stderr)
        results.append(entry)
    if all("error" in r for r in results):
        print("  [ERROR] 新浪和 Yahoo 备份源均失败", file=sys.stderr)
        sys.exit(1)
    return results


def format_output(results):
    """格式化可读文本"""
    now = datetime.now(CST).strftime('%Y-%m-%d %H:%M')
    lines = [
        f"📊 美股市场数据（获取时间: {now} CST）",
        f"📡 数据源: {next((r.get('source') for r in results if r.get('source')), '新浪财经（无需代理）')}",
        "=" * 60,
    ]

    for r in results:
        if "error" in r:
            lines.append(f"\n{r['name']}: ⚠️ {r['error']}")
            continue

        arrow = "▲" if r['change_pct'] > 0 else ("▼" if r['change_pct'] < 0 else "→")
        color = "🟢" if r['change_pct'] > 0 else ("🔴" if r['change_pct'] < 0 else "⚪")
        lines.append(f"\n{r['name']}")
        lines.append(f"  价格: {r['price']:,.2f} {color} {arrow} {r['change_abs']:+,.2f} ({r['change_pct']:+.2f}%)")
        lines.append(f"  今开: {r.get('open', 'N/A')} | 日内高/低: {r.get('high_5d', 'N/A')} / {r.get('low_5d', 'N/A')}")
        if r.get('volume'):
            lines.append(f"  成交量: {r['volume']:,}")
        if r.get('high_52w'):
            lines.append(f"  52周高/低: {r['high_52w']:,} / {r['low_52w']:,}")
        if r.get('update_time'):
            lines.append(f"  最新报价时间: {r['update_time']}")

    return "\n".join(lines)


if __name__ == "__main__":
    print("开始获取美股市场数据（新浪财经）...", file=sys.stderr)
    results = get_market_data()

    if "--json" in sys.argv:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(format_output(results))

    print("数据获取完成", file=sys.stderr)
