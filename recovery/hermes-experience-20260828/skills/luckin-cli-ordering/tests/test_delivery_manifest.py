import importlib.util
import json
import subprocess
from pathlib import Path


def _load_script(name: str):
    path = Path(__file__).parents[1] / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_create_script_writes_chat_scoped_delivery_manifest(tmp_path):
    module = _load_script("create_luckin_order_fast.py")
    pay_qr = tmp_path / "pay.png"
    pay_qr.write_bytes(b"qr")

    path = module.write_delivery_manifest(
        "order-1",
        "weixin:chat-a",
        pay_qr,
        root=tmp_path / "deliveries",
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["orderId"] == "order-1"
    assert payload["target"] == "weixin:chat-a"
    assert payload["payQrPath"] == str(pay_qr)
    assert payload["pickupReady"] is False
    assert payload["paymentExpired"] is False
    assert payload["orderStatus"] == "待付款"


def test_watcher_marks_manifest_ready_without_losing_payment_path(tmp_path):
    module = _load_script("watch_luckin_order.py")
    root = tmp_path / "deliveries"
    root.mkdir()
    manifest = root / "order-1.json"
    manifest.write_text(
        json.dumps({"orderId": "order-1", "target": "weixin:chat-a", "payQrPath": "/pay.png"}),
        encoding="utf-8",
    )
    pickup = tmp_path / "pickup.png"
    pickup.write_bytes(b"qr")

    module.mark_delivery_ready("order-1", pickup, status_name="等待取餐", root=root)

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["payQrPath"] == "/pay.png"
    assert payload["pickupQrPath"] == str(pickup)
    assert payload["pickupReady"] is True
    assert payload["orderStatus"] == "等待取餐"


def test_watcher_updates_manifest_on_nonterminal_status(tmp_path):
    module = _load_script("watch_luckin_order.py")
    root = tmp_path / "deliveries"
    root.mkdir()
    manifest = root / "order-1.json"
    manifest.write_text(
        json.dumps({"orderId": "order-1", "orderStatus": "待付款"}),
        encoding="utf-8",
    )

    module.mark_delivery_status("order-1", "精心制作中", root=root)

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["orderStatus"] == "精心制作中"


def test_watcher_closes_manifest_when_order_expires(tmp_path):
    module = _load_script("watch_luckin_order.py")
    root = tmp_path / "deliveries"
    root.mkdir()
    manifest = root / "order-1.json"
    manifest.write_text(
        json.dumps(
            {
                "orderId": "order-1",
                "target": "weixin:chat-a",
                "payQrPath": "/pay.png",
                "paymentExpired": False,
            }
        ),
        encoding="utf-8",
    )

    module.mark_delivery_closed("order-1", "已取消", payment_expired=True, root=root)

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["paymentExpired"] is True
    assert payload["orderStatus"] == "已取消"


def test_watcher_notifies_each_meaningful_order_transition_once():
    module = _load_script("watch_luckin_order.py")

    assert module.should_notify_status("待付款") is False
    assert module.should_notify_status("下单成功") is True
    assert module.should_notify_status("精心制作中") is True
    assert module.should_notify_status("等待取餐") is True
    assert module.should_notify_status("订单异常") is True


def test_lifecycle_messages_do_not_repeat_store_or_order_id():
    module = _load_script("watch_luckin_order.py")

    messages = [
        module.progress_message("下单成功"),
        module.progress_message("精心制作中"),
        module.ready_message("972", "/tmp/pickup.png"),
        module.failure_message("已取消"),
    ]

    assert messages[0] == "下单成功"
    assert messages[1] == "制作中"
    assert messages[2] == "可以取餐了\n取餐码：972\nMEDIA:/tmp/pickup.png"
    assert messages[3] == "瑞幸订单状态：已取消"
    assert all("门店" not in message for message in messages)
    assert all("订单号" not in message for message in messages)


def test_weixin_send_requires_exact_chat_and_context_token(tmp_path, monkeypatch):
    module = _load_script("watch_luckin_order.py")
    monkeypatch.setattr(module, "TARGET", "weixin:chat-a")
    monkeypatch.setattr(module, "LOG_FILE", tmp_path / "watch.log")

    def completed(payload):
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(payload), stderr=""
        )

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: completed(
            {"success": True, "chat_id": "chat-a", "context_token_used": True}
        ),
    )
    assert module.send("下单成功") is True

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: completed(
            {"success": True, "chat_id": "chat-a", "context_token_used": False}
        ),
    )
    assert module.send("制作中") is False

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: completed(
            {"success": True, "chat_id": "chat-b", "context_token_used": True}
        ),
    )
    assert module.send("制作中") is False

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="sent", stderr=""
        ),
    )
    assert module.send("制作中") is False


def test_watcher_suppresses_unpaid_expiry_but_not_post_payment_cancellation():
    module = _load_script("watch_luckin_order.py")

    assert module.is_unpaid_expiry("10:待付款", 100, "已取消") is True
    assert module.is_unpaid_expiry("10:待付款", "100", "订单已取消") is True
    assert module.is_unpaid_expiry("20:下单成功", 100, "已取消") is False
    assert module.is_unpaid_expiry("30:精心制作中", 100, "已取消") is False
    assert module.is_unpaid_expiry("10:待付款", 20, "下单成功") is False


def test_watcher_exits_silently_when_unpaid_order_expires(tmp_path, monkeypatch):
    module = _load_script("watch_luckin_order.py")
    state_file = tmp_path / "last_status"
    responses = iter(
        [
            {"orderStatus": 10, "orderStatusName": "待付款"},
            {
                "orderStatus": 100,
                "orderStatusName": "已取消",
                "shopInfo": {"deptName": "测试门店"},
            },
        ]
    )
    sent = []

    monkeypatch.setattr(module, "ORDER_ID", "order-expired")
    monkeypatch.setattr(module, "TARGET", "weixin:chat-a")
    monkeypatch.setattr(module, "STATE_FILE", state_file)
    monkeypatch.setattr(module, "LOG_FILE", tmp_path / "watch.log")
    monkeypatch.setattr(module, "READY_SENT_FILE", tmp_path / "ready.json")
    monkeypatch.setattr(module, "POLL_INTERVAL", 0)
    monkeypatch.setattr(module, "query", lambda: next(responses))
    monkeypatch.setattr(module, "send", lambda message: sent.append(message) or True)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    module.main()

    assert sent == []
    assert state_file.read_text(encoding="utf-8") == "100:已取消"
    assert "standalone cancellation notification suppressed" in (
        tmp_path / "watch.log"
    ).read_text(encoding="utf-8")


def test_watcher_emits_each_lifecycle_transition_once(tmp_path, monkeypatch):
    module = _load_script("watch_luckin_order.py")
    state_file = tmp_path / "last_status"
    ready_file = tmp_path / "ready.json"
    qr_path = tmp_path / "pickup.png"
    qr_path.write_bytes(b"qr")
    responses = iter(
        [
            {"orderStatus": 10, "orderStatusName": "待付款"},
            {
                "orderStatus": 20,
                "orderStatusName": "下单成功",
                "shopInfo": {"deptName": "测试门店"},
            },
            {
                "orderStatus": 30,
                "orderStatusName": "精心制作中",
                "shopInfo": {"deptName": "测试门店"},
            },
            {
                "orderStatus": 60,
                "orderStatusName": "等待取餐",
                "shopInfo": {"deptName": "测试门店"},
                "takeMealCodeInfo": {"code": "972", "takeOrderId": "take-1"},
            },
        ]
    )
    sent = []

    monkeypatch.setattr(module, "ORDER_ID", "order-1")
    monkeypatch.setattr(module, "TARGET", "weixin:chat-a")
    monkeypatch.setattr(module, "STATE_FILE", state_file)
    monkeypatch.setattr(module, "LOG_FILE", tmp_path / "watch.log")
    monkeypatch.setattr(module, "READY_SENT_FILE", ready_file)
    monkeypatch.setattr(module, "POLL_INTERVAL", 0)
    monkeypatch.setattr(module, "query", lambda: next(responses))
    monkeypatch.setattr(module, "send", lambda message: sent.append(message) or True)
    monkeypatch.setattr(module, "generate_pickup_qr", lambda *_args: str(qr_path))
    monkeypatch.setattr(module, "mark_delivery_ready", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    module.main()

    assert len(sent) == 3
    assert sent[0] == "下单成功"
    assert sent[1] == "制作中"
    assert sent[2] == f"可以取餐了\n取餐码：972\nMEDIA:{qr_path}"
    assert all("门店" not in message for message in sent)
    assert all("订单号" not in message for message in sent)
    assert ready_file.is_file()
