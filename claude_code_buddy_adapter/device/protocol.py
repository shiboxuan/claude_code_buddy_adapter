"""serial 协议帧：模型、序列化、seq、限长、error code。

对齐 protocol §4（帧）、§4.3（seq/ack）、§5.7（error code）、§2.5（≤1024 bytes）。
帧用 dict 表示，JSON Lines 序列化（单行 ``\\n`` 结束，行内无换行）。
13 种消息：host→device 带 seq（hello_ack/device_snapshot/session_snapshot/alert/config）、
host→device 不带 seq（ping）；device→host（hello/ack/button/mute/page/error/pong）。
"""

from __future__ import annotations

import json
import threading
from enum import Enum
from typing import Any, Optional

PROTOCOL_VERSION = "ccb-serial-v1"
MAX_FRAME_BYTES = 1024

# 带 seq 的关键帧（§4.3/§4.7）
KEY_FRAMES = frozenset({
    "hello_ack", "device_snapshot", "session_snapshot", "alert", "config",
})


class ErrorCode(str, Enum):
    """§5.7 错误码。"""

    json_parse_error = "json_parse_error"
    missing_required_field = "missing_required_field"
    unknown_message_type = "unknown_message_type"
    frame_too_large = "frame_too_large"
    version_mismatch = "version_mismatch"
    internal_error = "internal_error"


class FrameTooLargeError(Exception):
    def __init__(self, size: int, limit: int) -> None:
        super().__init__(f"frame {size}B exceeds limit {limit}B")
        self.size = size
        self.limit = limit


class FrameParseError(Exception):
    """JSON Lines 坏行解析错误。"""


class SeqCounter:
    """uint32 递增回绕，从 1 开始，跳过 0。线程安全。"""

    def __init__(self, start: int = 1) -> None:
        self._seq = start
        self._lock = threading.Lock()

    def next(self) -> int:
        with self._lock:
            cur = self._seq
            nxt = (self._seq + 1) & 0xFFFFFFFF
            if nxt == 0:
                nxt = 1  # 跳过 0（0 表示无 seq）
            self._seq = nxt
            return cur


def _base(frame_type: str, **fields: Any) -> dict[str, Any]:
    return {"type": frame_type, "protocol": PROTOCOL_VERSION, **fields}


# ---- host→device 帧构造 ----

def make_hello_ack(adapter_version: str, seq: int, ok: bool) -> dict:
    return _base("hello_ack", adapter_version=adapter_version, seq=seq, ok=ok)


def make_device_snapshot(
    seq: int, global_state: str, color: str,
    focus_session: Optional[dict] = None, counts: Optional[dict] = None,
    alert: Optional[dict] = None,
) -> dict:
    return _base(
        "device_snapshot", seq=seq, global_state=global_state, color=color,
        focus_session=focus_session, counts=counts or {}, alert=alert,
    )


def make_session_snapshot(seq: int, session: dict) -> dict:
    return _base("session_snapshot", seq=seq, session=session)


def make_alert(seq: int, kind: str, sound: bool, session_id: Optional[str] = None) -> dict:
    d = _base("alert", seq=seq, kind=kind, sound=sound)
    if session_id is not None:
        d["session_id"] = session_id
    return d


def make_config(
    seq: int, sound_enabled: Optional[bool] = None, privacy_mode: Optional[bool] = None,
    brightness: Optional[int] = None, done_ttl_ms: Optional[int] = None,
) -> dict:
    d = _base("config", seq=seq)
    if sound_enabled is not None:
        d["sound_enabled"] = sound_enabled
    if privacy_mode is not None:
        d["privacy_mode"] = privacy_mode
    if brightness is not None:
        d["brightness"] = brightness
    if done_ttl_ms is not None:
        d["done_ttl_ms"] = done_ttl_ms
    return d


def make_ping(ts_ms: int) -> dict:
    return _base("ping", ts_ms=ts_ms)


# ---- device→host 帧构造（解析/测试用） ----

def make_pong(ts_ms: int, echo_ts_ms: int) -> dict:
    return _base("pong", ts_ms=ts_ms, echo_ts_ms=echo_ts_ms)


def make_ack(seq: int, uptime_ms: int) -> dict:
    return _base("ack", seq=seq, uptime_ms=uptime_ms)


def make_error(code: str, uptime_ms: int, message: Optional[str] = None) -> dict:
    d = _base("error", code=code, uptime_ms=uptime_ms)
    if message:
        d["message"] = message
    return d


def make_hello(device: str, fw_version: str, features: list[str], muted: bool) -> dict:
    return _base("hello", device=device, fw_version=fw_version, features=features, muted=muted)


def make_button(button: str, action: str, page: str, muted: bool, uptime_ms: int) -> dict:
    return _base("button", button=button, action=action, page=page, muted=muted, uptime_ms=uptime_ms)


def make_mute(muted: bool, uptime_ms: int) -> dict:
    return _base("mute", muted=muted, uptime_ms=uptime_ms)


def make_page(page: str, muted: bool, uptime_ms: int, prev_page: Optional[str] = None) -> dict:
    d = _base("page", page=page, muted=muted, uptime_ms=uptime_ms)
    if prev_page is not None:
        d["prev_page"] = prev_page
    return d


# ---- 序列化 / 解析 / 限长 ----

def serialize(frame: dict) -> bytes:
    """序列化为 JSON Lines bytes（单行 ``\\n`` 结束）。"""
    line = json.dumps(frame, ensure_ascii=False, separators=(",", ":"))
    return (line + "\n").encode("utf-8")


def parse_frame(line: str) -> dict:
    """解析一行 JSON 为 dict。坏行抛 FrameParseError。"""
    line = line.strip()
    if not line:
        raise FrameParseError("empty line")
    try:
        obj = json.loads(line)
    except json.JSONDecodeError as e:
        raise FrameParseError(str(e)) from e
    if not isinstance(obj, dict):
        raise FrameParseError("frame is not an object")
    return obj


def frame_size(frame: dict) -> int:
    return len(serialize(frame))


def assert_within_max(frame: dict, max_bytes: int = MAX_FRAME_BYTES) -> None:
    """超限抛 FrameTooLargeError（§2.5 ≤1024 bytes）。"""
    size = frame_size(frame)
    if size > max_bytes:
        raise FrameTooLargeError(size, max_bytes)
