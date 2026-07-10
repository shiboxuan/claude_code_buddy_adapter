"""ADP-P9-T03: 用 tests/fixtures/real/ 真实格式 payload 校准 normalizer。

验证 normalizer 对 protocol §3.2/§3.3 全字段、全 14 hook_event_name + statusLine
不报错，且 event-specific 字段（tool_name/message/reason/agent_id/task_id/error/
model/repo/cost/context）通过 ClaudeEvent property 正确提取。

fixture 来源：基于 protocol §3.2/§3.3/§5.6 字段契约构造的真实格式 payload
（字段结构与 Claude Code 真实发出一致）；线上真实触发采集可用 debug/capture_payloads.py。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_code_buddy_adapter.claude.normalizer import (
    KNOWN_HOOK_EVENTS,
    normalize_hook,
    normalize_statusline,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "real"


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


HOOK_FIXTURES = [
    ("hook_session_start.json", "SessionStart"),
    ("hook_user_prompt_submit.json", "UserPromptSubmit"),
    ("hook_pre_tool_use.json", "PreToolUse"),
    ("hook_post_tool_use.json", "PostToolUse"),
    ("hook_message_display.json", "MessageDisplay"),
    ("hook_subagent_start.json", "SubagentStart"),
    ("hook_task_created.json", "TaskCreated"),
    ("hook_notification.json", "Notification"),
    ("hook_permission_request.json", "PermissionRequest"),
    ("hook_elicitation.json", "Elicitation"),
    ("hook_elicitation_result.json", "ElicitationResult"),
    ("hook_stop.json", "Stop"),
    ("hook_stop_failure.json", "StopFailure"),
    ("hook_session_end.json", "SessionEnd"),
]


@pytest.mark.parametrize("fname,event", HOOK_FIXTURES)
def test_real_hook_normalize_no_error(fname, event):
    """每个 hook_event_name 真实格式 payload 规范化不抛异常、字段不丢。"""
    payload = _load(fname)
    ev = normalize_hook(payload)
    assert ev.source == "hook"
    assert ev.hook_event_name == event
    assert ev.session_id  # fallback 也不丢
    assert event in KNOWN_HOOK_EVENTS


def test_real_statusline_normalize_no_error():
    payload = _load("statusline_real.json")
    ev = normalize_statusline(payload)
    assert ev.source == "statusline"
    assert ev.session_id == payload["session_id"]
    assert ev.hook_event_name is None


def test_real_statusline_extracts_nested_fields():
    """statusLine 嵌套字段（model/workspace/cost/context_window）通过 property 提取。"""
    payload = _load("statusline_real.json")
    ev = normalize_statusline(payload)
    assert ev.model_id == "claude-opus-4-8"
    assert ev.model_display_name == "Opus 4.8"
    assert ev.repo_name == "claude_code_buddy_adapter"
    assert ev.cost_usd == 0.42
    assert ev.cost_duration_ms == 120000
    assert ev.context_used_percentage == 35.5


def test_real_hook_extracts_event_specific_fields():
    """hook event-specific 字段通过 ClaudeEvent property 正确提取。"""
    # PreToolUse: tool_name + tool_input
    ev = normalize_hook(_load("hook_pre_tool_use.json"))
    assert ev.tool_name == "Bash"
    assert ev.tool_input == {"command": "pytest -q"}
    # Notification: message + notification_type
    ev = normalize_hook(_load("hook_notification.json"))
    assert ev.message == "需要用户确认"
    assert ev.notification_type == "permission"
    # PermissionRequest: reason
    ev = normalize_hook(_load("hook_permission_request.json"))
    assert ev.reason == "Bash: rm -rf build/"
    # SubagentStart: agent_id
    ev = normalize_hook(_load("hook_subagent_start.json"))
    assert ev.agent_id == "subagent-001"
    # TaskCreated: task_id + title
    ev = normalize_hook(_load("hook_task_created.json"))
    assert ev.task_id == "task-007"
    assert ev.title == "校准 normalizer"
    # StopFailure: error
    ev = normalize_hook(_load("hook_stop_failure.json"))
    assert ev.error == "API rate limit exceeded"
    # MessageDisplay: message
    ev = normalize_hook(_load("hook_message_display.json"))
    assert ev.message == "正在分析 install-claude 的合并逻辑"


def test_real_all_fixtures_cover_14_known_events():
    """real fixtures 覆盖 protocol §5.6 全部 14 个 hook_event_name。"""
    events = {e for _, e in HOOK_FIXTURES}
    assert events == set(KNOWN_HOOK_EVENTS)
