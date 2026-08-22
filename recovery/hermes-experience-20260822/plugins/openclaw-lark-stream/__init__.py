"""Hermes wrapper for the GitHub openclaw-lark-stream plugin.

The upstream repository is an OpenClaw JavaScript channel plugin. Hermes loads
Python plugins, so this module keeps Hermes' native CardKit adapter while adding
the multi-account routing needed by this installation.
"""

from __future__ import annotations

import logging
import os
from dataclasses import replace
from typing import Any, Dict, List, Optional

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import BasePlatformAdapter, ProcessingOutcome, SendResult
from plugins.platforms.feishu.adapter import (
    FeishuAdapter,
    _apply_yaml_config,
    _is_connected,
    _standalone_send,
    check_feishu_requirements,
    interactive_setup,
)


logger = logging.getLogger(__name__)


def _compact_number(value: int | float | None) -> str:
    try:
        number = float(value or 0)
    except Exception:
        number = 0.0
    sign = "-" if number < 0 else ""
    number = abs(number)
    if number >= 1_000_000:
        text = f"{number / 1_000_000:.1f}".rstrip("0").rstrip(".")
        return f"{sign}{text}m"
    if number >= 1_000:
        text = f"{number / 1_000:.1f}".rstrip("0").rstrip(".")
        return f"{sign}{text}k"
    return f"{sign}{int(round(number))}"


def _format_elapsed(value: float | int | None) -> str:
    try:
        seconds = max(0.0, float(value or 0))
    except Exception:
        seconds = 0.0
    if seconds < 60:
        return f"{seconds:.1f}s"
    return f"{int(seconds // 60)}m {int(round(seconds % 60))}s"


def _footer_text(value: object) -> str:
    return str(value or "").replace("\n", " ").strip()


def _format_stream_footer(
    *,
    status: str = "已完成",
    elapsed_seconds: float | int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cache_read_tokens: int | None = None,
    cache_write_tokens: int | None = None,
    context_tokens: int | None = None,
    context_length: int | None = None,
    model: Optional[str] = None,
) -> str:
    parts: List[str] = []
    if _footer_text(status):
        parts.append(_footer_text(status))
    if elapsed_seconds is not None:
        parts.append(f"耗时 {_format_elapsed(elapsed_seconds)}")
    if input_tokens is not None or output_tokens is not None:
        parts.append(
            f"输入 {_compact_number(input_tokens)} 输出 {_compact_number(output_tokens)}"
        )
    if cache_read_tokens is not None or cache_write_tokens is not None:
        read = max(0, int(cache_read_tokens or 0))
        write = max(0, int(cache_write_tokens or 0))
        denominator = max(int(input_tokens or 0), read + write)
        percent = int((read / denominator) * 100) if denominator else 0
        parts.append(f"缓存 {_compact_number(read)}/{_compact_number(write)} ({percent}%)")
    if context_tokens is not None and context_length:
        used = max(0, int(context_tokens or 0))
        total = max(0, int(context_length or 0))
        percent = round((used / total) * 100) if total else 0
        parts.append(f"上下文 {_compact_number(used)}/{_compact_number(total)} ({percent}%)")
    model_text = _footer_text((model or "").rsplit("/", 1)[-1])
    if model_text:
        parts.append(model_text)
    return " · ".join(parts)


def _account_configs(config: PlatformConfig) -> List[PlatformConfig]:
    extra = dict(config.extra or {})
    entries = extra.get("accounts")
    if not isinstance(entries, list):
        return []

    shared = {
        key: value
        for key, value in extra.items()
        if key not in {"accounts", "app_id", "app_secret", "app_secret_env"}
    }
    configs: List[PlatformConfig] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        app_id = str(entry.get("app_id") or entry.get("appId") or "").strip()
        app_secret = str(entry.get("app_secret") or entry.get("appSecret") or "").strip()
        secret_env = str(entry.get("app_secret_env") or "").strip()
        if not app_secret and secret_env:
            app_secret = os.getenv(secret_env, "").strip()
        if not app_id or not app_secret:
            continue

        child_extra = dict(shared)
        child_extra.update(
            {
                key: value
                for key, value in entry.items()
                if key not in {"app_secret", "appSecret", "app_secret_env"}
                and value is not None
            }
        )
        child_extra.update(
            {
                "app_id": app_id,
                "app_secret": app_secret,
                "streaming": True,
                "reply_mode": "streaming",
                "cardkit_streaming": True,
                "openclaw_lark_stream_style": True,
            }
        )
        configs.append(replace(config, extra=child_extra))
    return configs


class MultiFeishuAdapter(BasePlatformAdapter):
    """Route each Feishu chat and message through the bot that received it."""

    MAX_MESSAGE_LENGTH = FeishuAdapter.MAX_MESSAGE_LENGTH
    STREAM_SEGMENTS_IN_SINGLE_MESSAGE = getattr(
        FeishuAdapter, "STREAM_SEGMENTS_IN_SINGLE_MESSAGE", False
    )
    STREAM_PROGRESS_IN_SINGLE_CARD = getattr(
        FeishuAdapter, "STREAM_PROGRESS_IN_SINGLE_CARD", False
    )
    REQUIRES_EDIT_FINALIZE = getattr(FeishuAdapter, "REQUIRES_EDIT_FINALIZE", False)
    SUPPORTS_MESSAGE_EDITING = True
    supports_code_blocks = getattr(FeishuAdapter, "supports_code_blocks", True)

    def __init__(self, config: PlatformConfig):
        super().__init__(config, Platform.FEISHU)
        configs = _account_configs(config)
        self._children: List[FeishuAdapter] = [
            FeishuAdapter(child_config) for child_config in configs
        ]
        if not self._children:
            self._children.append(FeishuAdapter(config))
        self._default_child: FeishuAdapter = self._children[0]
        self._chat_child: Dict[str, FeishuAdapter] = {}
        self._message_child: Dict[str, FeishuAdapter] = {}

    def _remember_child(self, child: FeishuAdapter, key: str) -> None:
        if key:
            self._chat_child[str(key)] = child

    def _child_for_chat(self, chat_id: str) -> FeishuAdapter:
        return self._chat_child.get(str(chat_id)) or self._default_child

    def _child_for_message(self, message_id: str, chat_id: str = "") -> FeishuAdapter:
        return self._message_child.get(str(message_id)) or self._child_for_chat(chat_id)

    def _child_for_event(self, event: Any) -> FeishuAdapter:
        message_id = str(getattr(event, "message_id", "") or "")
        if message_id and message_id in self._message_child:
            return self._message_child[message_id]
        source = getattr(event, "source", None)
        return self._child_for_chat(str(getattr(source, "chat_id", "") or ""))

    async def _handle_child_message(self, child: FeishuAdapter, event: Any) -> Any:
        source = getattr(event, "source", None)
        chat_id = str(getattr(source, "chat_id", "") or "")
        user_id = str(getattr(source, "user_id", "") or "")
        message_id = str(getattr(event, "message_id", "") or "")
        self._remember_child(child, chat_id)
        self._remember_child(child, user_id)
        if message_id:
            self._message_child[message_id] = child
        # The child adapter already owns the complete BasePlatformAdapter
        # lifecycle for this inbound event. Calling self.handle_message() here
        # would spawn a second background lifecycle and return immediately,
        # causing the child to replace Typing with DONE while the real agent
        # and CardKit stream are still running.
        handler = getattr(self, "_message_handler", None)
        if handler is None:
            return None
        return await handler(event)

    async def _handle_child_fatal_error(self, _child: FeishuAdapter) -> None:
        if any(child.is_connected for child in self._children):
            return
        self._set_fatal_error(
            "feishu_all_accounts_failed",
            "All configured Feishu apps failed",
            retryable=True,
        )
        await self._notify_fatal_error()

    def set_message_handler(self, handler) -> None:
        super().set_message_handler(handler)
        for child in self._children:
            child.set_message_handler(
                lambda event, _child=child: self._handle_child_message(_child, event)
            )

    def set_fatal_error_handler(self, handler) -> None:
        super().set_fatal_error_handler(handler)
        for child in self._children:
            child.set_fatal_error_handler(self._handle_child_fatal_error)

    def set_busy_session_handler(self, handler) -> None:
        super().set_busy_session_handler(handler)
        for child in self._children:
            child.set_busy_session_handler(handler)

    def set_session_store(self, session_store: Any) -> None:
        super().set_session_store(session_store)
        for child in self._children:
            child.set_session_store(session_store)

    async def connect(self, *, is_reconnect: bool = False) -> bool:
        connected = 0
        for child in self._children:
            child.set_message_handler(
                lambda event, _child=child: self._handle_child_message(_child, event)
            )
            child.set_fatal_error_handler(self._handle_child_fatal_error)
            child.set_busy_session_handler(getattr(self, "_busy_session_handler", None))
            child.set_session_store(getattr(self, "_session_store", None))
            if await child.connect(is_reconnect=is_reconnect):
                connected += 1
        if connected:
            self._mark_connected()
            logger.info("[Feishu] Connected %d/%d account(s)", connected, len(self._children))
            return True
        self._set_fatal_error(
            "feishu_no_accounts_connected",
            "No configured Feishu apps connected",
            retryable=True,
        )
        return False

    async def disconnect(self) -> None:
        for child in self._children:
            await child.disconnect()
        self._mark_disconnected()
        logger.info("[Feishu] Disconnected multi-account adapter")

    async def send(
        self,
        chat_id: str,
        content: str,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SendResult:
        child = self._child_for_chat(chat_id)
        result = await child.send(chat_id, content, reply_to=reply_to, metadata=metadata)
        if result.success:
            self._remember_child(child, chat_id)
            if result.message_id:
                self._message_child[result.message_id] = child
        return result

    async def edit_message(
        self,
        chat_id: str,
        message_id: str,
        content: str,
        *,
        finalize: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SendResult:
        child = self._child_for_message(message_id, chat_id)
        return await child.edit_message(
            chat_id,
            message_id,
            content,
            finalize=finalize,
            metadata=metadata,
        )

    async def delete_message(self, chat_id: str, message_id: str) -> bool:
        child = self._child_for_message(message_id, chat_id)
        return await child.delete_message(chat_id, message_id)

    async def send_typing(self, chat_id: str, metadata=None) -> None:
        await self._child_for_chat(chat_id).send_typing(chat_id, metadata=metadata)

    async def stop_typing(self, chat_id: str) -> None:
        child = self._child_for_chat(chat_id)
        if hasattr(child, "stop_typing"):
            await child.stop_typing(chat_id)

    async def on_processing_start(self, event: Any) -> None:
        child = self._child_for_event(event)
        source = getattr(event, "source", None)
        chat_id = str(getattr(source, "chat_id", "") or "")
        message_id = str(getattr(event, "message_id", "") or "")
        self._remember_child(child, chat_id)
        if message_id:
            self._message_child[message_id] = child
        await child.on_processing_start(event)

    async def on_processing_complete(
        self, event: Any, outcome: ProcessingOutcome
    ) -> None:
        await self._child_for_event(event).on_processing_complete(event, outcome)

    async def finalize_processing_reaction(
        self, message_id: str, outcome: ProcessingOutcome
    ) -> None:
        child = self._child_for_message(message_id)
        await child.finalize_processing_reaction(message_id, outcome)

    async def mark_message_done(self, message_id: str, chat_id: str = "") -> None:
        child = self._child_for_message(message_id, chat_id)
        if hasattr(child, "mark_message_done"):
            await child.mark_message_done(message_id, chat_id=chat_id)

    async def update_openclaw_lark_stream_footer(
        self, message_id: str, footer: str
    ) -> bool:
        child = self._child_for_message(message_id)
        if hasattr(child, "update_openclaw_lark_stream_footer"):
            return await child.update_openclaw_lark_stream_footer(message_id, footer)
        return False

    def format_stream_footer(self, **metadata: Any) -> str:
        return _format_stream_footer(**metadata)

    async def get_chat_info(self, chat_id: str) -> Dict[str, Any]:
        return await self._child_for_chat(chat_id).get_chat_info(chat_id)


def _stream_adapter_factory(config: PlatformConfig):
    if isinstance(config.extra, dict):
        config.extra.setdefault("streaming", True)
        config.extra.setdefault("reply_mode", "streaming")
        config.extra.setdefault("cardkit_streaming", True)
        config.extra.setdefault("openclaw_lark_stream_style", True)
    return MultiFeishuAdapter(config)


def register(ctx) -> None:
    ctx.register_platform(
        name="feishu",
        label="Feishu / Lark Stream",
        adapter_factory=_stream_adapter_factory,
        check_fn=check_feishu_requirements,
        is_connected=_is_connected,
        validate_config=_is_connected,
        required_env=["FEISHU_APP_ID", "FEISHU_APP_SECRET"],
        install_hint="Uses Hermes' Feishu adapter; upstream source: ColinLu50/openclaw-lark-stream",
        setup_fn=interactive_setup,
        apply_yaml_config_fn=_apply_yaml_config,
        allowed_users_env="FEISHU_ALLOWED_USERS",
        allow_all_env="FEISHU_ALLOW_ALL_USERS",
        cron_deliver_env_var="FEISHU_HOME_CHANNEL",
        standalone_sender_fn=_standalone_send,
        max_message_length=8000,
        emoji="🪽",
        allow_update_command=True,
    )
