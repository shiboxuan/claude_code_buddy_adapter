"""ClaudeEvent 数据模型：normalizer 输出的统一事件表示。

字段对齐 docs/claude_code_buddy/claude-code-buddy-system-design.md §数据模型 ClaudeEvent
（event_id / source / received_at_ms / session_id / hook_event_name / cwd / raw）。

event-specific 字段（tool_name / message / title / error / agent_id …）保留在 ``raw`` 中，
通过 property 访问器暴露，便于 reducer / snapshot 读取而不污染顶层标准字段。
时间戳统一用 ``received_at_ms``（epoch 毫秒，遵循 protocol §2.4 ``*_ms`` 约定）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(kw_only=True, slots=True)
class ClaudeEvent:
    """normalized Claude Code 事件。"""

    event_id: str
    source: str  # "statusline" | "hook"
    received_at_ms: int
    session_id: Optional[str] = None
    hook_event_name: Optional[str] = None
    cwd: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)

    # ---- hook event-specific 访问器（从 raw 提取） ----
    @property
    def transcript_path(self) -> Optional[str]:
        return self.raw.get("transcript_path")

    @property
    def tool_name(self) -> Optional[str]:
        return self.raw.get("tool_name")

    @property
    def tool_input(self) -> Any:
        return self.raw.get("tool_input")

    @property
    def message(self) -> Optional[str]:
        return self.raw.get("message")

    @property
    def title(self) -> Optional[str]:
        return self.raw.get("title")

    @property
    def notification_type(self) -> Optional[str]:
        return self.raw.get("notification_type")

    @property
    def reason(self) -> Optional[str]:
        return self.raw.get("reason")

    @property
    def agent_id(self) -> Optional[str]:
        return self.raw.get("agent_id")

    @property
    def task_id(self) -> Optional[str]:
        return self.raw.get("task_id")

    @property
    def file_path(self) -> Optional[str]:
        return self.raw.get("file_path")

    @property
    def error(self) -> Optional[str]:
        return self.raw.get("error")

    # ---- statusLine 专属访问器（嵌套容器安全提取） ----
    @property
    def model_id(self) -> Optional[str]:
        model = self.raw.get("model")
        if isinstance(model, dict):
            return model.get("id")
        return None

    @property
    def model_display_name(self) -> Optional[str]:
        model = self.raw.get("model")
        if isinstance(model, dict):
            return model.get("display_name")
        return None

    @property
    def repo_name(self) -> Optional[str]:
        ws = self.raw.get("workspace")
        if isinstance(ws, dict):
            repo = ws.get("repo")
            if isinstance(repo, dict):
                return repo.get("name")
        return None

    @property
    def cost_usd(self) -> Optional[float]:
        cost = self.raw.get("cost")
        if isinstance(cost, dict):
            return cost.get("total_cost_usd")
        return None

    @property
    def cost_duration_ms(self) -> Optional[int]:
        cost = self.raw.get("cost")
        if isinstance(cost, dict):
            return cost.get("total_duration_ms")
        return None

    @property
    def context_used_percentage(self) -> Optional[float]:
        cw = self.raw.get("context_window")
        if isinstance(cw, dict):
            return cw.get("used_percentage")
        return None

    def __repr__(self) -> str:
        return (
            f"ClaudeEvent(event_id={self.event_id!r}, source={self.source!r}, "
            f"hook_event_name={self.hook_event_name!r}, session_id={self.session_id!r})"
        )
