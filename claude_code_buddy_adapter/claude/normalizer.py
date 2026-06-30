"""statusLine / hooks payload → ClaudeEvent normalizer。

字段对齐 protocol §3.2（statusLine）/ §3.3（hooks）；
容错对齐 protocol §6 + system-design §边界场景：
- unknown hook_event_name：接受并 warning。
- missing optional fields：用 fallback（None），不让 UI 显示 null。
- 缺 session_id：用 transcript_path 或 ``cwd:<cwd>`` 作临时 key 并 warning。
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Optional

from ..logging_setup import get_logger
from .event_model import ClaudeEvent

# protocol §5.6 全部 14 个 hook_event_name（reducer 状态机权威集）
KNOWN_HOOK_EVENTS = frozenset({
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "MessageDisplay",
    "SubagentStart",
    "TaskCreated",
    "Notification",
    "PermissionRequest",
    "Elicitation",
    "ElicitationResult",
    "Stop",
    "StopFailure",
    "SessionEnd",
})

_log = get_logger("event")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _gen_event_id() -> str:
    return uuid.uuid4().hex


def _coerce_payload(payload: Any) -> dict[str, Any]:
    """非 dict 输入容错为空 dict 并 warning，避免抛异常（protocol §6 精神）。"""
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        _log.warning("payload is not a dict (%s), treating as empty", type(payload).__name__)
        return {}
    return payload


def _resolve_session_id(payload: dict[str, Any]) -> Optional[str]:
    """session_id 缺失时用 fallback key：transcript_path 优先，否则 cwd:<cwd>。"""
    sid = payload.get("session_id")
    if sid:
        return str(sid)
    tp = payload.get("transcript_path")
    if tp:
        return str(tp)
    cwd = payload.get("cwd")
    if cwd:
        return f"cwd:{cwd}"
    return None


def normalize_statusline(
    payload: dict[str, Any], received_at_ms: Optional[int] = None
) -> ClaudeEvent:
    """protocol §3.2 statusLine payload → ClaudeEvent。"""
    payload = _coerce_payload(payload)
    sid = payload.get("session_id")
    if not sid:
        cwd = payload.get("cwd")
        sid = f"cwd:{cwd}" if cwd else None
        _log.warning("statusline missing session_id, using fallback key %r", sid)
    return ClaudeEvent(
        event_id=_gen_event_id(),
        source="statusline",
        received_at_ms=received_at_ms if received_at_ms is not None else _now_ms(),
        session_id=sid,
        hook_event_name=None,
        cwd=payload.get("cwd"),
        raw=payload,
    )


def normalize_hook(
    payload: dict[str, Any], received_at_ms: Optional[int] = None
) -> ClaudeEvent:
    """protocol §3.3 hooks payload → ClaudeEvent。"""
    payload = _coerce_payload(payload)
    sid = _resolve_session_id(payload)
    if not payload.get("session_id"):
        _log.warning("hook missing session_id, using fallback key %r", sid)

    hook_event_name = payload.get("hook_event_name")
    if hook_event_name and hook_event_name not in KNOWN_HOOK_EVENTS:
        _log.warning("unknown hook_event_name %r (accepted)", hook_event_name)

    return ClaudeEvent(
        event_id=_gen_event_id(),
        source="hook",
        received_at_ms=received_at_ms if received_at_ms is not None else _now_ms(),
        session_id=sid,
        hook_event_name=hook_event_name,
        cwd=payload.get("cwd"),
        raw=payload,
    )


def normalize(
    payload: dict[str, Any], source: str, received_at_ms: Optional[int] = None
) -> ClaudeEvent:
    """按 ``source`` 分派到对应 normalizer。``source`` ∈ {"statusline", "hook"}。"""
    if source == "statusline":
        return normalize_statusline(payload, received_at_ms)
    if source == "hook":
        return normalize_hook(payload, received_at_ms)
    raise ValueError(f"unknown source: {source!r}")
