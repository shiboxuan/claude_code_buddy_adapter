"""ADP-P2: reducer 状态机单元测试。

覆盖状态图全部边、14 个 hook_event_name 映射、TTL 降级、error 进出、不可变与元数据。
"""

from __future__ import annotations

import pytest

from claude_code_buddy_adapter.claude.event_model import ClaudeEvent
from claude_code_buddy_adapter.claude.reducer import (
    HOOK_STATE_MAP,
    Session,
    SessionState,
    new_session,
    reduce_event,
    tick,
)


def _hook(name: str | None, session_id: str = "s", **extra) -> ClaudeEvent:
    payload = {"session_id": session_id, "hook_event_name": name, **extra}
    return ClaudeEvent(
        event_id="e", source="hook", received_at_ms=1000,
        session_id=session_id, hook_event_name=name,
        cwd=extra.get("cwd"), raw=payload,
    )


def _statusline(session_id: str = "s", **extra) -> ClaudeEvent:
    payload = {"session_id": session_id, **extra}
    return ClaudeEvent(
        event_id="e", source="statusline", received_at_ms=1000,
        session_id=session_id, cwd=extra.get("cwd"), raw=payload,
    )


# ---------------- T01 Session 状态模型 ----------------

def test_session_state_enum_has_8_values():
    expected = {"unknown", "idle", "working", "attention", "plan",
                "done_recent", "error", "ended"}
    assert {s.value for s in SessionState} == expected


def test_new_session_is_unknown():
    s = new_session("s1")
    assert s.state == SessionState.unknown
    assert s.session_id == "s1"
    assert s.repo_name is None
    assert s.updated_at_ms == 0


# ---------------- T02 状态图每条边 ----------------

def test_unknown_to_idle_session_start():
    assert reduce_event(new_session("s"), _hook("SessionStart")).state == SessionState.idle


def test_unknown_to_idle_statusline():
    assert reduce_event(new_session("s"), _statusline()).state == SessionState.idle


def test_idle_to_working():
    s = reduce_event(new_session("s"), _hook("SessionStart"))
    assert reduce_event(s, _hook("UserPromptSubmit")).state == SessionState.working


def test_working_to_attention():
    s = reduce_event(new_session("s"), _hook("PreToolUse"))
    assert reduce_event(s, _hook("PermissionRequest")).state == SessionState.attention


def test_attention_to_working_elicitation_result():
    s = reduce_event(new_session("s"), _hook("Notification"))
    assert reduce_event(s, _hook("ElicitationResult")).state == SessionState.working


def test_attention_to_working_new_tool():
    s = reduce_event(new_session("s"), _hook("Notification"))
    assert reduce_event(s, _hook("PreToolUse")).state == SessionState.working


def test_working_to_done_recent():
    s = reduce_event(new_session("s"), _hook("PreToolUse"))
    assert reduce_event(s, _hook("Stop")).state == SessionState.done_recent


def test_working_to_error_stopfailure():
    s = reduce_event(new_session("s"), _hook("PreToolUse"))
    assert reduce_event(s, _hook("StopFailure", error="boom")).state == SessionState.error


def test_working_to_error_posttooluse_failure():
    s = reduce_event(new_session("s"), _hook("PreToolUse"))
    s = reduce_event(s, _hook("PostToolUse", error="tool failed"))
    assert s.state == SessionState.error
    assert s.error_summary == "tool failed"


def test_attention_to_error_stopfailure():
    s = reduce_event(new_session("s"), _hook("Notification"))
    assert reduce_event(s, _hook("StopFailure", error="x")).state == SessionState.error


def test_done_recent_to_idle_ttl():
    s = reduce_event(new_session("s"), _hook("PreToolUse"), now_ms=1000)
    s = reduce_event(s, _hook("Stop"), now_ms=2000)
    assert tick(s, now_ms=7000, done_ttl_ms=5000).state == SessionState.idle


def test_error_to_working_new_prompt():
    s = reduce_event(new_session("s"), _hook("StopFailure", error="x"))
    assert reduce_event(s, _hook("UserPromptSubmit")).state == SessionState.working


def test_idle_to_ended():
    s = reduce_event(new_session("s"), _hook("SessionStart"))
    assert reduce_event(s, _hook("SessionEnd")).state == SessionState.ended


def test_done_recent_to_ended():
    s = reduce_event(new_session("s"), _hook("Stop"))
    assert reduce_event(s, _hook("SessionEnd")).state == SessionState.ended


def test_error_to_ended():
    s = reduce_event(new_session("s"), _hook("StopFailure", error="x"))
    assert reduce_event(s, _hook("SessionEnd")).state == SessionState.ended


# ---------------- T03 hook_event_name → 状态映射 ----------------

@pytest.mark.parametrize("name,expected", [
    ("SessionStart", SessionState.idle),
    ("UserPromptSubmit", SessionState.working),
    ("PreToolUse", SessionState.working),
    ("PostToolUse", SessionState.working),
    ("MessageDisplay", SessionState.working),
    ("SubagentStart", SessionState.working),
    ("TaskCreated", SessionState.working),
    ("Notification", SessionState.attention),
    ("PermissionRequest", SessionState.attention),
    ("Elicitation", SessionState.attention),
    ("ElicitationResult", SessionState.working),
    ("Stop", SessionState.done_recent),
    ("StopFailure", SessionState.error),
    ("SessionEnd", SessionState.ended),
])
def test_hook_event_state_mapping(name, expected):
    s = reduce_event(new_session("s"), _hook(name))
    assert s.state == expected


def test_hook_state_map_is_complete():
    assert set(HOOK_STATE_MAP) == {
        "SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
        "MessageDisplay", "SubagentStart", "TaskCreated", "Notification",
        "PermissionRequest", "Elicitation", "ElicitationResult", "Stop",
        "StopFailure", "SessionEnd",
    }
    assert len(HOOK_STATE_MAP) == 14


# ---------------- T04 TTL 机制 ----------------

def test_done_recent_within_ttl_stays():
    s = reduce_event(new_session("s"), _hook("Stop"), now_ms=1000)
    assert tick(s, now_ms=4000, done_ttl_ms=5000).state == SessionState.done_recent


def test_attention_stale_to_idle():
    s = reduce_event(new_session("s"), _hook("Notification"), now_ms=1000)
    assert tick(s, now_ms=301000, session_ttl_ms=300000).state == SessionState.idle


def test_attention_within_ttl_stays():
    s = reduce_event(new_session("s"), _hook("Notification"), now_ms=1000)
    assert tick(s, now_ms=100000, session_ttl_ms=300000).state == SessionState.attention


def test_error_stale_to_idle():
    s = reduce_event(new_session("s"), _hook("StopFailure", error="x"), now_ms=1000)
    assert tick(s, now_ms=301000, session_ttl_ms=300000).state == SessionState.idle


def test_tick_does_not_change_other_states():
    s = reduce_event(new_session("s"), _hook("PreToolUse"))
    assert tick(s, now_ms=9_999_999).state == SessionState.working


# ---------------- T05 error 进入/退出 ----------------

def test_error_entered_on_stopfailure():
    s = reduce_event(new_session("s"), _hook("StopFailure", error="crash"))
    assert s.state == SessionState.error
    assert s.error_summary == "crash"


def test_error_entered_on_posttooluse_failure():
    assert reduce_event(new_session("s"), _hook("PostToolUse", error="fail")).state == SessionState.error


def test_posttooluse_without_error_is_working():
    assert reduce_event(new_session("s"), _hook("PostToolUse")).state == SessionState.working


def test_error_exit_new_prompt():
    s = reduce_event(new_session("s"), _hook("StopFailure", error="x"))
    assert reduce_event(s, _hook("UserPromptSubmit")).state == SessionState.working


def test_error_exit_session_end():
    s = reduce_event(new_session("s"), _hook("StopFailure", error="x"))
    assert reduce_event(s, _hook("SessionEnd")).state == SessionState.ended


def test_error_exit_timeout():
    s = reduce_event(new_session("s"), _hook("StopFailure", error="x"), now_ms=1000)
    assert tick(s, now_ms=301000, session_ttl_ms=300000).state == SessionState.idle


# ---------------- 不可变 + 元数据 ----------------

def test_reduce_event_does_not_mutate_input():
    s = new_session("s")
    s2 = reduce_event(s, _hook("Stop"))
    assert s.state == SessionState.unknown
    assert s2.state == SessionState.done_recent


def test_metadata_updated_from_hook_event():
    ev = _hook("PreToolUse", tool_name="Bash", file_path="/x", cwd="/y",
               workspace={"project_dir": "/proj"}, tool_input={"command": "ls"},
               prompt="do it")
    s = reduce_event(new_session("s"), ev)
    assert s.last_tool == "Bash"
    assert s.last_file == "/x"
    assert s.cwd == "/y"
    assert s.project_dir == "/proj"
    assert s.last_command == "ls"
    assert s.last_prompt == "do it"
    assert s.updated_at_ms == 1000


def test_statusline_updates_metadata():
    ev = _statusline(model={"id": "opus"}, workspace={"repo": {"name": "r"}})
    s = reduce_event(new_session("s"), ev)
    assert s.model == "opus"
    assert s.repo_name == "r"
    assert s.state == SessionState.idle  # unknown → idle


def test_unknown_hook_event_keeps_state():
    s = reduce_event(new_session("s"), _hook("SessionStart"))
    s = reduce_event(s, _hook("SomethingUnknown"))
    assert s.state == SessionState.idle


def test_statusline_does_not_change_working_state():
    s = reduce_event(new_session("s"), _hook("PreToolUse"))  # working
    s = reduce_event(s, _statusline())
    assert s.state == SessionState.working
