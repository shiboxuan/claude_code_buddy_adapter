"""ADP-P6: HTTP receiver 集成测试（4 endpoint + 错误路径 + sanitized + 性能）。"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from claude_code_buddy_adapter.claude.reducer import SessionState
from claude_code_buddy_adapter.config import AdapterConfig
from claude_code_buddy_adapter.receiver.http_server import create_app
from claude_code_buddy_adapter.session.snapshot import DisplayComposer
from claude_code_buddy_adapter.session.store import SessionStore


def _client(token=None, with_bridge=False):
    store = SessionStore()
    config = AdapterConfig()
    composer = DisplayComposer(config)
    bridge = None
    if with_bridge:
        from claude_code_buddy_adapter.device.bridge import SerialBridge
        from claude_code_buddy_adapter.device.fake_transport import FakeSerialTransport
        from claude_code_buddy_adapter.device.protocol import make_hello
        bridge = SerialBridge(FakeSerialTransport(), store, composer, config)
        bridge.handle_frame(make_hello("m5", "0", [], False))  # 握手 → device_connected
    app = create_app(store, composer, config, bridge=bridge, token=token)
    return TestClient(app), store


# ---- T02 statusline ----

def test_statusline_updates_state():
    client, store = _client()
    r = client.post("/v1/claude/statusline", json={
        "session_id": "s1", "model": {"id": "opus"}, "cwd": "/x/proj",
        "workspace": {"repo": {"name": "proj"}},
    })
    assert r.status_code == 200
    assert r.json()["ok"] is True
    state = client.get("/v1/state").json()
    assert state["sessions"][0]["session_id"] == "s1"
    assert state["sessions"][0]["repo"] == "proj"
    assert state["adapter_version"]


def test_statusline_missing_session_fallback():
    client, _ = _client()
    r = client.post("/v1/claude/statusline", json={"cwd": "/x/proj", "model": {"id": "m"}})
    assert r.status_code == 200  # 不抛，fallback


# ---- T03 hook ----

def test_hook_drives_state_machine():
    client, store = _client()
    r = client.post("/v1/claude/hook", json={"session_id": "s1", "hook_event_name": "PreToolUse"})
    assert r.status_code == 200
    assert store.get("s1").state == SessionState.working


def test_hook_attention_then_done():
    client, store = _client()
    client.post("/v1/claude/hook", json={
        "session_id": "s1",
        "hook_event_name": "Notification",
        "notification_type": "permission_prompt",
    })
    assert store.get("s1").state == SessionState.attention
    client.post("/v1/claude/hook", json={"session_id": "s1", "hook_event_name": "Stop"})
    assert store.get("s1").state == SessionState.done_recent


# ---- T04 /v1/state sanitized ----

def test_state_sanitized_no_sensitive_fields():
    client, _ = _client()
    client.post("/v1/claude/hook", json={
        "session_id": "s1", "hook_event_name": "PreToolUse",
        "cwd": "/secret/path", "tool_input": {"command": "secret"},
        "transcript_path": "/tmp/secret.jsonl",
    })
    sess = client.get("/v1/state").json()["sessions"][0]
    assert set(sess.keys()) == {"session_id", "state", "repo", "updated_at_ms"}
    assert "cwd" not in sess
    assert "tool_input" not in sess
    assert "transcript_path" not in sess


def test_state_fields_complete():
    state = _client()[0].get("/v1/state").json()
    assert state["ok"] is True
    for k in ("device_connected", "global_state", "focus_session_id", "sessions", "counts", "adapter_version"):
        assert k in state


def test_state_counts():
    client, _ = _client()
    client.post("/v1/claude/hook", json={"session_id": "s1", "hook_event_name": "PreToolUse"})
    client.post("/v1/claude/hook", json={
        "session_id": "s2",
        "hook_event_name": "Notification",
        "notification_type": "permission_prompt",
    })
    counts = client.get("/v1/state").json()["counts"]
    assert counts["sessions"] == 2
    assert counts["working"] == 1
    assert counts["attention"] == 1


def test_state_global_state_working():
    client, _ = _client(with_bridge=True)
    client.post("/v1/claude/hook", json={"session_id": "s1", "hook_event_name": "PreToolUse"})
    assert client.get("/v1/state").json()["global_state"] == "working"


# ---- T05 replay ----

def test_replay_returns_applied_state():
    client, _ = _client()
    r = client.post("/v1/debug/replay", json={
        "event": {"source": "hook", "session_id": "s1", "hook_event_name": "Stop"}
    })
    assert r.status_code == 200
    assert r.json()["applied_state"] == "done_recent"


def test_replay_missing_event():
    r = _client()[0].post("/v1/debug/replay", json={})
    assert r.status_code == 400
    assert r.json()["error"] == "missing_required_field"


def test_replay_bad_source():
    r = _client()[0].post("/v1/debug/replay", json={"event": {"source": "bad"}})
    assert r.status_code == 400


# ---- T06 错误响应 + 异常隔离 ----

def test_bad_json_returns_400():
    r = _client()[0].post(
        "/v1/claude/hook", content="not json",
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 400
    assert r.json()["error"] == "json_parse_error"


def test_unknown_route_returns_404():
    r = _client()[0].get("/v1/unknown")
    assert r.status_code == 404
    assert r.json()["ok"] is False


def test_error_responses_are_json_not_disconnect():
    """任何错误响应都是结构化 JSON（helper 能 exit 0）。"""
    client, _ = _client()
    for r in (
        client.post("/v1/claude/hook", content="bad", headers={"content-type": "application/json"}),
        client.get("/v1/nope"),
    ):
        assert r.status_code >= 400
        body = r.json()  # JSON 可解析，连接未断
        assert body["ok"] is False


# ---- X-Buddy-Token 预留 ----

def test_token_gate_rejects_missing_token():
    client, _ = _client(token="secret")
    assert client.get("/v1/state").status_code == 401


def test_token_gate_accepts_correct_token():
    client, _ = _client(token="secret")
    r = client.get("/v1/state", headers={"X-Buddy-Token": "secret"})
    assert r.status_code == 200


def test_no_token_gate_by_default():
    assert _client()[0].get("/v1/state").status_code == 200


# ---- T07 性能 P95 < 50ms ----

def test_state_p95_under_50ms():
    client, _ = _client()
    client.post("/v1/claude/hook", json={"session_id": "s1", "hook_event_name": "PreToolUse"})
    latencies = []
    for _ in range(50):
        t0 = time.perf_counter()
        client.get("/v1/state")
        latencies.append((time.perf_counter() - t0) * 1000)
    latencies.sort()
    p95 = latencies[int(len(latencies) * 0.95)]
    assert p95 < 50, f"P95 {p95:.1f}ms >= 50ms"
