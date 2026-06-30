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
