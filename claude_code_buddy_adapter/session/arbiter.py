"""focus arbiter + global state 聚合 + counts。

- BR-001 优先级：error > attention > working > done_recent > idle（plan 归入 attention）。
- BR-005 focus：多 attention → 最近进入 attention 的 session。
- BR-006 focus：多 working 无 attention → 最近更新的 working session。
- §5.2 global device state：device_disconnected / adapter_connected / idle / working / attention / error。
"""

from __future__ import annotations

from typing import Optional

from ..claude.reducer import Session, SessionState

# 状态优先级（越大越高）；plan 归入 attention，ended 不参与
_PRIORITY: dict[SessionState, int] = {
    SessionState.error: 5,
    SessionState.attention: 4,
    SessionState.plan: 4,
    SessionState.working: 3,
    SessionState.done_recent: 2,
    SessionState.idle: 1,
    SessionState.unknown: 0,
    SessionState.ended: -1,
}

GLOBAL_STATES = (
    "device_disconnected",
    "adapter_connected",
    "idle",
    "working",
    "attention",
    "error",
)


def priority_of(state: SessionState) -> int:
    return _PRIORITY.get(state, 0)


def _is_active(s: Session) -> bool:
    return s.state != SessionState.ended


def select_focus(sessions: list[Session]) -> Optional[Session]:
    """从 sessions 选 focus（BR-005/BR-006），ended 不参与。返回输入列表中的对象。"""
    active = [s for s in sessions if _is_active(s)]
    if not active:
        return None
    max_pri = max(priority_of(s.state) for s in active)
    top = [s for s in active if priority_of(s.state) == max_pri]
    if max_pri == priority_of(SessionState.attention):
        # attention/plan 组：最近进入 attention（attention_since_ms）
        return max(top, key=lambda s: s.attention_since_ms or s.updated_at_ms or 0)
    return max(top, key=lambda s: s.updated_at_ms or 0)


def compute_global_state(sessions: list[Session], device_connected: bool) -> str:
    """§5.2 global device state。done_recent 不在值集 → 映射 idle。"""
    if not device_connected:
        return "device_disconnected"
    active = [s for s in sessions if _is_active(s)]
    if not active:
        return "adapter_connected"
    max_pri = max(priority_of(s.state) for s in active)
    if max_pri == priority_of(SessionState.error):
        return "error"
    if max_pri == priority_of(SessionState.attention):
        return "attention"
    if max_pri == priority_of(SessionState.working):
        return "working"
    return "idle"  # done_recent / idle / unknown


def compute_counts(sessions: list[Session]) -> dict[str, int]:
    """active session 计数：sessions / working / attention / error。"""
    active = [s for s in sessions if _is_active(s)]
    return {
        "sessions": len(active),
        "working": sum(1 for s in active if s.state == SessionState.working),
        "attention": sum(1 for s in active if s.state in (SessionState.attention, SessionState.plan)),
        "error": sum(1 for s in active if s.state == SessionState.error),
    }
