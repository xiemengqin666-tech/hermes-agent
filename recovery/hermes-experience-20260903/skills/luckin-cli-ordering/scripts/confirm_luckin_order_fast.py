#!/usr/bin/env python3
"""Atomically create a Luckin order from the latest confirmed preview."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from prepare_luckin_order_fast import pending_preview_path


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_pending_preview(
    target: str,
    root: Path | None = None,
    *,
    now: float | None = None,
) -> tuple[Path, dict[str, Any]]:
    path = pending_preview_path(target, root)
    payload = json.loads(path.read_text(encoding="utf-8"))
    current = time.time() if now is None else now
    if payload.get("target") != target:
        raise RuntimeError("pending preview belongs to another chat")
    if payload.get("status") != "prepared":
        raise RuntimeError(f"pending preview is not creatable: {payload.get('status')}")
    if current > float(payload.get("expiresAt") or 0):
        raise RuntimeError("pending preview expired; preview the order again")
    return path, payload


def build_create_command(payload: dict[str, Any], target: str, script: Path) -> list[str]:
    store = payload["store"]
    command = [
        sys.executable,
        str(script),
        "--dept",
        str(store["deptId"]),
        "--lat",
        str(store["latitude"]),
        "--lng",
        str(store["longitude"]),
    ]
    for product in payload["products"]:
        command += [
            "-p",
            f"{product['productId']}:{product['skuCode']}:{product['amount']}",
        ]
    for coupon in payload.get("couponCodes") or []:
        command += ["--coupon", str(coupon)]
    command += ["--target", target, "--no-send"]
    return command


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True)
    parser.add_argument("--pending-root", type=Path)
    parser.add_argument("--create-script", type=Path)
    args = parser.parse_args()

    path = pending_preview_path(args.target, args.pending_root)
    lock_path = path.with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RuntimeError("this preview confirmation is already being processed") from exc

    try:
        os.write(lock_fd, f"{os.getpid()} {time.time()}\n".encode("ascii"))
        os.close(lock_fd)
        preview_path, pending = load_pending_preview(args.target, args.pending_root)
        pending["status"] = "creating"
        pending["claimedAt"] = time.time()
        _write_json_atomic(preview_path, pending)

        script = args.create_script or Path(__file__).with_name("create_luckin_order_fast.py")
        try:
            result = subprocess.run(
                build_create_command(pending, args.target, script),
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except Exception as exc:
            pending["status"] = "needs_review"
            pending["error"] = f"{type(exc).__name__}: {exc}"[:1000]
            _write_json_atomic(preview_path, pending)
            raise RuntimeError(
                "order creation outcome is uncertain; preview locked to prevent a duplicate order"
            ) from exc
        if result.returncode != 0:
            pending["status"] = "needs_review"
            pending["error"] = (result.stderr or result.stdout or "create failed")[:1000]
            _write_json_atomic(preview_path, pending)
            raise RuntimeError("order creation failed; preview locked to prevent duplicate creation")

        try:
            created = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            pending["status"] = "needs_review"
            pending["error"] = "create helper returned invalid JSON"
            _write_json_atomic(preview_path, pending)
            raise RuntimeError(
                "order creation outcome is uncertain; preview locked to prevent a duplicate order"
            ) from exc
        if not created.get("success") or not created.get("verified"):
            pending["status"] = "needs_review"
            _write_json_atomic(preview_path, pending)
            raise RuntimeError("order creation result was not verified")

        pending["status"] = "consumed"
        pending["consumedAt"] = time.time()
        pending["orderId"] = str(created.get("orderId") or "")
        pending["payQrPath"] = created.get("payQrPath")
        _write_json_atomic(preview_path, pending)

        payable = float(created.get("discountPrice") or pending.get("payable") or 0)
        reply_text = (
            "瑞幸订单已创建，待付款\n"
            f"应付：¥{payable:.2f}\n"
            "请在 5 分钟内完成支付；逾期瑞幸会自动取消，不再单独提醒。\n"
            f"MEDIA:{created['payQrPath']}"
        )
        print(
            json.dumps(
                {
                    "success": True,
                    "verified": True,
                    "orderStatus": created.get("orderStatus"),
                    "watcherPid": created.get("watcherPid"),
                    "replyText": reply_text,
                },
                ensure_ascii=False,
            )
        )
    finally:
        lock_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
