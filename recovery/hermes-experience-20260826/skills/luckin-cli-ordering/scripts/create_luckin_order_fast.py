#!/usr/bin/env python3
"""Create a Luckin order, send payment QR immediately, and start the fast watcher.

This is intended for the post-preview "确认下单" path where product SKUs,
store, coupon and payable amount have already been previewed and accepted.
It performs side effects: creates a Luckin order and optionally sends the QR.

Usage:
  python3 create_luckin_order_fast.py \
    --dept 382610 --lat 22.569883 --lng 113.953133 \
    -p 5151:SP3571-00085:1 -p 5585:SP4005-00004:1 \
    --coupon SY119541451431200984 \
    --target 'weixin:o9...@im.wechat'
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any


def run(cmd: list[str], timeout: float = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def parse_luckin_stdout(cp: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr or cp.stdout or f"command failed rc={cp.returncode}")
    payload = json.loads(cp.stdout)
    if not payload.get("success") and payload.get("code") != 0:
        raise RuntimeError(cp.stdout[:1000])
    return payload["data"]


def download_payment_qr(order_id: str, url: str) -> Path | None:
    if not url:
        return None
    out_dir = Path.home() / ".luckin" / "pay_qr"
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = out_dir / f"luckin_pay_order_{order_id}.png"
    big = out_dir / f"luckin_pay_order_{order_id}_big.png"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        raw.write_bytes(r.read())
    try:
        from PIL import Image
        im = Image.open(raw).convert("RGB").resize((1056, 1056), Image.Resampling.NEAREST)
        canvas = Image.new("RGB", (1152, 1152), "white")
        canvas.paste(im, (48, 48))
        canvas.save(big)
        return big
    except Exception:
        return raw


def write_delivery_manifest(
    order_id: str,
    target: str,
    pay_qr_path: Path,
    *,
    root: Path | None = None,
) -> Path:
    delivery_dir = root or (Path.home() / ".luckin" / "deliveries")
    delivery_dir.mkdir(parents=True, exist_ok=True)
    path = delivery_dir / f"{order_id}.json"
    payload = {
        "orderId": order_id,
        "target": target,
        "payQrPath": str(pay_qr_path),
        "pickupQrPath": None,
        "pickupReady": False,
        "paymentExpired": False,
        "orderStatus": "待付款",
        "updatedAt": time.time(),
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def hermes_send(target: str, message: str) -> dict[str, Any]:
    start = time.perf_counter()
    cp = run(["hermes", "send", "--json", "--to", target, message], timeout=60)
    result: dict[str, Any]
    try:
        result = json.loads(cp.stdout) if cp.stdout.strip() else {}
    except Exception:
        result = {"raw_stdout": cp.stdout.strip()}
    result["exit_code"] = cp.returncode
    result["stderr"] = cp.stderr.strip()
    result["elapsed_sec"] = round(time.perf_counter() - start, 3)
    if cp.returncode != 0 or result.get("success") is False or result.get("error"):
        raise RuntimeError(json.dumps(result, ensure_ascii=False)[:1000])
    return result


def start_watcher(order_id: str, target: str | None, interval: str) -> int | None:
    if not target:
        return None
    watcher = Path(__file__).with_name("watch_luckin_order.py")
    log_dir = Path.home() / ".luckin" / "watch_state"
    log_dir.mkdir(parents=True, exist_ok=True)
    out = open(log_dir / f"{order_id}.watcher.stdout.log", "a", encoding="utf-8")
    err = open(log_dir / f"{order_id}.watcher.stderr.log", "a", encoding="utf-8")
    env = os.environ.copy()
    env.setdefault("LUCKIN_WATCH_INTERVAL", interval)
    env.setdefault("LUCKIN_WATCH_QUERY_TIMEOUT", "8")
    try:
        p = subprocess.Popen(
            [sys.executable, str(watcher), order_id, target],
            stdout=out,
            stderr=err,
            env=env,
            start_new_session=True,
        )
        return p.pid
    finally:
        out.close()
        err.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dept", type=int, required=True)
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lng", type=float, required=True)
    ap.add_argument("-p", "--product", action="append", required=True)
    ap.add_argument("--coupon", action="append", default=[])
    ap.add_argument("--target", default="")
    ap.add_argument("--watch-interval", default="5")
    ap.add_argument("--no-watch", action="store_true")
    ap.add_argument("--no-send", action="store_true")
    args = ap.parse_args()

    cmd = ["luckin", "order", "create", str(args.dept), "--lat", str(args.lat), "--lng", str(args.lng)]
    for p in args.product:
        cmd += ["-p", p]
    for c in args.coupon:
        cmd += ["--coupon", c]

    t0 = time.perf_counter()
    create_data = parse_luckin_stdout(run(cmd, timeout=60))
    order_id = str(create_data.get("orderIdStr") or create_data.get("orderId"))
    qr_path = download_payment_qr(order_id, create_data.get("payOrderQrCodeUrl") or "")

    detail_data = parse_luckin_stdout(
        run(["luckin", "order", "detail", order_id], timeout=30)
    )
    detail_shop = detail_data.get("shopInfo") or {}
    if int(detail_shop.get("deptId") or 0) != args.dept:
        raise RuntimeError("created order store does not match the confirmed preview")
    if qr_path is None or not qr_path.is_file() or qr_path.stat().st_size <= 0:
        raise RuntimeError("payment QR was not created")
    try:
        from PIL import Image

        with Image.open(qr_path) as image:
            image.verify()
    except Exception as exc:
        raise RuntimeError(f"payment QR is unreadable: {exc}") from exc

    delivery_manifest = None
    if args.target:
        delivery_manifest = write_delivery_manifest(order_id, args.target, qr_path)

    send_result = None
    if args.target and not args.no_send:
        msg = (
            f"☕️ 瑞幸订单已创建，待付款\n"
            f"订单号：{order_id}\n"
            f"应付：¥{create_data.get('discountPrice')}\n"
            f"请在 5 分钟内完成支付；逾期瑞幸会自动取消，不再单独提醒。\n"
            f"MEDIA:{qr_path}" if qr_path else
            f"☕️ 瑞幸订单已创建，待付款\n订单号：{order_id}\n应付：¥{create_data.get('discountPrice')}\n"
            f"请在 5 分钟内完成支付；逾期瑞幸会自动取消，不再单独提醒。"
        )
        send_result = hermes_send(args.target, msg)

    watcher_pid = None
    if args.target and not args.no_watch:
        watcher_pid = start_watcher(order_id, args.target, args.watch_interval)

    print(json.dumps({
        "success": True,
        "orderId": order_id,
        "needPay": create_data.get("needPay"),
        "discountPrice": create_data.get("discountPrice"),
        "verified": True,
        "orderStatus": detail_data.get("orderStatusName"),
        "store": detail_shop.get("deptName"),
        "orderPayAmount": detail_data.get("orderPayAmount"),
        "products": detail_data.get("productInfoList") or [],
        "payQrPath": str(qr_path) if qr_path else None,
        "deliveryManifest": str(delivery_manifest) if delivery_manifest else None,
        "send": send_result,
        "watcherPid": watcher_pid,
        "elapsedSec": round(time.perf_counter() - t0, 3),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
