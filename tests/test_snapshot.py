"""ADP-P4: DisplayComposer 单测（限长 / privacy_mode / 帧字段 / color）。"""

from __future__ import annotations

from claude_code_buddy_adapter.claude.reducer import SessionState, new_session
from claude_code_buddy_adapter.claude.textutil import display_width
from claude_code_buddy_adapter.config import AdapterConfig
from claude_code_buddy_adapter.device.protocol import assert_within_max
from claude_code_buddy_adapter.session.snapshot import (
    GLOBAL_COLOR,
    STATE_COLOR,
    DisplayComposer,
)


def _sess(sid: str = "s", state: SessionState = SessionState.idle, **kw):
    s = new_session(sid)
    s.state = state
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def _composer(privacy: bool = False) -> DisplayComposer:
    return DisplayComposer(AdapterConfig(privacy_mode=privacy))


# ---- focus_session 字段 ----

def test_focus_session_fields():
    s = _sess("abcdef1234", SessionState.working,
              repo_name="a/b/myrepo", cwd="/x/y/proj", last_tool="Bash", last_command="ls")
    fs = _composer().compose_focus_session(s)
    assert fs["id"] == "abcdef1234"
    assert fs["label"] == "abcdef12"  # 前 8 位
    assert fs["repo"] == "myrepo"  # basename
    assert fs["cwd"] == "proj"  # tail
    assert fs["state"] == "working"
    assert fs["title"] == "Working"
    assert fs["line1"] == "Bash"
    assert fs["line2"] == "ls"


def test_privacy_mode_hides_cwd_and_command():
    s = _sess("s", SessionState.working,
              repo_name="myrepo", cwd="/secret/path", last_command="secret cmd")
    fs = _composer(privacy=True).compose_focus_session(s)
    assert fs["cwd"] is None
    assert fs["line2"] == ""


def test_title_line_respect_pixel_width_limit():
    s = _sess("s", SessionState.attention, last_prompt="中" * 50)  # 50 中文 = 100 宽
    fs = _composer().compose_focus_session(s)
    assert display_width(fs["line1"]) <= 28
    assert display_width(fs["title"]) <= 20


def test_attention_text():
    s = _sess("s", SessionState.attention, last_prompt="need help")
    fs = _composer().compose_focus_session(s)
    assert fs["title"] == "Attention"
    assert fs["line1"] == "need help"


def test_error_text():
    s = _sess("s", SessionState.error, error_summary="boom")
    fs = _composer().compose_focus_session(s)
    assert fs["title"] == "Error"
    assert fs["line1"] == "boom"


def test_done_text():
    s = _sess("s", SessionState.done_recent, repo_name="repo")
    fs = _composer().compose_focus_session(s)
    assert fs["title"] == "Done"
    assert fs["repo"] == "repo"


def test_idle_text():
    s = _sess("s", SessionState.idle, repo_name="r", model="opus")
    fs = _composer().compose_focus_session(s)
    assert fs["title"] == "Idle"
    assert fs["line1"] == "r"
    assert fs["line2"] == "opus"


# ---- session_snapshot ----

def test_session_detail_has_color_and_age():
    s = _sess("s", SessionState.working, repo_name="r")
    s.updated_at_ms = 1000
    d = _composer().compose_session_detail(s, now_ms=3000)
    assert d["color"] == "red"
    assert d["age_sec"] == 2
    assert d["session_id_short"]


def test_session_snapshot_frame():
    s = _sess("s", SessionState.idle, repo_name="r")
    frame = _composer().compose_session_snapshot(s, seq=2, now_ms=1000)
    assert frame["type"] == "session_snapshot"
    assert frame["seq"] == 2
    assert frame["session"]["state"] == "idle"


# ---- color 映射 ----

def test_state_color_map():
    assert STATE_COLOR[SessionState.working] == "red"
    assert STATE_COLOR[SessionState.attention] == "yellow"
    assert STATE_COLOR[SessionState.plan] == "yellow"
    assert STATE_COLOR[SessionState.done_recent] == "blue"
    assert STATE_COLOR[SessionState.error] == "red_flash"
    assert STATE_COLOR[SessionState.idle] == "green"


def test_global_color_map():
    assert GLOBAL_COLOR["working"] == "red"
    assert GLOBAL_COLOR["attention"] == "yellow"
    assert GLOBAL_COLOR["error"] == "red_flash"


# ---- device_snapshot ----

def test_device_snapshot_fields():
    s = _sess("s1", SessionState.working, repo_name="r")
    frame = _composer().compose_device_snapshot([s], device_connected=True, seq=1, now_ms=1000)
    assert frame["type"] == "device_snapshot"
    assert frame["seq"] == 1
    assert frame["global_state"] == "working"
    assert frame["color"] == "red"
    assert frame["focus_session"]["id"] == "s1"
    assert frame["counts"]["working"] == 1
    assert frame["alert"] is None


def test_device_snapshot_no_session_adapter_connected():
    frame = _composer().compose_device_snapshot([], device_connected=True, seq=1, now_ms=1000)
    assert frame["global_state"] == "adapter_connected"
    assert frame["focus_session"] is None


def test_device_snapshot_disconnected():
    frame = _composer().compose_device_snapshot([], device_connected=False, seq=1, now_ms=1000)
    assert frame["global_state"] == "device_disconnected"
    assert frame["color"] == "gray"


def test_device_snapshot_serializes_under_1024():
    s = _sess("s1", SessionState.working, repo_name="r", last_tool="Bash", last_command="ls -la")
    frame = _composer().compose_device_snapshot([s], device_connected=True, seq=1, now_ms=1000)
    assert_within_max(frame)  # 不抛


def test_focus_session_progress_passthrough():
    s = _sess("s", SessionState.working)
    s.progress = 42.5
    fs = _composer().compose_focus_session(s)
    assert fs["progress"] == 42.5
