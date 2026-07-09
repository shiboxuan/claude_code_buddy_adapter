"""ADP-P5: serial transport 集成测试（握手 / 收发 / 重连 / 坏包 / 心跳，用 fake）。"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from claude_code_buddy_adapter.claude.event_model import ClaudeEvent
from claude_code_buddy_adapter.claude.reducer import SessionState
from claude_code_buddy_adapter.config import AdapterConfig
from claude_code_buddy_adapter.device.bridge import SerialBridge
from claude_code_buddy_adapter.device.fake_transport import FakeSerialTransport
from claude_code_buddy_adapter.device.protocol import (
    PROTOCOL_VERSION,
    assert_within_max,
    make_hello,
)
from claude_code_buddy_adapter.device.transport import SerialTransport
from claude_code_buddy_adapter.metrics import Metrics
from claude_code_buddy_adapter.session.snapshot import DisplayComposer
from claude_code_buddy_adapter.session.store import SessionStore


def _hello(protocol: str = PROTOCOL_VERSION) -> dict:
    return make_hello(device="m5stick-s3", fw_version="0.1.0", features=["lcd"], muted=False) \
        if protocol == PROTOCOL_VERSION else {"type": "hello", "protocol": protocol,
                                              "device": "x", "fw_version": "0", "features": [], "muted": False}


def _make_bridge(heartbeat_interval: float = 99.0, reconnect_interval: float = 2.0):
    fake = FakeSerialTransport()
    store = SessionStore()
    config = AdapterConfig()
    composer = DisplayComposer(config)
    metrics = Metrics()
    bridge = SerialBridge(
        fake, store, composer, config, metrics=metrics,
        heartbeat_interval=heartbeat_interval, reconnect_interval=reconnect_interval,
    )
    return bridge, fake, store, metrics


def _working_event(session_id: str = "s1") -> ClaudeEvent:
    return ClaudeEvent(
        event_id="e", source="hook", received_at_ms=1000,
        session_id=session_id, hook_event_name="PreToolUse", raw={},
    )


# ---- T03 握手 ----

def test_handshake_success_sends_hello_ack_snapshot_config():
    bridge, fake, _, _ = _make_bridge()
    bridge.handle_frame(_hello())
    types = [f["type"] for f in fake.written]
    assert "hello_ack" in types
    assert "device_snapshot" in types
    assert "config" in types
    assert bridge.handshook is True
    ack = next(f for f in fake.written if f["type"] == "hello_ack")
    assert ack["ok"] is True


def test_handshake_version_mismatch_ok_false():
    bridge, fake, _, _ = _make_bridge()
    bridge.handle_frame(_hello(protocol="ccb-serial-v0"))
    ack = next(f for f in fake.written if f["type"] == "hello_ack")
    assert ack["ok"] is False
    assert bridge.handshook is False


def test_handshake_snapshot_under_1024():
    bridge, fake, _, _ = _make_bridge()
    bridge.handle_frame(_hello())
    snap = next(f for f in fake.written if f["type"] == "device_snapshot")
    assert_within_max(snap)  # 不抛


# ---- 收发 ----

def test_send_full_snapshot_reflects_store():
    bridge, fake, store, _ = _make_bridge()
    bridge.handle_frame(_hello())
    fake.written.clear()
    store.apply_event(_working_event("s1"))
    bridge.send_full_snapshot()
    snap = next(f for f in fake.written if f["type"] == "device_snapshot")
    assert snap["focus_session"]["id"] == "s1"


def test_ack_does_not_block_sending():
    bridge, fake, _, _ = _make_bridge()
    bridge.handle_frame(_hello())
    fake.written.clear()
    bridge.handle_frame({"type": "ack", "protocol": PROTOCOL_VERSION, "seq": 1, "uptime_ms": 100})
    bridge.send_full_snapshot()
    assert any(f["type"] == "device_snapshot" for f in fake.written)


# ---- 坏包 ----

def test_bad_frame_increments_parse_error_metric():
    bridge, _, _, metrics = _make_bridge()
    bridge.process_line("not json{")
    assert metrics.get("events_parse_error_total") == 1


def test_unknown_frame_type_ignored():
    bridge, _, _, _ = _make_bridge()
    bridge.handle_frame({"type": "mystery", "protocol": PROTOCOL_VERSION})  # 不抛


# ---- T04 重连 ----

def test_disconnect_clears_handshake_and_preserves_store():
    bridge, fake, store, _ = _make_bridge()
    bridge.handle_frame(_hello())
    store.apply_event(_working_event("s1"))
    fake.close()
    bridge._on_disconnect()
    assert bridge.handshook is False
    # store 未丢
    assert store.get("s1") is not None
    assert store.get("s1").state == SessionState.working


def test_reconnect_resends_full_snapshot():
    bridge, fake, _, _ = _make_bridge()
    bridge.handle_frame(_hello())
    fake.written.clear()
    fake.close()
    bridge._on_disconnect()
    assert bridge.handshook is False
    # 重连
    fake.open()
    bridge.handle_frame(_hello())  # 重新握手
    types = [f["type"] for f in fake.written]
    assert "hello_ack" in types
    assert "device_snapshot" in types  # 重发全量
    assert bridge.handshook is True


# ---- T05 心跳 ----

def test_heartbeat_sends_ping():
    bridge, fake, _, _ = _make_bridge(heartbeat_interval=0.1)
    bridge.start()
    try:
        bridge.handle_frame(_hello())
        fake.written.clear()
        time.sleep(0.35)  # > 2 个心跳周期
        types = [f["type"] for f in fake.written]
        assert "ping" in types
    finally:
        bridge.stop()


def test_no_heartbeat_before_handshake():
    bridge, fake, _, _ = _make_bridge(heartbeat_interval=0.1)
    bridge.start()
    try:
        time.sleep(0.3)
        # 未握手，不发 ping
        assert not any(f["type"] == "ping" for f in fake.written)
    finally:
        bridge.stop()


# ---- T02 真实 SerialTransport（mock pyserial）----

def test_serial_transport_write_and_read():
    with patch("serial.Serial") as mock_serial_cls:
        mock_serial = MagicMock()
        mock_serial.is_open = True
        mock_serial.readline.return_value = (
            b'{"type":"ping","protocol":"ccb-serial-v1","ts_ms":1}\n'
        )
        mock_serial_cls.return_value = mock_serial
        t = SerialTransport("/dev/ttyUSB0", 115200)
        t.open()
        assert t.is_open
        t.write_frame({"type": "ping", "protocol": "ccb-serial-v1", "ts_ms": 1})
        assert mock_serial.write.called
        line = t.read_line()
        assert "ping" in line
        t.close()


def test_serial_transport_read_none_when_closed():
    t = SerialTransport("/dev/ttyUSB0")
    assert t.read_line() is None
    assert t.is_open is False


# ---- T06 FakeSerialTransport ----

def test_fake_transport_write_and_inject():
    fake = FakeSerialTransport()
    fake.write_frame({"type": "ping", "protocol": PROTOCOL_VERSION, "ts_ms": 1})
    assert len(fake.written) == 1
    # host 读 device 注入
    assert fake.read_line() is None  # 无注入
    fake.inject({"type": "ack", "protocol": PROTOCOL_VERSION, "seq": 1, "uptime_ms": 0})
    line = fake.read_line()
    assert "ack" in line
    # device 侧收到 host 写入
    assert fake.device_rx_frames[0]["type"] == "ping"


def test_fake_transport_close_reopen():
    fake = FakeSerialTransport()
    assert fake.is_open
    fake.close()
    assert not fake.is_open
    fake.open()
    assert fake.is_open


# ---- T04 断线检测（INT-5）----


def test_serial_transport_write_oserror_marks_disconnected():
    """write 抛 OSError（USB 断开）-> 关闭底层，is_open=False。"""
    with patch("serial.Serial") as mock_serial_cls:
        mock_serial = MagicMock()
        mock_serial.is_open = True
        mock_serial.write.side_effect = OSError("device gone")
        mock_serial_cls.return_value = mock_serial
        t = SerialTransport("/dev/ttyUSB0", 115200)
        t.open()
        with pytest.raises(OSError):
            t.write_frame({"type": "ping", "protocol": PROTOCOL_VERSION, "ts_ms": 1})
        assert t.is_open is False  # 标记断开，触发 bridge 重连
        mock_serial.close.assert_called()  # 底层已关闭


def test_serial_transport_read_oserror_marks_disconnected():
    """readline 抛 OSError（USB 断开）-> read_line 返 None，is_open=False。"""
    with patch("serial.Serial") as mock_serial_cls:
        mock_serial = MagicMock()
        mock_serial.is_open = True
        mock_serial.readline.side_effect = OSError("device gone")
        mock_serial_cls.return_value = mock_serial
        t = SerialTransport("/dev/ttyUSB0", 115200)
        t.open()
        assert t.read_line() is None
        assert t.is_open is False  # 标记断开


# ---- T04 重连循环（INT-5）----


def test_reconnect_loop_rebuilds_on_disconnect():
    """断开后 reconnect 线程用 factory 重建 transport；重连后 hello 恢复连接。"""
    bridge, fake, _, metrics = _make_bridge(reconnect_interval=0.05)

    def factory():
        fake.open()  # 模拟端口回来
        return fake

    bridge._transport_factory = factory
    bridge.start()
    try:
        bridge.handle_frame(_hello())
        assert bridge.is_device_connected
        fake.close()  # 模拟 USB 断开
        time.sleep(0.3)  # 等重连线程（>多个 reconnect_interval）
        assert fake.is_open  # factory 重新 open
        assert metrics.get("serial_reconnect_total") >= 1
        # 重连后 firmware 主动发 hello -> 重新握手
        bridge.handle_frame(_hello())
        assert bridge.is_device_connected
    finally:
        bridge.stop()


def test_device_connected_gauge_tracks_handshake():
    """device_connected gauge：初始 0，握手 -> 1，断开 -> 0。"""
    bridge, fake, _, metrics = _make_bridge()
    assert metrics.get("device_connected") == 0
    bridge.handle_frame(_hello())
    assert metrics.get("device_connected") == 1
    fake.close()
    bridge._on_disconnect()
    assert metrics.get("device_connected") == 0
