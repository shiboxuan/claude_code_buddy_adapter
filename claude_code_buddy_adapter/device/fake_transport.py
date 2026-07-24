"""FakeSerialTransport：无硬件环境的内存队列模拟 device。

- host 调 ``write_frame`` → 帧进 device_rx 队列（可由 ``device_rx_frames`` 读取）。
- 测试调 ``inject`` → 帧进 host_rx 队列，host ``read_line`` 读到。
- ``close`` 模拟断开（is_open=False），``open`` 模拟重连。
"""

from __future__ import annotations

import json
import queue
from typing import Optional

from .protocol import serialize


class FakeSerialTransport:
    def __init__(self) -> None:
        self._host_rx: "queue.Queue[str]" = queue.Queue()  # host 读取（device 注入）
        self._device_rx: "queue.Queue[dict]" = queue.Queue()  # device 读取（host 写入）
        self._open = True
        self.written: list[dict] = []  # host 写入的全部帧（按序）

    @property
    def is_open(self) -> bool:
        return self._open

    def open(self) -> None:
        self._open = True

    def write_frame(self, frame: dict) -> None:
        self.written.append(frame)
        self._device_rx.put(frame)

    def read_line(self) -> Optional[str]:
        try:
            frame = self._host_rx.get_nowait()
        except queue.Empty:
            return None
        # 模拟 device 发出的一行 JSON Lines
        return serialize(frame).decode("utf-8")

    def inject(self, frame: dict) -> None:
        """device 注入一帧（hello/ack/button/mute/page/error/pong），host 将读到。"""
        self._host_rx.put(frame)

    def close(self) -> None:
        self._open = False

    @property
    def device_rx_frames(self) -> list[dict]:
        """取出 device 侧收到的全部帧（清空队列）。"""
        out: list[dict] = []
        while True:
            try:
                out.append(self._device_rx.get_nowait())
            except queue.Empty:
                break
        return out


class NullTransport:
    """占位 transport：表示"无设备，等待 reconnect loop 发现真设备"。

    is_open 恒 False：bridge._reconnect_loop 据此判定需要重新 discover/open，
    不会像 FakeSerialTransport（is_open=True）那样让重连循环误判"端口仍在"而跳过。
    - open() 是 no-op（不抛），让 bridge.start() 的初始 ``if not is_open: open()`` 不炸；
    - write_frame 抛 ConnectionError，与 SerialTransport 未 open 时一致，
      由 bridge._send 的 try/except 兜住并计 snapshot_send_failure_total；
    - read_line 返 None。
    """

    @property
    def is_open(self) -> bool:
        return False

    def open(self) -> None:
        pass  # no-op：保持未连，reconnect_loop 负责 discover 真设备

    def write_frame(self, frame: dict) -> None:
        raise ConnectionError("null transport: not connected")

    def read_line(self) -> Optional[str]:
        return None

    def close(self) -> None:
        pass
