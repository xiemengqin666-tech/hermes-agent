#!/usr/bin/env python3
"""Fast Luckin order watcher.

Polls a Luckin order and notifies status transitions via `hermes send`.

Usage:
  python3 watch_luckin_order.py <order_id> [target]

Defaults are tuned for Pigger's Luckin flow:
- direct raw Luckin MCP query first (faster + explicit timeout), CLI fallback second
- 5s poll interval, configurable by LUCKIN_WATCH_INTERVAL
- JSON-validated Hermes delivery; logs exact send result
- pickup QR generated with real Chinese font fallbacks
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

if len(sys.argv) < 2:
    raise SystemExit("Usage: watch_luckin_order.py <order_id> [target]")

ORDER_ID = sys.argv[1]
TARGET = sys.argv[2] if len(sys.argv) >= 3 else "weixin"
POLL_INTERVAL = float(os.getenv("LUCKIN_WATCH_INTERVAL", "5"))
QUERY_TIMEOUT = float(os.getenv("LUCKIN_WATCH_QUERY_TIMEOUT", "8"))
CLI_TIMEOUT = float(os.getenv("LUCKIN_WATCH_CLI_TIMEOUT", "12"))
MCP_URL = os.getenv("LUCKIN_MCP_URL", "https://gwmcp.lkcoffee.com/order/user/mcp")

STATE_DIR = Path.home() / ".luckin" / "watch_state"
STATE_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = STATE_DIR / f"{ORDER_ID}.last_status"
LOG_FILE = STATE_DIR / f"{ORDER_ID}.watch.log"
READY_SENT_FILE = STATE_DIR / f"{ORDER_ID}.pickup_qr_sent.json"
QR_DIR = Path.home() / ".luckin" / "take_qr"
QR_DIR.mkdir(parents=True, exist_ok=True)

BAD_WORDS = ("取消", "退款", "异常", "失败")
READY_WORDS = ("制作完成", "等待取餐", "待取餐", "可取餐", "请取餐", "待自提")
PROGRESS_WORDS = ("下单成功", "制作中")


def log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")


def should_notify_status(name: str) -> bool:
    return any(word in name for word in BAD_WORDS + READY_WORDS + PROGRESS_WORDS)


def is_unpaid_expiry(last_status: str, status: Any, name: str) -> bool:
    """Return true for Luckin's automatic cancellation of an unpaid order."""
    return (
        last_status.startswith("10:")
        and str(status) == "100"
        and "取消" in name
    )


def _update_delivery_manifest(
    order_id: str,
    status_name: str,
    *,
    root: Path | None = None,
    **updates: Any,
) -> Path | None:
    delivery_dir = root or (Path.home() / ".luckin" / "deliveries")
    path = delivery_dir / f"{order_id}.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload.update({"orderStatus": status_name, "updatedAt": time.time(), **updates})
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        return path
    except (OSError, TypeError, ValueError) as exc:
        log(f"delivery manifest update failed: {exc}")
        return None


def mark_delivery_status(
    order_id: str,
    status_name: str,
    *,
    root: Path | None = None,
) -> Path | None:
    return _update_delivery_manifest(order_id, status_name, root=root)


def mark_delivery_ready(
    order_id: str,
    pickup_qr_path: Path,
    *,
    status_name: str = "等待取餐",
    root: Path | None = None,
) -> Path | None:
    return _update_delivery_manifest(
        order_id,
        status_name,
        root=root,
        pickupQrPath=str(pickup_qr_path),
        pickupReady=True,
    )


def mark_delivery_closed(
    order_id: str,
    status_name: str,
    *,
    payment_expired: bool = False,
    root: Path | None = None,
) -> Path | None:
    return _update_delivery_manifest(
        order_id,
        status_name,
        root=root,
        paymentExpired=payment_expired,
    )


def progress_message(status_name: str) -> str:
    return "制作中" if "制作" in status_name else "下单成功"


def ready_message(take_code: str, qr_path: str | None) -> str:
    message = f"可以取餐了\n取餐码：{take_code}"
    if qr_path:
        return f"{message}\nMEDIA:{qr_path}"
    return f"{message}\n二维码生成失败，直接报取餐码也可以。"


def failure_message(status_name: str) -> str:
    return f"瑞幸订单状态：{status_name}"


def load_token() -> str | None:
    token = os.getenv("LUCKIN_MCP_ORDER_TOKEN")
    if token:
        return token
    env_path = Path.home() / ".luckin" / ".env"
    if not env_path.exists():
        return None
    for raw in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k == "LUCKIN_MCP_ORDER_TOKEN":
            return v.strip().strip('"').strip("'")
    return None


def _extract_mcp_payload(resp_text: str) -> dict[str, Any]:
    # The endpoint may return plain JSON or SSE-ish "data:" lines.
    data_lines = [ln[5:].strip() for ln in resp_text.splitlines() if ln.startswith("data:")]
    if data_lines:
        resp_text = "\n".join(data_lines)
    outer = json.loads(resp_text)
    content = (outer.get("result") or {}).get("content") or outer.get("result")
    if isinstance(content, list):
        text = "".join(x.get("text", "") if isinstance(x, dict) else str(x) for x in content)
    elif isinstance(content, str):
        text = content
    else:
        text = json.dumps(content, ensure_ascii=False)
    payload = json.loads(text)
    if not payload.get("success") and payload.get("code") != 0:
        raise RuntimeError(text[:500])
    return payload["data"]


def query_raw() -> dict[str, Any]:
    token = load_token()
    if not token:
        raise RuntimeError("missing LUCKIN_MCP_ORDER_TOKEN")
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "queryOrderDetailInfo", "arguments": {"orderId": ORDER_ID}},
    }
    req = urllib.request.Request(
        MCP_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": "Hermes-Luckin-Watcher/2.0",
            "Connection": "close",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=QUERY_TIMEOUT) as r:
        return _extract_mcp_payload(r.read().decode("utf-8", "replace"))


def query_cli() -> dict[str, Any]:
    cp = subprocess.run(
        ["luckin", "order", "detail", ORDER_ID],
        capture_output=True,
        text=True,
        timeout=CLI_TIMEOUT,
    )
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr or cp.stdout or f"luckin exit {cp.returncode}")
    payload = json.loads(cp.stdout)
    if not payload.get("success") and payload.get("code") != 0:
        raise RuntimeError(cp.stdout[:500])
    return payload["data"]


def query() -> dict[str, Any]:
    start = time.perf_counter()
    try:
        data = query_raw()
        log(f"poll ok source=raw dt={time.perf_counter() - start:.2f}s status={data.get('orderStatus')}:{data.get('orderStatusName')}")
        return data
    except Exception as raw_exc:
        log(f"raw query failed after {time.perf_counter() - start:.2f}s: {type(raw_exc).__name__}: {raw_exc}")
    start = time.perf_counter()
    data = query_cli()
    log(f"poll ok source=cli dt={time.perf_counter() - start:.2f}s status={data.get('orderStatus')}:{data.get('orderStatusName')}")
    return data


def send(msg: str) -> bool:
    start = time.perf_counter()
    try:
        cp = subprocess.run(
            ["hermes", "send", "--json", "--to", TARGET, msg],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except Exception as exc:
        log(f"send failed exception: {exc}")
        return False
    dt = time.perf_counter() - start
    out = (cp.stdout or "").strip()
    err = (cp.stderr or "").strip()
    log(f"send rc={cp.returncode} dt={dt:.2f}s stdout={out[:1000]} stderr={err[:500]}")
    if cp.returncode != 0:
        return False
    try:
        result = json.loads(out) if out else {}
    except Exception:
        # Chat-scoped Weixin delivery needs structured routing proof. A plain
        # "sent" line cannot prove which account/chat received the message.
        return not TARGET.startswith("weixin:")
    if isinstance(result, dict) and result.get("success") is False:
        return False
    if TARGET.startswith("weixin:") and isinstance(result, dict):
        expected = TARGET.split(":", 1)[1]
        got = str(result.get("chat_id") or result.get("target") or "")
        note = str(result.get("note") or "")
        context_used = result.get("context_token_used")
        unsafe_home_fallback = "home channel" in note.lower()
        unsafe_account_route = context_used is not True
        unsafe_chat_mismatch = got != expected
        if unsafe_home_fallback or unsafe_account_route or unsafe_chat_mismatch:
            log(
                "send target validation failed "
                f"expected={expected} got={got} context_token_used={context_used} note={note}"
            )
            return False
    return True


def generate_pickup_qr(take_order_id: str, take_code: str) -> str | None:
    if not take_order_id:
        return None
    final_path = QR_DIR / f"luckin_take_order_{ORDER_ID}_clean.png"
    if final_path.exists() and final_path.stat().st_size > 20_000:
        return str(final_path)
    qr_py = r'''
from pathlib import Path
import sys
import qrcode
from PIL import Image, ImageDraw, ImageFont
order, take_order_id, take_code, final_path = sys.argv[1:5]
final_path = Path(final_path)
fonts = [
    '/System/Library/Fonts/PingFang.ttc',
    '/System/Library/Fonts/STHeiti Medium.ttc',
    '/Library/Fonts/Arial Unicode.ttf',
    '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
    '/System/Library/Fonts/Helvetica.ttc',
]
def font(size):
    for fp in fonts:
        try:
            return ImageFont.truetype(fp, size)
        except Exception:
            pass
    return ImageFont.load_default()
def center(draw, y, text, fnt, fill=(0,0,0)):
    box = draw.textbbox((0,0), text, font=fnt)
    draw.text(((1100 - (box[2]-box[0]))//2, y), text, font=fnt, fill=fill)
qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=18, border=4)
qr.add_data(take_order_id); qr.make(fit=True)
qr_img = qr.make_image(fill_color='black', back_color='white').convert('RGB')
qr_img = qr_img.resize((780,780), Image.Resampling.NEAREST)
canvas = Image.new('RGB', (1100, 1500), 'white')
d = ImageDraw.Draw(canvas)
center(d, 60, '瑞幸取餐二维码', font(64))
center(d, 155, '取餐码', font(44), (80,80,80))
center(d, 205, take_code, font(180))
canvas.paste(qr_img, (160, 450))
center(d, 1285, f'扫码不行就报取餐码 {take_code}', font(34), (60,60,60))
canvas.save(final_path)
print(final_path)
'''
    cp = subprocess.run(
        ["uv", "run", "--with", "qrcode[pil]", "python3", "-c", qr_py, ORDER_ID, take_order_id, take_code, str(final_path)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if cp.returncode != 0:
        log(f"qr gen failed rc={cp.returncode}: {cp.stderr or cp.stdout}")
        return None
    log(f"qr generated path={final_path} size={final_path.stat().st_size if final_path.exists() else 0}")
    return str(final_path)


def status_key(data: dict[str, Any]) -> str:
    return f"{data.get('orderStatus')}:{data.get('orderStatusName') or '未知状态'}"


def is_ready(data: dict[str, Any]) -> bool:
    status = data.get("orderStatus")
    name = data.get("orderStatusName") or ""
    return any(w in name for w in READY_WORDS) or (
        isinstance(status, int) and status >= 40 and not any(w in name for w in BAD_WORDS)
    )


def seed_current_status() -> None:
    try:
        data = query()
        STATE_FILE.write_text(status_key(data), encoding="utf-8")
        log(f"seeded {status_key(data)} interval={POLL_INTERVAL}s target={TARGET}")
    except Exception as exc:
        log(f"seed failed: {type(exc).__name__}: {exc}")


def main() -> None:
    seed_current_status()
    log(f"watcher started target={TARGET}")
    consecutive_errors = 0
    while True:
        loop_start = time.perf_counter()
        try:
            data = query()
            consecutive_errors = 0
            key = status_key(data)
            last = STATE_FILE.read_text(encoding="utf-8").strip() if STATE_FILE.exists() else ""
            status = data.get("orderStatus")
            name = data.get("orderStatusName") or "未知状态"
            take = data.get("takeMealCodeInfo") or {}
            code = take.get("code") or "生成中"
            take_order_id = take.get("takeOrderId") or ""
            shop = (data.get("shopInfo") or {}).get("deptName") or "瑞幸门店"

            if key != last:
                log(f"transition {last or '<none>'} -> {key}")
                if any(w in name for w in BAD_WORDS):
                    unpaid_expiry = is_unpaid_expiry(last, status, name)
                    mark_delivery_closed(ORDER_ID, name, payment_expired=unpaid_expiry)
                    if unpaid_expiry:
                        # The payment message already explains the five-minute
                        # expiry. Weixin cannot edit that prior native message,
                        # so avoid a second standalone cancellation message.
                        STATE_FILE.write_text(key, encoding="utf-8")
                        log("unpaid order expired; standalone cancellation notification suppressed")
                        break
                    if send(failure_message(name)):
                        STATE_FILE.write_text(key, encoding="utf-8")
                        break
                    time.sleep(31)
                    continue
                if is_ready(data):
                    qr_path = generate_pickup_qr(take_order_id, code)
                    if qr_path:
                        mark_delivery_ready(ORDER_ID, Path(qr_path), status_name=name)
                    msg = ready_message(code, qr_path)
                    sent_ok = send(msg)
                    if sent_ok and qr_path:
                        STATE_FILE.write_text(key, encoding="utf-8")
                        sent_payload = {
                            "orderId": ORDER_ID,
                            "statusKey": key,
                            "takeCode": code,
                            "shop": shop,
                            "qrPath": qr_path,
                            "target": TARGET,
                            "sentAt": time.strftime("%Y-%m-%d %H:%M:%S"),
                        }
                        READY_SENT_FILE.write_text(json.dumps(sent_payload, ensure_ascii=False, indent=2), encoding="utf-8")
                        # Keep stdout quiet: if this watcher is launched with notify_on_complete,
                        # stdout is user-visible. The sent file + watch log are enough for supervisors.
                        log("pickup_qr_sent " + json.dumps(sent_payload, ensure_ascii=False))
                        break
                    time.sleep(31)
                    continue
                if should_notify_status(name):
                    if send(progress_message(name)):
                        STATE_FILE.write_text(key, encoding="utf-8")
                        mark_delivery_status(ORDER_ID, name)
                        # Pre-generate only after the user-visible transition is sent.
                        if code and code != "生成中" and take_order_id:
                            generate_pickup_qr(take_order_id, code)
                    else:
                        time.sleep(31)
                        continue
                else:
                    STATE_FILE.write_text(key, encoding="utf-8")
            elapsed = time.perf_counter() - loop_start
            time.sleep(max(0.5, POLL_INTERVAL - elapsed))
        except Exception as exc:
            consecutive_errors += 1
            log(f"error {consecutive_errors}: {type(exc).__name__}: {exc}")
            if consecutive_errors in (3, 9):
                send("瑞幸订单状态查询暂时失败，仍在重试。")
            if consecutive_errors >= 18:
                send("瑞幸订单状态查询连续失败，已停止；回复“查订单”可重新查询。")
                break
            time.sleep(min(POLL_INTERVAL, 5))


if __name__ == "__main__":
    main()
