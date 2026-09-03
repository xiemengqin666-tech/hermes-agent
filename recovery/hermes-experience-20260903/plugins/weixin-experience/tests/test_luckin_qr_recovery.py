import json
import importlib.util
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from gateway.config import PlatformConfig
from gateway.platforms.base import SendResult

_PLUGIN_PATH = Path(__file__).parents[1] / "__init__.py"
_SPEC = importlib.util.spec_from_file_location("weixin_experience_under_test", _PLUGIN_PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

_find_luckin_delivery_for_chat = _MODULE._find_luckin_delivery_for_chat
_is_luckin_qr_recovery_request = _MODULE._is_luckin_qr_recovery_request
_find_pending_luckin_preview_for_chat = _MODULE._find_pending_luckin_preview_for_chat
_luckin_workflow_prompt = _MODULE._luckin_workflow_prompt


def test_qr_recovery_request_is_narrow():
    assert _is_luckin_qr_recovery_request("二维码呢？怎么没有二维码")
    assert _is_luckin_qr_recovery_request("怎么没有二维码")
    assert _is_luckin_qr_recovery_request("瑞幸付款码没发出来")
    assert not _is_luckin_qr_recovery_request("帮我生成一个活动二维码")
    assert not _is_luckin_qr_recovery_request("瑞幸。葡萄冰茶超大杯不加糖")


def test_find_delivery_is_scoped_to_chat_and_prefers_ready_qr(tmp_path):
    pay = tmp_path / "pay.png"
    pickup = tmp_path / "pickup.png"
    pay.write_bytes(b"pay")
    pickup.write_bytes(b"pickup")
    deliveries = tmp_path / "deliveries"
    deliveries.mkdir()
    (deliveries / "order.json").write_text(
        json.dumps(
            {
                "target": "weixin:chat-a",
                "payQrPath": str(pay),
                "pickupQrPath": str(pickup),
                "pickupReady": True,
                "updatedAt": time.time(),
            }
        ),
        encoding="utf-8",
    )

    assert _find_luckin_delivery_for_chat("chat-a", deliveries) == pickup
    assert _find_luckin_delivery_for_chat("chat-b", deliveries) is None


def test_find_delivery_rejects_stale_or_missing_files(tmp_path):
    deliveries = tmp_path / "deliveries"
    deliveries.mkdir()
    (deliveries / "stale.json").write_text(
        json.dumps(
            {
                "target": "weixin:chat-a",
                "payQrPath": str(tmp_path / "missing.png"),
                "updatedAt": time.time() - 7200,
            }
        ),
        encoding="utf-8",
    )

    assert _find_luckin_delivery_for_chat("chat-a", deliveries) is None


def test_find_delivery_rejects_cancelled_payment_qr(tmp_path):
    pay = tmp_path / "pay.png"
    pay.write_bytes(b"pay")
    deliveries = tmp_path / "deliveries"
    deliveries.mkdir()
    (deliveries / "cancelled.json").write_text(
        json.dumps(
            {
                "target": "weixin:chat-a",
                "payQrPath": str(pay),
                "paymentExpired": True,
                "orderStatus": "已取消",
                "updatedAt": time.time(),
            }
        ),
        encoding="utf-8",
    )

    assert _find_luckin_delivery_for_chat("chat-a", deliveries) is None


def test_luckin_request_gets_model_guided_fast_path_prompt():
    prompt = _luckin_workflow_prompt("瑞幸。葡萄冰茶超大杯不加糖", "chat-a")

    assert "luckin-cli-ordering" in prompt
    assert "do not use browser" in prompt
    assert "weixin:chat-a" in prompt


def test_confirmation_recovers_pending_preview_after_new(tmp_path):
    previews = tmp_path / "pending"
    previews.mkdir()
    (previews / "preview.json").write_text(
        json.dumps(
            {
                "target": "weixin:chat-a",
                "status": "prepared",
                "expiresAt": time.time() + 600,
            }
        ),
        encoding="utf-8",
    )

    pending = _find_pending_luckin_preview_for_chat("chat-a", previews)
    prompt = _luckin_workflow_prompt("确认下单", "chat-a", previews)

    assert pending is not None
    assert "confirm_luckin_order_fast.py" in prompt
    assert "weixin:chat-a" in prompt


def test_confirmation_ignores_expired_or_other_chat_preview(tmp_path):
    previews = tmp_path / "pending"
    previews.mkdir()
    (previews / "preview.json").write_text(
        json.dumps(
            {
                "target": "weixin:chat-b",
                "status": "prepared",
                "expiresAt": time.time() + 600,
            }
        ),
        encoding="utf-8",
    )

    assert _luckin_workflow_prompt("确认", "chat-a", previews) is None


def test_confirmation_refreshes_expired_preview_after_new(tmp_path):
    previews = tmp_path / "pending"
    previews.mkdir()
    (previews / "preview.json").write_text(
        json.dumps(
            {
                "target": "weixin:chat-a",
                "status": "prepared",
                "preset": "grape-ice-tea-xl-no-sugar",
                "expiresAt": time.time() - 1,
            }
        ),
        encoding="utf-8",
    )

    prompt = _luckin_workflow_prompt("确认下单", "chat-a", previews)

    assert "expired Luckin preview" in prompt
    assert "prepare_luckin_order_fast.py" in prompt
    assert "confirm again" in prompt
    assert "Do not create an order" in prompt


@pytest.mark.asyncio
async def test_handle_message_injects_luckin_prompt_without_bypassing_model(monkeypatch):
    @dataclass
    class Event:
        text: str
        source: object
        channel_prompt: str | None = None

    upstream = AsyncMock(return_value="handled")
    monkeypatch.setattr(_MODULE.WeixinAdapter, "handle_message", upstream)
    adapter = _MODULE.ExperienceWeixinAdapter(
        PlatformConfig(enabled=True, token="token", extra={"account_id": "account"})
    )
    event = Event("瑞幸。葡萄冰茶超大杯不加糖", SimpleNamespace(chat_id="chat-a"))

    result = await adapter.handle_message(event)

    assert result == "handled"
    forwarded = upstream.await_args.args[0]
    assert forwarded.text == event.text
    assert "model-guided fast path" in forwarded.channel_prompt


@pytest.mark.asyncio
async def test_missing_qr_request_bypasses_model_and_resends_image(tmp_path, monkeypatch):
    qr = tmp_path / "pay.png"
    qr.write_bytes(b"qr")
    adapter = _MODULE.ExperienceWeixinAdapter(
        PlatformConfig(enabled=True, token="token", extra={"account_id": "account"})
    )
    adapter.send_image_file = AsyncMock(return_value=SendResult(success=True, message_id="image"))
    adapter.send = AsyncMock(return_value=SendResult(success=True, message_id="text"))
    monkeypatch.setattr(_MODULE, "_find_luckin_delivery_for_chat", lambda _chat_id: qr)
    event = SimpleNamespace(
        text="二维码呢？怎么没有二维码",
        source=SimpleNamespace(chat_id="chat-a"),
    )

    await adapter.handle_message(event)

    adapter.send_image_file.assert_awaited_once_with("chat-a", str(qr))
    adapter.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_multi_account_adapter_delegates_single_text_image_message(monkeypatch):
    adapter = _MODULE.MultiAccountWeixinAdapter(
        PlatformConfig(
            enabled=True,
            extra={"accounts": [{"account_id": "account", "token": "token"}]},
        )
    )
    child = SimpleNamespace(
        send_text_with_image=AsyncMock(
            return_value=SendResult(success=True, message_id="combined")
        )
    )
    monkeypatch.setattr(adapter, "_select_adapter", lambda _chat_id: child)

    result = await adapter.send_text_with_image(
        "chat-a",
        "订单已创建",
        "/tmp/pay.png",
        metadata={"notify": True},
    )

    assert result.success is True
    child.send_text_with_image.assert_awaited_once_with(
        "chat-a",
        "订单已创建",
        "/tmp/pay.png",
        reply_to=None,
        metadata={"notify": True},
    )
