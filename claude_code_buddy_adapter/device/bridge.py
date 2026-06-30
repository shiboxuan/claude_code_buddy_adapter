"""SerialBridge：握手 + 重连 + 心跳，连接 store/composer/alert/transport/metrics。

- 握手（§4.4）：收 hello → 校验 protocol → 发 hello_ack + 全量 device_snapshot + config。
- 重连：断开检测（is_open=False）→ 停止发送、保留 store；重连后收到 hello 重新握手 + 重发全量。
- 心跳（§4.3）：周期发 ping；未收 ack 不阻塞，仅记 snapshot_send_failure_total。
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from .. import __version__ as ADAPTER_VERSION
from .alert import AlertTracker
from .protocol import (
    PROTOCOL_VERSION,
    FrameParseError,
    SeqCounter,
    assert_within_max,
    make_config,
    make_hello_ack,
    make_ping,
    parse_frame,
)


class SerialBridge:
    def __init__(
        self,
        transport,
        store,
        composer,
        config,
        metrics=None,
        alert_tracker: Optional[AlertTracker] = None,
        reconnect_interval: float = 5.0,
        heartbeat_interval: float = 10.0,
        poll_interval: float = 0.05,
    ) -> None:
        self._transport = transport
        self._store = store
        self._composer = composer
        self._config = config
        self._metrics = metrics
        self._alert = alert_tracker or AlertTracker(sound_enabled=config.sound_enabled_default)
        self._seq = SeqCounter()
        self._reconnect_interval = reconnect_interval
        self._heartbeat_interval = heartbeat_interval
        self._poll_interval = poll_interval
        self._stop = threading.Event()
        self._lock = threading.RLock()  # 可重入：_handle_hello 内调 send_full_snapshot
        self._read_thread: Optional[threading.Thread] = None
        self._hb_thread: Optional[threading.Thread] = None
        self._handshook = False

    # ---- 生命周期 ----
    def start(self) -> None:
        self._stop.clear()
        if not self._transport.is_open:
            self._transport.open()
        self._read_thread = threading.Thread(
            target=self._read_loop, daemon=True, name="buddy-serial-read")
        self._read_thread.start()
        self._hb_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True, name="buddy-serial-hb")
        self._hb_thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._transport.close()
        except Exception:
            pass
        if self._read_thread is not None:
            self._read_thread.join(timeout=2)
        if self._hb_thread is not None:
            self._hb_thread.join(timeout=2)

    @property
    def handshook(self) -> bool:
        return self._handshook

    @property
    def is_device_connected(self) -> bool:
        return self._handshook and self._transport.is_open

    # ---- 读循环 ----
    def _read_loop(self) -> None:
        while not self._stop.is_set():
            if not self._transport.is_open:
                self._on_disconnect()
                if self._stop.wait(self._poll_interval):
                    break
                continue
            line = self._transport.read_line()
            if line is None:
                if self._stop.wait(self._poll_interval):
                    break
                continue
            self.process_line(line)

    def process_line(self, line: str) -> None:
        """解析一行并处理；坏行丢弃并记指标。"""
        try:
            frame = parse_frame(line)
        except FrameParseError:
            self._inc("events_parse_error_total")
            return
        self.handle_frame(frame)

    def handle_frame(self, frame: dict) -> None:
        ftype = frame.get("type")
        if ftype == "hello":
            self._handle_hello(frame)
        elif ftype in ("ack", "pong"):
            pass  # ack 不阻塞（§4.3）
        elif ftype in ("button", "mute", "page", "error"):
            self._handle_device_event(frame)
        # 未知类型忽略（§6）

    def _on_disconnect(self) -> None:
        with self._lock:
            self._handshook = False
            self._alert.reset()  # 重连后 connected 可再发

    # ---- 握手（§4.4）----
    def _handle_hello(self, frame: dict) -> None:
        ok = frame.get("protocol") == PROTOCOL_VERSION
        with self._lock:
            self._send(make_hello_ack(ADAPTER_VERSION, self._seq.next(), ok))
            if ok:
                self._handshook = True
                alert = self._alert.on_connect(self._seq.next())
                self.send_full_snapshot(alert=alert)
                self._send(make_config(
                    self._seq.next(),
                    sound_enabled=self._config.sound_enabled_default,
                    privacy_mode=self._config.privacy_mode,
                    done_ttl_ms=self._config.done_ttl_ms,
                ))

    def send_full_snapshot(self, now_ms: Optional[int] = None, alert: Optional[dict] = None) -> None:
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        sessions = self._store.active()
        with self._lock:
            seq = self._seq.next()
            frame = self._composer.compose_device_snapshot(
                sessions, device_connected=True, seq=seq, now_ms=now, alert=alert
            )
        self._send(frame)

    def handle_state_change(self, prev, updated) -> None:
        """状态变化时触发 alert 边沿 + 全量 snapshot（供 HTTP receiver 调用）。"""
        if prev is not None and updated is not None and prev.state != updated.state:
            alert = self._alert.on_session_change(
                updated.session_id, prev.state, updated.state, self._seq.next()
            )
            if alert:
                self._send(alert)
        self.send_full_snapshot()

    # ---- 心跳（§4.3）----
    def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            if self._stop.wait(self._heartbeat_interval):
                break
            with self._lock:
                if self._handshook and self._transport.is_open:
                    self._send(make_ping(int(time.time() * 1000)))

    # ---- 发送 ----
    def _send(self, frame: dict) -> None:
        try:
            assert_within_max(frame)
            self._transport.write_frame(frame)
            self._inc("snapshot_sent_total")
        except Exception:
            self._inc("snapshot_send_failure_total")

    def _inc(self, name: str) -> None:
        if self._metrics is not None:
            try:
                self._metrics.inc(name)
            except KeyError:
                pass

    def _handle_device_event(self, frame: dict) -> None:
        # MVP：button/mute/page/error 仅记录，不控制 Claude Code
        pass
