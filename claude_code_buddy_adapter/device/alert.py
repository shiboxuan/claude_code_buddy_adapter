"""alert 边沿触发（protocol §5.8 + BR-009）。

- connected：不重复（仅连接边沿一次）。
- attention：每 session 每次 attention 边沿一次（进入 attention 触发，离开后重置可再次触发）。
- done：可配置关闭（``done_alert_enabled``）。
- error：每错误边沿一次。
返回独立 ``alert`` 帧（§4.5.4），由调用方分配 seq 并发送。
"""

from __future__ import annotations

from typing import Optional

from ..claude.reducer import SessionState
from .protocol import make_alert


class AlertTracker:
    def __init__(
        self, sound_enabled: bool = True, done_alert_enabled: bool = True
    ) -> None:
        self._sound_enabled = sound_enabled
        self._done_alert_enabled = done_alert_enabled
        self._connected_sent = False
        self._attention_alerted: set[str] = set()
        self._error_alerted: set[str] = set()

    def on_connect(self, seq: int) -> Optional[dict]:
        """设备连接边沿：首次返回 connected alert，之后不重复。"""
        if self._connected_sent:
            return None
        self._connected_sent = True
        return make_alert(seq=seq, kind="connected", sound=self._sound_enabled)

    def on_session_change(
        self, session_id: str, prev_state: SessionState, new_state: SessionState, seq: int
    ) -> Optional[dict]:
        """session 状态变化边沿：进入 attention/error/done 时返回对应 alert。

        连续相同状态不重复；离开 attention/error 后重置，下次进入再发。
        """
        # attention 边沿
        if new_state == SessionState.attention and prev_state != SessionState.attention:
            if session_id not in self._attention_alerted:
                self._attention_alerted.add(session_id)
                return make_alert(seq=seq, kind="attention", sound=self._sound_enabled, session_id=session_id)
        if new_state != SessionState.attention:
            self._attention_alerted.discard(session_id)  # 离开 → 可再次触发

        # error 边沿
        if new_state == SessionState.error and prev_state != SessionState.error:
            if session_id not in self._error_alerted:
                self._error_alerted.add(session_id)
                return make_alert(seq=seq, kind="error", sound=self._sound_enabled, session_id=session_id)
        if new_state != SessionState.error:
            self._error_alerted.discard(session_id)

        # done 边沿（可配置关闭）
        if (
            new_state == SessionState.done_recent
            and prev_state != SessionState.done_recent
            and self._done_alert_enabled
        ):
            return make_alert(seq=seq, kind="done", sound=self._sound_enabled, session_id=session_id)

        return None

    def reset(self) -> None:
        """重连后重置连接态（connected 可再发一次），保留 session 边沿状态。"""
        self._connected_sent = False
