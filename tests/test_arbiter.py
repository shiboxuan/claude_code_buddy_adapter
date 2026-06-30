"""ADP-P3: focus arbiter + global state + counts 单测（BR-001/BR-005/BR-006）。"""

from __future__ import annotations

from claude_code_buddy_adapter.claude.reducer import SessionState, new_session
from claude_code_buddy_adapter.session.arbiter import (
    compute_counts,
    compute_global_state,
    priority_of,
    select_focus,
)


def _sess(sid: str, state: SessionState, updated: int = 0, attention_since: int | None = None):
    s = new_session(sid)
    s.state = state
    s.updated_at_ms = updated
    s.attention_since_ms = attention_since
    return s


# ---- BR-001 global state 优先级 ----

def test_global_state_device_disconnected():
    assert compute_global_state([], device_connected=False) == "device_disconnected"


def test_global_state_adapter_connected_no_session():
    assert compute_global_state([], device_connected=True) == "adapter_connected"


def test_global_state_error_beats_attention():
    sessions = [_sess("a", SessionState.attention), _sess("b", SessionState.error)]
    assert compute_global_state(sessions, True) == "error"


def test_global_state_attention_beats_working():
    sessions = [_sess("a", SessionState.working), _sess("b", SessionState.attention)]
    assert compute_global_state(sessions, True) == "attention"


def test_global_state_working():
    assert compute_global_state([_sess("a", SessionState.working)], True) == "working"


def test_global_state_done_recent_maps_to_idle():
    # done_recent 不在 §5.2 值集 → idle
    assert compute_global_state([_sess("a", SessionState.done_recent)], True) == "idle"


def test_global_state_idle():
    assert compute_global_state([_sess("a", SessionState.idle)], True) == "idle"


def test_global_state_ended_not_counted():
    assert compute_global_state([_sess("a", SessionState.ended)], True) == "adapter_connected"


# ---- BR-005 focus：多 attention → 最近进入 attention ----

def test_focus_none_when_empty():
    assert select_focus([]) is None


def test_focus_attention_most_recent():
    a = _sess("a", SessionState.attention, attention_since=1000)
    b = _sess("b", SessionState.attention, attention_since=2000)
    assert select_focus([a, b]).session_id == "b"


def test_focus_error_beats_attention():
    a = _sess("a", SessionState.attention, attention_since=2000)
    b = _sess("b", SessionState.error, updated=1000)
    assert select_focus([a, b]).session_id == "b"


# ---- BR-006 focus：多 working 无 attention → 最近更新 ----

def test_focus_working_most_recent_updated():
    a = _sess("a", SessionState.working, updated=1000)
    b = _sess("b", SessionState.working, updated=2000)
    assert select_focus([a, b]).session_id == "b"


def test_focus_ended_not_selected():
    a = _sess("a", SessionState.ended, updated=9999)
    b = _sess("b", SessionState.working, updated=1000)
    assert select_focus([a, b]).session_id == "b"


def test_focus_attention_beats_working():
    a = _sess("a", SessionState.working, updated=9999)
    b = _sess("b", SessionState.attention, attention_since=1)
    assert select_focus([a, b]).session_id == "b"


# ---- counts ----

def test_counts():
    sessions = [
        _sess("a", SessionState.working),
        _sess("b", SessionState.attention),
        _sess("c", SessionState.error),
        _sess("d", SessionState.idle),
        _sess("e", SessionState.ended),
    ]
    c = compute_counts(sessions)
    assert c["sessions"] == 4  # ended 不计
    assert c["working"] == 1
    assert c["attention"] == 1
    assert c["error"] == 1


def test_priority_ordering():
    assert priority_of(SessionState.error) > priority_of(SessionState.attention)
    assert priority_of(SessionState.attention) > priority_of(SessionState.working)
    assert priority_of(SessionState.working) > priority_of(SessionState.done_recent)
    assert priority_of(SessionState.done_recent) > priority_of(SessionState.idle)
    assert priority_of(SessionState.plan) == priority_of(SessionState.attention)
