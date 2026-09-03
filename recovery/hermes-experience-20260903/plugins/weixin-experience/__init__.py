"""Weixin behavior that belongs in a platform plugin, not a Hermes core patch."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Optional

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import BasePlatformAdapter, SendResult
from gateway.platforms.weixin import (
    ContextTokenStore,
    WeixinAdapter,
    _pack_markdown_blocks_for_weixin,
    check_weixin_requirements,
    send_weixin_direct as _core_send_weixin_direct,
)
from hermes_cli.config import get_hermes_home


logger = logging.getLogger(__name__)

_MODEL_SWITCH_ACTION_RE = re.compile(
    r"(切换|切換|切到|换成|換成|换到|換到|改成|设为|設為|保持|switch)",
    re.IGNORECASE,
)
_GPT53_RE = re.compile(r"gpt\s*-?\s*5\s*[.\-]?\s*3|gpt5\s*[.\-]?\s*3", re.IGNORECASE)
_GPT55_RE = re.compile(r"gpt\s*-?\s*5\s*[.\-]?\s*5|gpt5\s*[.\-]?\s*5", re.IGNORECASE)
_CURRENT_SESSION_MARKERS = (
    "这个会话", "這個會話", "本会话", "本會話", "当前会话", "當前會話",
    "自己的模型", "它自己的模型", "自己模型",
)
_GLOBAL_MODEL_MARKERS = (
    "其他会话", "其它会话", "其他會話", "其它會話", "所有会话", "全部会话",
    "默认", "默認", "全局", "global",
)
_QR_MARKER_RE = re.compile(r"二维码|付款码|支付码|取餐码", re.IGNORECASE)
_QR_RECOVERY_MARKER_RE = re.compile(
    r"呢|没|没有|未|不见|失败|出错|补发|重发|再发|发出来|看不到",
    re.IGNORECASE,
)
_LUCKIN_MARKER_RE = re.compile(r"瑞幸|luckin", re.IGNORECASE)
_LUCKIN_CONFIRM_RE = re.compile(r"^\s*(确认|确认下单|确认购买)\s*[。.!！]?$", re.IGNORECASE)
_TRANSIENT_MEDIA_ERRORS = (
    "cannot connect",
    "connection error",
    "connection reset",
    "dns",
    "name resolution",
    "temporary failure",
    "timed out",
    "timeout",
    "novac2c.cdn.weixin.qq.com",
)


def _is_luckin_qr_recovery_request(text: str) -> bool:
    raw = (text or "").strip()
    if not raw or len(raw) > 80:
        return False
    return bool(_QR_MARKER_RE.search(raw) and _QR_RECOVERY_MARKER_RE.search(raw))


def _find_luckin_delivery_for_chat(
    chat_id: str,
    deliveries_dir: Optional[Path] = None,
    *,
    max_age_seconds: float = 3600.0,
) -> Optional[Path]:
    root = deliveries_dir or (Path.home() / ".luckin" / "deliveries")
    if not root.is_dir():
        return None
    now = time.time()
    candidates = sorted(root.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    for manifest in candidates:
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            if payload.get("target") != f"weixin:{chat_id}":
                continue
            if payload.get("paymentExpired") or "取消" in str(payload.get("orderStatus") or ""):
                continue
            updated_at = float(payload.get("updatedAt") or manifest.stat().st_mtime)
            if now - updated_at > max_age_seconds:
                continue
            path_value = (
                payload.get("pickupQrPath")
                if payload.get("pickupReady")
                else payload.get("payQrPath")
            )
            path = Path(str(path_value or "")).expanduser()
            if path.is_file() and path.stat().st_size > 0:
                return path
        except (OSError, TypeError, ValueError):
            continue
    return None


def _find_pending_luckin_preview_for_chat(
    chat_id: str,
    previews_dir: Optional[Path] = None,
    *,
    now: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    root = previews_dir or (Path.home() / ".luckin" / "pending_previews")
    if not root.is_dir():
        return None
    current = time.time() if now is None else now
    for path in sorted(root.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("target") != f"weixin:{chat_id}":
                continue
            if payload.get("status") != "prepared":
                continue
            if current > float(payload.get("expiresAt") or 0):
                continue
            return payload
        except (OSError, TypeError, ValueError):
            continue
    return None


def _find_latest_luckin_preview_for_chat(
    chat_id: str,
    previews_dir: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    root = previews_dir or (Path.home() / ".luckin" / "pending_previews")
    if not root.is_dir():
        return None
    for path in sorted(root.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("target") == f"weixin:{chat_id}":
                return payload
        except (OSError, TypeError, ValueError):
            continue
    return None


def _luckin_workflow_prompt(
    text: str,
    chat_id: str,
    previews_dir: Optional[Path] = None,
) -> Optional[str]:
    raw = (text or "").strip()
    target = f"weixin:{chat_id}"
    if _LUCKIN_CONFIRM_RE.fullmatch(raw):
        pending = _find_pending_luckin_preview_for_chat(chat_id, previews_dir)
        if pending is not None:
            return (
                "This Weixin chat has an unexpired, verified Luckin preview and the "
                "current user message confirms it. Load only luckin-cli-ordering, then "
                "run confirm_luckin_order_fast.py once with target "
                f"{target!r}. Relay only its replyText. Do not browse, look up the menu "
                "again, or create the order by any other path."
            )
        latest = _find_latest_luckin_preview_for_chat(chat_id, previews_dir)
        if (
            latest is not None
            and latest.get("status") == "prepared"
            and latest.get("preset") == "grape-ice-tea-xl-no-sugar"
        ):
            return (
                "This Weixin chat has an expired Luckin preview. Do not create an "
                "order from it. Load only luckin-cli-ordering, then run "
                "prepare_luckin_order_fast.py once with preset "
                "grape-ice-tea-xl-no-sugar and target "
                f"{target!r}. Relay only its fresh replyText and require the user to "
                "confirm again. Do not browse or use the expired price/coupon."
            )
    if _LUCKIN_MARKER_RE.search(raw):
        return (
            "This is a Luckin request. Load luckin-cli-ordering first and follow its "
            "model-guided fast path. Use Luckin CLI/MCP as the live source; do not use "
            "browser, web search, image analysis, unrelated skills, or manual skill "
            f"usage logging. The originating target is {target!r}."
        )
    return None


def _natural_model_switch_command(text: str) -> Optional[str]:
    raw = (text or "").strip()
    if not raw or raw.startswith("/") or len(raw) > 160:
        return None
    lowered = raw.lower()
    if not _MODEL_SWITCH_ACTION_RE.search(lowered):
        return None
    current = any(marker in raw for marker in _CURRENT_SESSION_MARKERS)
    global_request = any(marker in raw for marker in _GLOBAL_MODEL_MARKERS)
    if global_request and not current:
        return None
    if _GPT53_RE.search(lowered):
        target = "gpt-5.3-codex-spark"
    elif _GPT55_RE.search(lowered):
        target = "gpt-5.5"
    else:
        return None
    return f"/model {target} --provider openai-codex --session"


def _account_entries(config: PlatformConfig) -> List[Dict[str, Any]]:
    raw = (config.extra or {}).get("accounts") or []
    if isinstance(raw, dict):
        raw = list(raw.values())
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, dict)]


def _account_configs(config: PlatformConfig) -> List[PlatformConfig]:
    accounts = _account_entries(config)
    if not accounts:
        return [config]
    shared = dict(config.extra or {})
    shared.pop("accounts", None)
    return [
        replace(
            config,
            token=str(account.get("token") or config.token or "").strip(),
            extra={**shared, **account},
        )
        for account in accounts
    ]


class ExperienceWeixinAdapter(WeixinAdapter):
    """Native Weixin adapter with installation-specific presentation behavior."""

    def __init__(self, config: PlatformConfig):
        super().__init__(config)
        self._pending_media: Dict[str, Path] = {}
        self._media_retry_tasks: Dict[str, asyncio.Task] = {}

    def _split_text(self, content: str) -> List[str]:
        if self._split_multiline_messages:
            return super()._split_text(content)
        if len(content) <= self.MAX_MESSAGE_LENGTH:
            return [content]
        return _pack_markdown_blocks_for_weixin(content, self.MAX_MESSAGE_LENGTH) or [content]

    async def handle_message(self, event):
        chat_id = event.source.chat_id
        if _is_luckin_qr_recovery_request(event.text or ""):
            path = self._pending_media.get(chat_id) or _find_luckin_delivery_for_chat(chat_id)
            if path is not None:
                task = self._media_retry_tasks.pop(chat_id, None)
                if task is not None and not task.done():
                    task.cancel()
                result = await self.send_image_file(chat_id, str(path))
                if not result.success:
                    await self.send(chat_id, "二维码正在自动补发，请稍等片刻。")
                return
        workflow_prompt = _luckin_workflow_prompt(event.text or "", chat_id)
        if workflow_prompt:
            current_prompt = str(getattr(event, "channel_prompt", "") or "").strip()
            event = replace(
                event,
                channel_prompt=(f"{current_prompt}\n\n{workflow_prompt}".strip()),
            )
        command = _natural_model_switch_command(event.text or "")
        if command:
            logger.info(
                "Weixin natural model switch: chat=%s command=%s",
                event.source.chat_id,
                command,
            )
            event = replace(event, text=command)
        return await super().handle_message(event)

    @staticmethod
    def _is_transient_media_error(error: Optional[str]) -> bool:
        lowered = (error or "").lower()
        return any(marker in lowered for marker in _TRANSIENT_MEDIA_ERRORS)

    async def send_document(self, chat_id: str, file_path: str, **kwargs) -> SendResult:
        result = await super().send_document(chat_id, file_path, **kwargs)
        if result.success:
            if self._pending_media.get(chat_id) == Path(file_path):
                self._pending_media.pop(chat_id, None)
            return result
        if not self._is_transient_media_error(result.error):
            return result
        self._pending_media[chat_id] = Path(file_path)
        current = self._media_retry_tasks.get(chat_id)
        if current is None or current.done():
            self._media_retry_tasks[chat_id] = asyncio.create_task(
                self._retry_document(chat_id, file_path, dict(kwargs))
            )
        return result

    async def _retry_document(self, chat_id: str, file_path: str, kwargs: Dict[str, Any]) -> None:
        try:
            for delay in (3.0, 8.0, 20.0, 45.0):
                await asyncio.sleep(delay)
                result = await super().send_document(chat_id, file_path, **kwargs)
                if result.success:
                    self._pending_media.pop(chat_id, None)
                    logger.info("[%s] recovered pending media for %s", self.name, chat_id[:8])
                    return
                if not self._is_transient_media_error(result.error):
                    return
        except asyncio.CancelledError:
            return
        finally:
            current = asyncio.current_task()
            if self._media_retry_tasks.get(chat_id) is current:
                self._media_retry_tasks.pop(chat_id, None)

    async def disconnect(self) -> None:
        for task in self._media_retry_tasks.values():
            if not task.done():
                task.cancel()
        self._media_retry_tasks.clear()
        await super().disconnect()

class MultiAccountWeixinAdapter(BasePlatformAdapter):
    """Expose all configured iLink identities as one logical Weixin platform."""

    supports_code_blocks = ExperienceWeixinAdapter.supports_code_blocks
    supports_async_delivery = ExperienceWeixinAdapter.supports_async_delivery
    splits_long_messages = ExperienceWeixinAdapter.splits_long_messages
    SUPPORTS_MESSAGE_EDITING = ExperienceWeixinAdapter.SUPPORTS_MESSAGE_EDITING
    MAX_MESSAGE_LENGTH = ExperienceWeixinAdapter.MAX_MESSAGE_LENGTH

    def __init__(self, config: PlatformConfig):
        super().__init__(config, Platform.WEIXIN)
        self._adapters = [ExperienceWeixinAdapter(item) for item in _account_configs(config)]

    @property
    def enforces_own_access_policy(self) -> bool:
        return True

    def _propagate_runtime_hooks(self, adapter: ExperienceWeixinAdapter) -> None:
        if self._message_handler is not None:
            adapter.set_message_handler(self._message_handler)
        adapter.set_session_store(getattr(self, "_session_store", None))
        adapter.set_busy_session_handler(getattr(self, "_busy_session_handler", None))
        adapter.set_topic_recovery_fn(getattr(self, "_topic_recovery_fn", None))
        adapter.set_authorization_check(getattr(self, "_authorization_check", None))

    def set_message_handler(self, handler) -> None:
        super().set_message_handler(handler)
        for adapter in self._adapters:
            adapter.set_message_handler(handler)

    def set_session_store(self, session_store: Any) -> None:
        super().set_session_store(session_store)
        for adapter in self._adapters:
            adapter.set_session_store(session_store)

    def set_busy_session_handler(self, handler) -> None:
        super().set_busy_session_handler(handler)
        for adapter in self._adapters:
            adapter.set_busy_session_handler(handler)

    def set_topic_recovery_fn(self, fn) -> None:
        super().set_topic_recovery_fn(fn)
        for adapter in self._adapters:
            adapter.set_topic_recovery_fn(fn)

    def set_authorization_check(self, callback) -> None:
        super().set_authorization_check(callback)
        for adapter in self._adapters:
            adapter.set_authorization_check(callback)

    async def connect(self, *, is_reconnect: bool = False) -> bool:
        connected = 0
        for adapter in self._adapters:
            self._propagate_runtime_hooks(adapter)
            try:
                if await adapter.connect(is_reconnect=is_reconnect):
                    connected += 1
                else:
                    await adapter.disconnect()
            except Exception as exc:
                logger.error(
                    "[%s] child account %s failed to connect: %s",
                    self.name,
                    getattr(adapter, "_account_id", ""),
                    exc,
                )
                try:
                    await adapter.disconnect()
                except Exception:
                    logger.debug("[%s] child disconnect failed", self.name, exc_info=True)
        if not connected:
            self._set_fatal_error(
                "weixin_all_accounts_failed",
                "Weixin startup failed: all configured accounts failed to connect",
                retryable=True,
            )
            await self._notify_fatal_error()
            return False
        self._mark_connected()
        logger.info("[%s] Connected %d/%d account(s)", self.name, connected, len(self._adapters))
        return True

    async def disconnect(self) -> None:
        for adapter in self._adapters:
            try:
                await adapter.disconnect()
            except Exception:
                logger.debug("[%s] child disconnect failed", self.name, exc_info=True)
        self._mark_disconnected()

    def _connected_adapters(self) -> List[ExperienceWeixinAdapter]:
        return [adapter for adapter in self._adapters if adapter.is_connected]

    def _select_adapter(self, chat_id: str) -> Optional[ExperienceWeixinAdapter]:
        candidates = self._connected_adapters() or self._adapters
        for adapter in candidates:
            if adapter._token_store.get(adapter._account_id, chat_id):
                return adapter
        return candidates[0] if candidates else None

    def format_message(self, content: Optional[str]) -> str:
        if self._adapters:
            return self._adapters[0].format_message(content)
        return "" if content is None else str(content)

    async def get_chat_info(self, chat_id: str) -> Dict[str, Any]:
        adapter = self._select_adapter(chat_id)
        if adapter is not None:
            return await adapter.get_chat_info(chat_id)
        return {
            "name": chat_id,
            "type": "group" if chat_id.endswith("@chatroom") else "dm",
            "chat_id": chat_id,
        }

    async def send(self, chat_id: str, content: str, reply_to=None, metadata=None) -> SendResult:
        adapter = self._select_adapter(chat_id)
        if adapter is None:
            return SendResult(success=False, error="No Weixin accounts configured")
        return await adapter.send(chat_id, content, reply_to=reply_to, metadata=metadata)

    async def send_typing(self, chat_id: str, metadata=None) -> None:
        adapter = self._select_adapter(chat_id)
        if adapter is not None:
            await adapter.send_typing(chat_id, metadata=metadata)

    async def stop_typing(self, chat_id: str) -> None:
        adapter = self._select_adapter(chat_id)
        if adapter is not None:
            await adapter.stop_typing(chat_id)

    async def send_image(self, chat_id: str, image_url: str, caption: str, reply_to=None, metadata=None) -> SendResult:
        adapter = self._select_adapter(chat_id)
        if adapter is None:
            return SendResult(success=False, error="No Weixin accounts configured")
        return await adapter.send_image(chat_id, image_url, caption, reply_to=reply_to, metadata=metadata)

    async def send_image_file(self, chat_id: str, image_path: str, caption=None, reply_to=None, metadata=None, **kwargs) -> SendResult:
        adapter = self._select_adapter(chat_id)
        if adapter is None:
            return SendResult(success=False, error="No Weixin accounts configured")
        return await adapter.send_image_file(chat_id, image_path, caption=caption, reply_to=reply_to, metadata=metadata, **kwargs)

    async def send_text_with_image(self, chat_id: str, content: str, image_path: str, reply_to=None, metadata=None):
        adapter = self._select_adapter(chat_id)
        if adapter is None:
            return SendResult(success=False, error="No Weixin accounts configured")
        return await adapter.send_text_with_image(
            chat_id,
            content,
            image_path,
            reply_to=reply_to,
            metadata=metadata,
        )

    async def send_document(self, chat_id: str, file_path: str, caption=None, file_name=None, reply_to=None, metadata=None, **kwargs) -> SendResult:
        adapter = self._select_adapter(chat_id)
        if adapter is None:
            return SendResult(success=False, error="No Weixin accounts configured")
        return await adapter.send_document(chat_id, file_path, caption=caption, file_name=file_name, reply_to=reply_to, metadata=metadata, **kwargs)

    async def send_video(self, chat_id: str, video_path: str, caption=None, reply_to=None, metadata=None) -> SendResult:
        adapter = self._select_adapter(chat_id)
        if adapter is None:
            return SendResult(success=False, error="No Weixin accounts configured")
        return await adapter.send_video(chat_id, video_path, caption=caption, reply_to=reply_to, metadata=metadata)

    async def send_voice(self, chat_id: str, audio_path: str, caption=None, reply_to=None, metadata=None) -> SendResult:
        adapter = self._select_adapter(chat_id)
        if adapter is None:
            return SendResult(success=False, error="No Weixin accounts configured")
        return await adapter.send_voice(chat_id, audio_path, caption=caption, reply_to=reply_to, metadata=metadata)


def _select_account(config: PlatformConfig, chat_id: str) -> PlatformConfig:
    candidates = _account_configs(config)
    store = ContextTokenStore(str(get_hermes_home()))
    for candidate in candidates:
        account_id = str((candidate.extra or {}).get("account_id") or "").strip()
        if not account_id:
            continue
        store.restore(account_id)
        if store.get(account_id, chat_id):
            return candidate
    return candidates[0]


async def _standalone_send(
    pconfig: PlatformConfig,
    chat_id: str,
    message: str,
    *,
    thread_id=None,
    media_files=None,
    force_document=False,
    **_kwargs,
):
    del thread_id, force_document
    selected = _select_account(pconfig, chat_id)
    return await _core_send_weixin_direct(
        extra=selected.extra or {},
        token=selected.token,
        chat_id=chat_id,
        message=message,
        media_files=media_files,
    )


def _adapter_factory(config: PlatformConfig):
    if len(_account_entries(config)) > 1:
        return MultiAccountWeixinAdapter(config)
    return ExperienceWeixinAdapter(config)


def register(ctx) -> None:
    ctx.register_platform(
        name="weixin",
        label="Weixin Experience",
        adapter_factory=_adapter_factory,
        check_fn=check_weixin_requirements,
        validate_config=lambda config: bool(_account_configs(config)),
        allowed_users_env="WEIXIN_ALLOWED_USERS",
        allow_all_env="WEIXIN_ALLOW_ALL_USERS",
        cron_deliver_env_var="WEIXIN_HOME_CHANNEL",
        standalone_sender_fn=_standalone_send,
        max_message_length=ExperienceWeixinAdapter.MAX_MESSAGE_LENGTH,
        emoji="💬",
        allow_update_command=True,
    )
