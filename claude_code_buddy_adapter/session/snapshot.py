"""DisplayComposer：session/global state → firmware 可显示短文本 + 帧构造。

对齐 protocol §2.5（限长：title≤20、line1/line2≤28，像素等价宽度中文按 2 宽）、
§4.5.2（device_snapshot）、§4.5.3（session_snapshot）、§5.3（color）。
privacy_mode=true 隐藏 cwd/命令参数。
"""

from __future__ import annotations

from typing import Optional

from .. import PROTOCOL_VERSION
from ..claude.reducer import Session, SessionState
from ..claude.textutil import (
    LINE_MAX_WIDTH,
    TITLE_MAX_WIDTH,
    cwd_tail,
    repo_basename,
    session_id_short,
    truncate_width,
)
from ..config import AdapterConfig
from .arbiter import compute_counts, compute_global_state, select_focus

# session state → color（§5.3）
STATE_COLOR: dict[SessionState, str] = {
    SessionState.unknown: "gray",
    SessionState.idle: "green",
    SessionState.working: "red",
    SessionState.attention: "yellow",
    SessionState.plan: "yellow",
    SessionState.done_recent: "blue",
    SessionState.error: "red_flash",
    SessionState.ended: "gray",
}

# global_state → color（§5.2/§5.3）
GLOBAL_COLOR: dict[str, str] = {
    "device_disconnected": "gray",
    "adapter_connected": "green",
    "idle": "green",
    "working": "red",
    "attention": "yellow",
    "error": "red_flash",
}


class DisplayComposer:
    def __init__(self, config: AdapterConfig) -> None:
        self._privacy_mode = config.privacy_mode

    # ---- §4.5.2 device_snapshot ----
    def compose_device_snapshot(
        self, sessions: list[Session], device_connected: bool, seq: int,
        now_ms: int, alert: Optional[dict] = None,
    ) -> dict:
        global_state = compute_global_state(sessions, device_connected)
        focus = select_focus(sessions)
        return {
            "type": "device_snapshot",
            "protocol": PROTOCOL_VERSION,
            "seq": seq,
            "global_state": global_state,
            "color": GLOBAL_COLOR.get(global_state, "gray"),
            "focus_session": self.compose_focus_session(focus) if focus else None,
            "counts": compute_counts(sessions),
            "alert": alert,
        }

    def compose_focus_session(self, session: Session) -> dict:
        """§4.5.2 focus_session 子对象。"""
        title, line1, line2 = self._compose_text(session)
        return {
            "id": session.session_id,
            "label": session_id_short(session.session_id) or session.session_id,
            "repo": self._repo(session),
            "cwd": self._cwd(session),
            "state": session.state.value,
            "title": title,
            "line1": line1,
            "line2": line2,
            "progress": session.progress,
        }

    # ---- §4.5.3 session_snapshot ----
    def compose_session_snapshot(self, session: Session, seq: int, now_ms: int) -> dict:
        return {
            "type": "session_snapshot",
            "protocol": PROTOCOL_VERSION,
            "seq": seq,
            "session": self.compose_session_detail(session, now_ms),
        }

    def compose_session_detail(self, session: Session, now_ms: int) -> dict:
        """§4.5.3 session 子对象。"""
        title, line1, line2 = self._compose_text(session)
        age_sec = max(0, (now_ms - (session.updated_at_ms or now_ms)) // 1000)
        return {
            "session_id_short": session_id_short(session.session_id) or session.session_id,
            "repo": self._repo(session),
            "cwd_label": self._cwd(session),
            "state": session.state.value,
            "color": STATE_COLOR.get(session.state, "gray"),
            "title": title,
            "line1": line1,
            "line2": line2,
            "progress": session.progress,
            "age_sec": age_sec,
        }

    # ---- 文本生成（按状态）----
    def _compose_text(self, session: Session) -> tuple[str, str, str]:
        st = session.state
        priv = self._privacy_mode
        repo = self._repo(session) or ""

        if st == SessionState.working:
            title = "Working"
            if priv:
                line1, line2 = repo or "…", ""
            else:
                line1 = session.last_tool or repo or "…"
                line2 = session.last_command or ""
        elif st in (SessionState.attention, SessionState.plan):
            title = "Attention" if st == SessionState.attention else "Plan"
            line1 = session.last_prompt or session.plan_summary or ""
            line2 = "" if priv else (session.reason or "")
        elif st == SessionState.error:
            title, line1, line2 = "Error", session.error_summary or "error", ""
        elif st == SessionState.done_recent:
            title, line1, line2 = "Done", repo, ""
        elif st == SessionState.ended:
            title, line1, line2 = "Ended", repo, ""
        else:  # idle / unknown
            title = "Idle"
            line1 = repo
            line2 = "" if priv else (session.model or "")

        return (
            truncate_width(title, TITLE_MAX_WIDTH),
            truncate_width(line1, LINE_MAX_WIDTH),
            truncate_width(line2, LINE_MAX_WIDTH),
        )

    def _repo(self, session: Session) -> Optional[str]:
        return repo_basename(session.repo_name) if session.repo_name else None

    def _cwd(self, session: Session) -> Optional[str]:
        if self._privacy_mode:
            return None  # privacy_mode 隐藏路径
        return cwd_tail(session.cwd) if session.cwd else None
