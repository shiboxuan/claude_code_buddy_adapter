"""ADP-P1: ClaudeEvent / normalizer / textutil 单元测试 + fixture。

覆盖 protocol §3.2（statusLine）/ §3.3（hooks）全字段、14 个 hook_event_name、
字段限长（像素等价宽度，中文按 2 宽）、unknown/missing/null/缺 session_id 容错。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from claude_code_buddy_adapter.claude import textutil
from claude_code_buddy_adapter.claude.event_model import ClaudeEvent
from claude_code_buddy_adapter.claude.normalizer import (
    KNOWN_HOOK_EVENTS,
    normalize,
    normalize_hook,
    normalize_statusline,
)

FIXTURES = Path(__file__).parent / "fixtures"
EVENT_LOGGER = "claude_code_buddy_adapter.event"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _event_log_propagate():
    """event logger 默认 propagate=False（见 logging_setup），测试期开启以供 caplog 捕获。"""
    logger = logging.getLogger(EVENT_LOGGER)
    old = logger.propagate
    logger.propagate = True
    yield
    logger.propagate = old


# ---------------- T01 ClaudeEvent 数据模型 ----------------

def test_event_model_construct_kw_only():
    ev = ClaudeEvent(
        event_id="e1", source="hook", received_at_ms=1000,
        session_id="s1", hook_event_name="Stop", cwd="/x", raw={"a": 1},
    )
    assert ev.event_id == "e1"
    assert ev.source == "hook"
    assert ev.received_at_ms == 1000
    assert ev.session_id == "s1"
    assert ev.hook_event_name == "Stop"
    assert ev.cwd == "/x"
    assert ev.raw == {"a": 1}


def test_event_model_rejects_positional_args():
    with pytest.raises(TypeError):
        ClaudeEvent("e1", "hook", 1000)  # kw_only：禁止位置参数


def test_event_model_hook_accessors():
    ev = ClaudeEvent(
        event_id="e", source="hook", received_at_ms=0,
        raw={
            "tool_name": "Bash", "tool_input": {"command": "ls"},
            "message": "hi", "title": "t", "error": "boom",
            "agent_id": "a1", "task_id": "t1", "file_path": "/f",
            "reason": "r", "notification_type": "n", "transcript_path": "/t",
        },
    )
    assert ev.tool_name == "Bash"
    assert ev.tool_input == {"command": "ls"}
    assert ev.message == "hi"
    assert ev.title == "t"
    assert ev.error == "boom"
    assert ev.agent_id == "a1"
    assert ev.task_id == "t1"
    assert ev.file_path == "/f"
    assert ev.reason == "r"
    assert ev.notification_type == "n"
    assert ev.transcript_path == "/t"


def test_event_model_statusline_accessors():
    ev = ClaudeEvent(
        event_id="e", source="statusline", received_at_ms=0,
        raw={
            "model": {"id": "claude-opus-4-8", "display_name": "Opus"},
            "workspace": {"repo": {"name": "myrepo"}},
            "cost": {"total_cost_usd": 0.5, "total_duration_ms": 1000},
            "context_window": {"used_percentage": 40.0},
        },
    )
    assert ev.model_id == "claude-opus-4-8"
    assert ev.model_display_name == "Opus"
    assert ev.repo_name == "myrepo"
    assert ev.cost_usd == 0.5
    assert ev.cost_duration_ms == 1000
    assert ev.context_used_percentage == 40.0


def test_event_model_missing_accessors_none():
    ev = ClaudeEvent(event_id="e", source="hook", received_at_ms=0, raw={})
    assert ev.tool_name is None
    assert ev.model_id is None
    assert ev.repo_name is None
    assert ev.cost_usd is None


# ---------------- T02 statusLine normalizer ----------------

def test_normalize_statusline_fixture_full_fields():
    payload = _load("statusline_basic.json")
    ev = normalize_statusline(payload, received_at_ms=12345)
    assert ev.source == "statusline"
    assert ev.session_id == "abc123-456-789"
    assert ev.hook_event_name is None
    assert ev.cwd == payload["cwd"]
    assert ev.received_at_ms == 12345
    assert ev.event_id
    assert ev.raw == payload
    assert ev.model_id == "claude-opus-4-8"
    assert ev.repo_name == "claude_code_buddy_adapter"
    assert ev.cost_usd == 0.42
    assert ev.cost_duration_ms == 12000
    assert ev.context_used_percentage == 35.5


def test_normalize_statusline_missing_session_fallback():
    ev = normalize_statusline({"cwd": "/x/y", "model": {"id": "m"}})
    assert ev.session_id == "cwd:/x/y"
    assert ev.cwd == "/x/y"


def test_normalize_statusline_received_at_default():
    ev = normalize_statusline({"session_id": "s"})
    assert ev.received_at_ms > 0


# ---------------- T03 hooks normalizer ----------------

ALL_HOOKS = [
    "SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
    "MessageDisplay", "SubagentStart", "TaskCreated", "Notification",
    "PermissionRequest", "Elicitation", "ElicitationResult", "Stop",
    "StopFailure", "SessionEnd",
]


@pytest.mark.parametrize("name", ALL_HOOKS)
def test_normalize_hook_all_event_names(name):
    ev = normalize_hook({"session_id": "s", "hook_event_name": name})
    assert ev.source == "hook"
    assert ev.hook_event_name == name
    assert ev.session_id == "s"


def test_known_hook_events_is_full_set():
    assert KNOWN_HOOK_EVENTS == frozenset(ALL_HOOKS)
    assert len(KNOWN_HOOK_EVENTS) == 14


def test_normalize_hook_event_specific_fields():
    payload = {
        "session_id": "s", "hook_event_name": "PreToolUse",
        "tool_name": "Bash", "tool_input": {"command": "ls"},
    }
    ev = normalize_hook(payload)
    assert ev.tool_name == "Bash"
    assert ev.tool_input == {"command": "ls"}


def test_normalize_hook_fixture_pretooluse():
    payload = _load("hook_pretooluse.json")
    ev = normalize_hook(payload)
    assert ev.hook_event_name == "PreToolUse"
    assert ev.tool_name == "Bash"
    assert ev.transcript_path == "/tmp/abc.jsonl"


def test_normalize_hook_fixture_session_start():
    ev = normalize_hook(_load("hook_session_start.json"))
    assert ev.hook_event_name == "SessionStart"
    assert ev.cwd.endswith("claude_code_buddy_adapter")


# ---------------- T04 字段限长 / 截断 ----------------

def test_display_width_ascii_cjk():
    assert textutil.display_width("abc") == 3
    assert textutil.display_width("中文") == 4
    assert textutil.display_width("a中") == 3
    assert textutil.display_width("") == 0


def test_truncate_width_ascii():
    assert textutil.truncate_width("abcdefghij", 5) == "abcde"


def test_truncate_width_cjk():
    # 4 个中文 = 8 宽；截到 5 宽只能放 2 个中文（4 宽），第 3 个会超 5
    assert textutil.truncate_width("中文测试", 5) == "中文"


def test_truncate_width_ellipsis():
    # "中"(2)+"…"(2)=4 <= 6；"中文"(4)+"…"(2)=6 <= 6 → 取后者
    assert textutil.truncate_width("中文测试", 6, ellipsis="…") == "中文…"


def test_truncate_width_no_change_when_within_limit():
    assert textutil.truncate_width("abc", 10) == "abc"
    assert textutil.truncate_width(None, 10) == ""


def test_repo_basename():
    assert textutil.repo_basename({"name": "myrepo"}) == "myrepo"
    assert textutil.repo_basename("a/b/c") == "c"
    assert textutil.repo_basename("c") == "c"
    assert textutil.repo_basename("a/b/") == "b"
    assert textutil.repo_basename(None) is None
    assert textutil.repo_basename({}) is None


def test_cwd_tail():
    assert textutil.cwd_tail("/home/user/project") == "project"
    assert textutil.cwd_tail("/home/user/project/") == "project"
    assert textutil.cwd_tail("project") == "project"
    assert textutil.cwd_tail(None) is None


def test_session_id_short():
    assert textutil.session_id_short("abcdef1234567890") == "abcdef12"
    assert textutil.session_id_short("abc", n=6) == "abc"
    assert textutil.session_id_short(None) is None


# ---------------- T05 容错：unknown / missing / null / 缺 session_id ----------------

def test_unknown_hook_event_accepted_with_warning(caplog):
    with caplog.at_level(logging.WARNING, logger=EVENT_LOGGER):
        ev = normalize_hook({"session_id": "s", "hook_event_name": "SomethingNew"})
    assert ev.hook_event_name == "SomethingNew"  # 接受，不抛异常
    assert any("unknown hook_event_name" in r.message for r in caplog.records)


def test_missing_session_id_uses_transcript():
    ev = normalize_hook({"transcript_path": "/tmp/x.jsonl", "hook_event_name": "Stop"})
    assert ev.session_id == "/tmp/x.jsonl"


def test_missing_session_id_uses_cwd():
    ev = normalize_hook({"cwd": "/x/y", "hook_event_name": "Stop"})
    assert ev.session_id == "cwd:/x/y"


def test_missing_session_id_and_everything_no_crash():
    ev = normalize_hook({"hook_event_name": "Stop"})
    assert ev.session_id is None
    assert ev.cwd is None


def test_missing_optional_fields_no_crash():
    ev = normalize_hook({"hook_event_name": "Stop"})
    assert ev.tool_name is None
    assert ev.tool_input is None
    assert ev.cwd is None


def test_null_fields_no_crash():
    ev = normalize_hook({
        "session_id": "s", "hook_event_name": "Stop",
        "tool_name": None, "cwd": None, "tool_input": None,
    })
    assert ev.tool_name is None
    assert ev.cwd is None


def test_non_dict_payload_no_crash():
    ev = normalize_hook(None)
    assert ev.source == "hook"
    assert ev.session_id is None
    ev2 = normalize_hook("not a dict")
    assert ev2.source == "hook"


def test_missing_session_id_logs_warning(caplog):
    with caplog.at_level(logging.WARNING, logger=EVENT_LOGGER):
        normalize_hook({"cwd": "/x", "hook_event_name": "Stop"})
    assert any("missing session_id" in r.message for r in caplog.records)


# ---------------- normalize 分派 ----------------

def test_normalize_dispatch_statusline():
    ev = normalize({"session_id": "s"}, "statusline")
    assert ev.source == "statusline"


def test_normalize_dispatch_hook():
    ev = normalize({"session_id": "s", "hook_event_name": "Stop"}, "hook")
    assert ev.source == "hook"


def test_normalize_bad_source_raises():
    with pytest.raises(ValueError):
        normalize({}, "unknown")
