"""Gateway runtime-metadata footer.

Renders a compact footer showing runtime state (model, context %, cwd) and
appends it to the FINAL message of an agent turn when enabled.  Off by default
to keep replies minimal.

Config (``~/.hermes/config.yaml``)::

    display:
      runtime_footer:
        enabled: true                       # off by default
        fields: [model, context_pct, cwd]   # order shown; drop any to hide

Per-platform overrides live under ``display.platforms.<platform>.runtime_footer``.
Users can toggle the global setting with ``/footer on|off`` from both the CLI
and any gateway platform.

The footer is appended to the final response text in ``gateway/run.py`` right
before returning the response to the adapter send path — so it only lands on
the final message a user sees, not on tool-progress updates or streaming
partials.  When streaming is on and the final text has already been delivered
piecemeal, the footer is sent as a separate trailing message via
``send_trailing_footer()``.
"""

from __future__ import annotations

import os
from typing import Any, Iterable, Optional

_DEFAULT_FIELDS: tuple[str, ...] = ("model", "context_pct", "cwd")
_SEP = " · "


def _home_relative_cwd(cwd: str) -> str:
    """Return *cwd* with ``$HOME`` collapsed to ``~``.  Empty string if unset."""
    if not cwd:
        return ""
    try:
        home = os.path.expanduser("~")
        p = os.path.abspath(cwd)
        if home and (p == home or p.startswith(home + os.sep)):
            return "~" + p[len(home):]
        return p
    except Exception:
        return cwd


def _model_short(model: Optional[str]) -> str:
    """Drop ``vendor/`` prefix for readability (``openai/gpt-5.4`` → ``gpt-5.4``)."""
    if not model:
        return ""
    return model.rsplit("/", 1)[-1]


def _compact_number(value: int | float | None) -> str:
    """Compact a token count using lower-case k/m suffixes."""
    try:
        num = float(value or 0)
    except Exception:
        num = 0.0
    sign = "-" if num < 0 else ""
    num = abs(num)
    if num >= 1_000_000:
        scaled = num / 1_000_000
        text = f"{scaled:.1f}".rstrip("0").rstrip(".")
        return f"{sign}{text}m"
    if num >= 1_000:
        scaled = num / 1_000
        text = f"{scaled:.1f}".rstrip("0").rstrip(".")
        return f"{sign}{text}k"
    return f"{sign}{int(round(num))}"


def _format_elapsed(seconds: float | int | None) -> str:
    try:
        sec = max(0.0, float(seconds or 0.0))
    except Exception:
        sec = 0.0
    if sec < 60:
        return f"{sec:.1f}s"
    mins = int(sec // 60)
    rem = int(round(sec % 60))
    return f"{mins}m {rem}s"


def _safe_footer_text(text: object) -> str:
    """Keep footer metadata to one markdown-safe-ish line."""
    return str(text or "").replace("\n", " ").strip()


def resolve_footer_config(
    user_config: dict[str, Any] | None,
    platform_key: str | None = None,
) -> dict[str, Any]:
    """Resolve effective runtime-footer config for *platform_key*.

    Merge order (later wins):
        1. Built-in defaults (enabled=False)
        2. ``display.runtime_footer``
        3. ``display.platforms.<platform_key>.runtime_footer``
    """
    resolved = {"enabled": False, "fields": list(_DEFAULT_FIELDS)}
    cfg = (user_config or {}).get("display") or {}

    global_cfg = cfg.get("runtime_footer")
    if isinstance(global_cfg, dict):
        if "enabled" in global_cfg:
            resolved["enabled"] = bool(global_cfg.get("enabled"))
        if isinstance(global_cfg.get("fields"), list) and global_cfg["fields"]:
            resolved["fields"] = [str(f) for f in global_cfg["fields"]]

    if platform_key:
        platforms = cfg.get("platforms") or {}
        plat_cfg = platforms.get(platform_key)
        if isinstance(plat_cfg, dict):
            plat_footer = plat_cfg.get("runtime_footer")
            if isinstance(plat_footer, dict):
                if "enabled" in plat_footer:
                    resolved["enabled"] = bool(plat_footer.get("enabled"))
                if isinstance(plat_footer.get("fields"), list) and plat_footer["fields"]:
                    resolved["fields"] = [str(f) for f in plat_footer["fields"]]

    return resolved


def format_runtime_footer(
    *,
    model: Optional[str],
    context_tokens: int,
    context_length: Optional[int],
    cwd: Optional[str] = None,
    fields: Iterable[str] = _DEFAULT_FIELDS,
) -> str:
    """Render the footer line, or return "" if no fields have data.

    Fields are skipped silently when their underlying data is missing — a
    partially-populated footer is better than a line with ``?%`` or empty slots.
    """
    parts: list[str] = []
    for field in fields:
        if field == "model":
            m = _model_short(model)
            if m:
                parts.append(m)
        elif field == "context_pct":
            if context_length and context_length > 0 and context_tokens >= 0:
                pct = max(0, min(100, round((context_tokens / context_length) * 100)))
                parts.append(f"{pct}%")
        elif field == "cwd":
            rel = _home_relative_cwd(cwd or os.environ.get("TERMINAL_CWD", ""))
            if rel:
                parts.append(rel)
        # Unknown field names are silently ignored.

    if not parts:
        return ""
    return _SEP.join(parts)


def format_feishu_stream_footer(
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
    """Render the Feishu CardKit streaming footer requested by the user.

    Example:
    ``已完成 · 耗时 8.3s · 输入 19k 输出 145 · 缓存 18k/1k (94%) · 上下文 19k/200k (10%) · claude-3-7-sonnet``
    """
    parts: list[str] = []
    status_text = _safe_footer_text(status)
    if status_text:
        parts.append(status_text)
    if elapsed_seconds is not None:
        parts.append(f"耗时 {_format_elapsed(elapsed_seconds)}")
    if input_tokens is not None or output_tokens is not None:
        parts.append(
            f"输入 {_compact_number(input_tokens or 0)} 输出 {_compact_number(output_tokens or 0)}"
        )
    if cache_read_tokens is not None or cache_write_tokens is not None:
        read = max(0, int(cache_read_tokens or 0))
        write = max(0, int(cache_write_tokens or 0))
        denom = max(int(input_tokens or 0), read + write)
        pct = int((read / denom) * 100) if denom > 0 else 0
        parts.append(f"缓存 {_compact_number(read)}/{_compact_number(write)} ({pct}%)")
    if context_tokens is not None and context_length:
        used = max(0, int(context_tokens or 0))
        total = max(0, int(context_length or 0))
        pct = round((used / total) * 100) if total > 0 else 0
        parts.append(f"上下文 {_compact_number(used)}/{_compact_number(total)} ({pct}%)")
    model_text = _safe_footer_text(_model_short(model))
    if model_text:
        parts.append(model_text)
    return _SEP.join(parts)


def build_footer_line(
    *,
    user_config: dict[str, Any] | None,
    platform_key: str | None,
    model: Optional[str],
    context_tokens: int,
    context_length: Optional[int],
    cwd: Optional[str] = None,
) -> str:
    """Top-level entry point used by gateway/run.py.

    Returns the footer text (empty string when disabled or no data).  Callers
    append this to the final response themselves, preserving a single blank
    line of separation.
    """
    cfg = resolve_footer_config(user_config, platform_key)
    if not cfg.get("enabled"):
        return ""
    return format_runtime_footer(
        model=model,
        context_tokens=context_tokens,
        context_length=context_length,
        cwd=cwd,
        fields=cfg.get("fields") or _DEFAULT_FIELDS,
    )
