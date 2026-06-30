"""ADP-P3: SessionStore 单测（线程安全、TTL 清理、归档、debug JSONL、snapshot）。"""

from __future__ import annotations

import json
import threading

from claude_code_buddy_adapter.claude.event_model import ClaudeEvent
from claude_code_buddy_adapter.claude.reducer import SessionState, new_session
from claude_code_buddy_adapter.session.store import SessionStore


def _hook(name: str, session_id: str = "s", **extra) -> ClaudeEvent:
    payload = {"session_id": session_id, "hook_event_name": name, **extra}
    return ClaudeEvent(
        event_id="e", source="hook", received_at_ms=1000,
        session_id=session_id, hook_event_name=name,
        cwd=extra.get("cwd"), raw=payload,
    )


def test_get_missing_returns_none():
    assert SessionStore().get("nope") is None


def test_apply_event_creates_session():
    store = SessionStore()
    s = store.apply_event(_hook("SessionStart", "s1"))
    assert s.state == SessionState.idle
    assert store.get("s1").state == SessionState.idle


def test_apply_event_transitions():
    store = SessionStore()
    store.apply_event(_hook("SessionStart", "s1"))
    store.apply_event(_hook("UserPromptSubmit", "s1"))
    assert store.get("s1").state == SessionState.working


def test_apply_event_archives_ended():
    store = SessionStore()
    store.apply_event(_hook("SessionStart", "s1"))
    store.apply_event(_hook("SessionEnd", "s1"))
    assert store.get("s1") is None  # 已归档
    assert store.get_archived("s1") is not None
    assert store.counts()["sessions"] == 0


def test_ended_not_in_focus():
    store = SessionStore()
    store.apply_event(_hook("SessionEnd", "s1"))
    assert store.focus() is None


def test_counts_and_focus_attention_priority():
    store = SessionStore()
    store.apply_event(_hook("PreToolUse", "s1"), now_ms=1000)
    store.apply_event(_hook("Notification", "s2"), now_ms=2000)
    c = store.counts()
    assert c["working"] == 1
    assert c["attention"] == 1
    assert store.focus().session_id == "s2"  # attention 优先


def test_global_state_aggregation():
    store = SessionStore()
    store.apply_event(_hook("PreToolUse", "s1"))
    assert store.global_state(device_connected=True) == "working"
    assert store.global_state(device_connected=False) == "device_disconnected"
    assert store.global_state(device_connected=True) != "device_disconnected"


def test_global_state_adapter_connected_when_no_session():
    store = SessionStore()
    assert store.global_state(device_connected=True) == "adapter_connected"


def test_cleanup_ttl_downgrades_done_recent():
    store = SessionStore(done_ttl_ms=5000)
    store.apply_event(_hook("Stop", "s1"), now_ms=1000)  # done_recent at 1000
    store.cleanup(now_ms=7000)  # 6000 >= 5000 → idle
    assert store.get("s1").state == SessionState.idle


def test_cleanup_within_ttl_stays():
    store = SessionStore(done_ttl_ms=5000)
    store.apply_event(_hook("Stop", "s1"), now_ms=1000)
    store.cleanup(now_ms=4000)  # 3000 < 5000
    assert store.get("s1").state == SessionState.done_recent


def test_thread_safety_concurrent_apply():
    store = SessionStore()

    def worker(i: int) -> None:
        for j in range(50):
            store.apply_event(_hook("PreToolUse", f"s{i}"), now_ms=j)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    c = store.counts()
    assert c["sessions"] == 8
    assert c["working"] == 8


def test_snapshot():
    store = SessionStore()
    store.apply_event(_hook("PreToolUse", "s1"), now_ms=1000)
    snap = store.snapshot(device_connected=True)
    assert snap["device_connected"] is True
    assert snap["global_state"] == "working"
    assert snap["focus_session_id"] == "s1"
    assert snap["counts"]["working"] == 1


def test_debug_jsonl(tmp_path):
    p = tmp_path / "debug.jsonl"
    store = SessionStore(debug_jsonl=str(p))
    store.apply_event(_hook("SessionStart", "s1"))
    assert p.exists()
    lines = p.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["session_id"] == "s1"
    assert rec["state"] == "idle"


def test_get_returns_copy_not_internal():
    store = SessionStore()
    s = new_session("s1")
    s.state = SessionState.working
    store.upsert(s)
    got = store.get("s1")
    got.state = SessionState.idle  # 外部修改不影响 store
    assert store.get("s1").state == SessionState.working


def test_active_excludes_ended():
    store = SessionStore()
    store.apply_event(_hook("PreToolUse", "s1"))
    store.apply_event(_hook("SessionEnd", "s2"))
    active = store.active()
    assert len(active) == 1
    assert active[0].session_id == "s1"
