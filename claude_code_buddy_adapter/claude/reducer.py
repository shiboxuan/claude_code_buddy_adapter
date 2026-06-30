"""状态机 reducer：把 ClaudeEvent 转成 session state。

状态图对齐 system-design §状态变化 stateDiagram-v2（13 条边）；
状态枚举对齐 §5.1（8 状态）；hook→状态映射对齐 protocol §5.6；
TTL 对齐 BR-007（done_recent 5s→idle）/ BR-008（attention/error 超时降级）。
reducer 为纯函数风格：返回新 Session，不原地修改输入。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Optional

from .event_model import ClaudeEvent


class SessionState(str, Enum):
    """§5.1 的 8 个 session 状态。"""

    unknown = "unknown"
    idle = "idle"
    working = "working"
    attention = "attention"
    plan = "plan"
    done_recent = "done_recent"
    error = "error"
    ended = "ended"


# protocol §5.6 hook_event_name → 目标状态（T03 映射权威表）
HOOK_STATE_MAP: dict[str, SessionState] = {
    "SessionStart": SessionState.idle,
    "UserPromptSubmit": SessionState.working,
    "PreToolUse": SessionState.working,
    "PostToolUse": SessionState.working,  # 带 error 时 reducer 特判 → error
    "MessageDisplay": SessionState.working,
    "SubagentStart": SessionState.working,
    "TaskCreated": SessionState.working,
    "Notification": SessionState.attention,
    "PermissionRequest": SessionState.attention,
    "Elicitation": SessionState.attention,
    "ElicitationResult": SessionState.working,  # attention → working
    "Stop": SessionState.done_recent,
    "StopFailure": SessionState.error,
    "SessionEnd": SessionState.ended,
}

ATTENTION_EVENTS = frozenset({"Notification", "PermissionRequest", "Elicitation"})
WORKING_EVENTS = frozenset({
    "UserPromptSubmit", "PreToolUse", "PostToolUse", "MessageDisplay",
    "SubagentStart", "TaskCreated", "ElicitationResult",
})


@dataclass
class Session:
    """按 session_id 聚合的 Claude Code session（system-design §数据实体 Session）。"""

    session_id: str
    state: SessionState = SessionState.unknown
    repo_name: Optional[str] = None
    cwd: Optional[str] = None
    project_dir: Optional[str] = None
    model: Optional[str] = None
    last_prompt: Optional[str] = None
    last_tool: Optional[str] = None
    last_file: Optional[str] = None
    last_command: Optional[str] = None
    plan_summary: Optional[str] = None
    error_summary: Optional[str] = None
    updated_at_ms: int = 0
    attention_since_ms: Optional[int] = None
    # TTL 起算时间
    done_at_ms: Optional[int] = None
    error_since_ms: Optional[int] = None


def new_session(session_id: str) -> Session:
    """创建一个 unknown 状态的新 session。"""
    return Session(session_id=session_id, state=SessionState.unknown)


def reduce_event(
    session: Session, event: ClaudeEvent, now_ms: Optional[int] = None
) -> Session:
    """把 ``event`` 应用到 ``session``，返回新 Session（输入不变）。

    实现状态图全部边；未知 hook_event_name 保持当前状态（normalizer 已 warning）。
    """
    s = replace(session)
    now = now_ms if now_ms is not None else event.received_at_ms
    name = event.hook_event_name

    if name is None and event.source == "statusline":
        # statusLine 不驱动状态机，但 unknown → idle（首次见到 session）
        if s.state == SessionState.unknown:
            s.state = SessionState.idle
    elif name == "SessionEnd":
        s.state = SessionState.ended  # 任何状态 → ended
    elif name == "StopFailure":
        s.state = SessionState.error
        s.error_since_ms = now
        s.error_summary = event.error or "stop failure"
    elif name == "PostToolUse" and event.error:
        # PostToolUseFailure → error
        s.state = SessionState.error
        s.error_since_ms = now
        s.error_summary = event.error
    elif name == "Stop":
        s.state = SessionState.done_recent
        s.done_at_ms = now
        s.attention_since_ms = None
    elif name in ATTENTION_EVENTS:
        s.state = SessionState.attention
        s.attention_since_ms = now
    elif name in WORKING_EVENTS:
        s.state = SessionState.working
        s.attention_since_ms = None
    elif name == "SessionStart":
        s.state = SessionState.idle
        s.attention_since_ms = None
    # 未知 hook_event_name：保持当前状态（容错）

    s.updated_at_ms = now
    _apply_metadata(s, event)
    return s


def _apply_metadata(s: Session, event: ClaudeEvent) -> None:
    """从 event 更新 session 展示元数据（不影响状态判断）。"""
    if event.cwd:
        s.cwd = event.cwd
    if event.repo_name:
        s.repo_name = event.repo_name
    if event.model_id:
        s.model = event.model_id
    ws = event.raw.get("workspace")
    if isinstance(ws, dict) and ws.get("project_dir"):
        s.project_dir = ws.get("project_dir")
    if event.tool_name:
        s.last_tool = event.tool_name
    if event.file_path:
        s.last_file = event.file_path
    ti = event.tool_input
    if isinstance(ti, dict) and ti.get("command"):
        s.last_command = ti.get("command")
    prompt = event.raw.get("prompt")
    if prompt:
        s.last_prompt = prompt
    elif event.message:
        s.last_prompt = event.message
    if event.title:
        s.plan_summary = event.title
    if event.error and s.state == SessionState.error and not s.error_summary:
        s.error_summary = event.error


def tick(
    session: Session,
    now_ms: int,
    done_ttl_ms: int = 5000,
    session_ttl_ms: int = 300_000,
) -> Session:
    """惰性 TTL 降级（BR-007/BR-008），返回新 Session。

    - done_recent 经 done_ttl_ms → idle
    - attention 超过 session_ttl_ms → idle（stale attention 降级）
    - error 超过 session_ttl_ms → idle（错误超时降级）
    """
    s = replace(session)
    if s.state == SessionState.done_recent and s.done_at_ms is not None:
        if now_ms - s.done_at_ms >= done_ttl_ms:
            s.state = SessionState.idle
            s.done_at_ms = None
    elif s.state == SessionState.attention and s.attention_since_ms is not None:
        if now_ms - s.attention_since_ms >= session_ttl_ms:
            s.state = SessionState.idle
            s.attention_since_ms = None
    elif s.state == SessionState.error and s.error_since_ms is not None:
        if now_ms - s.error_since_ms >= session_ttl_ms:
            s.state = SessionState.idle
            s.error_since_ms = None
            s.error_summary = None
    return s
