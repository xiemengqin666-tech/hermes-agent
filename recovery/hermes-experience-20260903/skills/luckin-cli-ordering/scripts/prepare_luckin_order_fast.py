#!/usr/bin/env python3
"""Prepare one verified Luckin preview and persist it for confirmation."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Any

from create_luckin_order_fast import parse_luckin_stdout, run


PRESETS: dict[str, dict[str, Any]] = {
    "grape-ice-tea-xl-no-sugar": {
        "query": "葡萄冰茶",
        "product_id": 5542,
        "sku_code": "SP3962-00023",
        "amount": 1,
        "expected_name": "葡萄冰茶",
        "expected_attrs": [
            "超大杯",
            "冰",
            "不另外加糖",
            "茉莉花香",
            "常规葡萄果肉",
        ],
    }
}

_TRANSIENT_READ_ERRORS = (
    "eof",
    "timeout",
    "timed out",
    "connection reset",
    "server disconnected",
    "temporary failure",
    "remote end closed",
    "cannot connect",
)


def run_read_only_luckin(
    command: list[str],
    *,
    timeout: float,
    retries: int = 2,
) -> subprocess.CompletedProcess[str]:
    """Retry transient failures only for commands without side effects."""
    for attempt in range(retries + 1):
        try:
            result = run(command, timeout=timeout)
        except subprocess.TimeoutExpired:
            if attempt >= retries:
                raise
        else:
            if result.returncode == 0:
                return result
            error = f"{result.stderr}\n{result.stdout}".lower()
            if attempt >= retries or not any(marker in error for marker in _TRANSIENT_READ_ERRORS):
                return result
        time.sleep(attempt + 1)
    raise RuntimeError("unreachable Luckin retry state")


def pending_preview_path(target: str, root: Path | None = None) -> Path:
    base = root or (Path.home() / ".luckin" / "pending_previews")
    digest = hashlib.sha256(target.encode("utf-8")).hexdigest()[:24]
    return base / f"{digest}.json"


def read_default_store(path: Path | None = None) -> dict[str, Any]:
    source = path or (Path.home() / ".luckin" / "default_order_store.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    required = ("deptId", "deptName", "latitude", "longitude")
    if any(payload.get(key) in (None, "") for key in required):
        raise RuntimeError("default Luckin store is incomplete")
    return payload


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def build_pending_preview(
    target: str,
    store: dict[str, Any],
    preset_name: str,
    preset: dict[str, Any],
    preview: dict[str, Any],
    *,
    now: float | None = None,
) -> dict[str, Any]:
    created_at = time.time() if now is None else now
    products = preview.get("productInfoList") or []
    product = next(
        (
            item
            for item in products
            if int(item.get("productId") or 0) == int(preset["product_id"])
            and str(item.get("skuCode") or "") == preset["sku_code"]
        ),
        None,
    )
    if product is None:
        raise RuntimeError("preview did not return the requested product/SKU")

    addition = str(product.get("additionDesc") or "")
    missing = [item for item in preset["expected_attrs"] if item not in addition]
    if str(product.get("name") or "") != preset["expected_name"] or missing:
        raise RuntimeError(f"preview attributes do not match request: missing={missing}")

    initial = float(preview.get("totalInitialPrice") or product.get("initPrice") or 0)
    payable = float(preview.get("discountPrice") or product.get("estimateTotalPrice") or 0)
    discount = float(preview.get("privilegeMoney") or max(initial - payable, 0))
    payload = {
        "version": 1,
        "status": "prepared",
        "target": target,
        "preset": preset_name,
        "createdAt": created_at,
        "expiresAt": created_at + 900,
        "store": {
            "deptId": int(store["deptId"]),
            "deptName": str(store["deptName"]),
            "latitude": float(store["latitude"]),
            "longitude": float(store["longitude"]),
        },
        "products": [
            {
                "productId": int(product["productId"]),
                "skuCode": str(product["skuCode"]),
                "amount": int(product.get("amount") or preset.get("amount") or 1),
                "name": str(product["name"]),
                "additionDesc": addition,
            }
        ],
        "couponCodes": [str(item) for item in (preview.get("couponCodeList") or [])],
        "totalInitialPrice": initial,
        "discount": discount,
        "payable": payable,
    }
    payload["replyText"] = (
        f"门店：{payload['store']['deptName']}\n"
        f"商品：{product['name']} × {payload['products'][0]['amount']}\n"
        f"规格：{addition}\n"
        f"原价：¥{initial:.2f}\n"
        f"优惠：¥{discount:.2f}\n"
        f"应付：¥{payable:.2f}\n"
        "内容正确请回复：确认下单"
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preset", choices=sorted(PRESETS), required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--pending-root", type=Path)
    parser.add_argument("--store-file", type=Path)
    args = parser.parse_args()

    preset = PRESETS[args.preset]
    store = read_default_store(args.store_file)
    products = parse_luckin_stdout(
        run_read_only_luckin(
            ["luckin", "product", str(store["deptId"]), preset["query"]],
            timeout=30,
        )
    )
    if not any(
        int(item.get("productId") or 0) == int(preset["product_id"])
        and str(item.get("productName") or "") == preset["expected_name"]
        for item in products
    ):
        raise RuntimeError("requested product is not currently listed at the store")

    product_arg = f"{preset['product_id']}:{preset['sku_code']}:{preset['amount']}"
    preview = parse_luckin_stdout(
        run_read_only_luckin(
            ["luckin", "order", "preview", str(store["deptId"]), "-p", product_arg],
            timeout=45,
        )
    )
    pending = build_pending_preview(args.target, store, args.preset, preset, preview)
    path = pending_preview_path(args.target, args.pending_root)
    _write_json_atomic(path, pending)
    print(
        json.dumps(
            {
                "success": True,
                "verified": True,
                "pendingPreview": str(path),
                "expiresAt": pending["expiresAt"],
                "replyText": pending["replyText"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
