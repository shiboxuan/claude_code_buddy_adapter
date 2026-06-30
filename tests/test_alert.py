"""ADP-P4: alert 边沿触发单测（§5.8 + BR-009）。"""

from __future__ import annotations

from claude_code_buddy_adapter.claude.reducer import SessionState
from claude_code_buddy_adapter.device.alert import AlertTracker


def test_connected_not_repeated():
    t = AlertTracker()
    a1 = t.on_connect(seq=1)
    assert a1 is not None and a1["kind"] == "connected"
    assert t.on_connect(seq=2) is None  # 不重复


def test_attention_edge_once_per_session():
    t = AlertTracker()
    # working → attention：发一次
    a = t.on_session_change("s1", SessionState.working, SessionState.attention, seq=1)
    assert a is not None and a["kind"] == "attention" and a["session_id"] == "s1"
    # 连续 attention：不重复
    assert t.on_session_change("s1", SessionState.attention, SessionState.attention, seq=2) is None
    # attention → working：不发
    assert t.on_session_change("s1", SessionState.attention, SessionState.working, seq=3) is None
    # working → attention 再次：再发一次（离开后重置）
    a = t.on_session_change("s1", SessionState.working, SessionState.attention, seq=4)
    assert a is not None and a["kind"] == "attention"


def test_attention_independent_per_session():
    t = AlertTracker()
    a1 = t.on_session_change("s1", SessionState.working, SessionState.attention, seq=1)
    a2 = t.on_session_change("s2", SessionState.working, SessionState.attention, seq=2)
    assert a1 is not None and a2 is not None
    assert a1["session_id"] == "s1"
    assert a2["session_id"] == "s2"


def test_error_edge():
    t = AlertTracker()
    a = t.on_session_change("s1", SessionState.working, SessionState.error, seq=1)
    assert a is not None and a["kind"] == "error"
    # 连续 error：不重复
    assert t.on_session_change("s1", SessionState.error, SessionState.error, seq=2) is None


def test_done_edge():
    t = AlertTracker()
    a = t.on_session_change("s1", SessionState.working, SessionState.done_recent, seq=1)
    assert a is not None and a["kind"] == "done"


def test_done_alert_disabled():
    t = AlertTracker(done_alert_enabled=False)
    a = t.on_session_change("s1", SessionState.working, SessionState.done_recent, seq=1)
    assert a is None


def test_no_alert_on_same_state():
    t = AlertTracker()
    assert t.on_session_change("s1", SessionState.working, SessionState.working, seq=1) is None


def test_attention_to_error_sends_error_alert():
    t = AlertTracker()
    t.on_session_change("s1", SessionState.working, SessionState.attention, seq=1)
    a = t.on_session_change("s1", SessionState.attention, SessionState.error, seq=2)
    assert a is not None and a["kind"] == "error"


def test_reset_allows_connected_again():
    t = AlertTracker()
    t.on_connect(seq=1)
    assert t.on_connect(seq=2) is None
    t.reset()
    assert t.on_connect(seq=3) is not None  # 重连后再发 connected


def test_alert_carries_seq_and_sound():
    t = AlertTracker(sound_enabled=True)
    a = t.on_connect(seq=42)
    assert a["seq"] == 42
    assert a["sound"] is True


def test_sound_disabled_propagates():
    t = AlertTracker(sound_enabled=False)
    a = t.on_session_change("s1", SessionState.working, SessionState.attention, seq=1)
    assert a["sound"] is False
