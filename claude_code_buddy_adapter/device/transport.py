"""serial transport 抽象 + 真实 pyserial 实现。

Transport 抽象定义读写 JSON Lines 帧的接口；SerialTransport 用 pyserial 实现。
坏行（解析失败）由调用方（bridge）丢弃并记指标，transport 只负责按行读写。
"""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from .protocol import (
    MAX_FRAME_BYTES,
    FrameTooLargeError,
    assert_within_max,
    serialize,
)


@runtime_checkable
class Transport(Protocol):
    """transport 抽象：读写 JSON Lines 帧。"""

    @property
    def is_open(self) -> bool: ...

    def open(self) -> None: ...

    def write_frame(self, frame: dict) -> None: ...

    def read_line(self) -> Optional[str]:
        """读一行；无数据或断开返回 None。"""
        ...

    def close(self) -> None: ...


class SerialTransport:
    """真实 pyserial 实现。按行读写 JSON Lines（\\n 结束）。"""

    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 1.0) -> None:
        self._port = port
        self._baudrate = baudrate
        self._timeout = timeout
        self._serial = None  # serial.Serial 实例

    def open(self) -> None:
        import serial

        self._serial = serial.Serial(
            self._port, self._baudrate, timeout=self._timeout
        )

    @property
    def is_open(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def write_frame(self, frame: dict) -> None:
        assert_within_max(frame)  # 发送前截断/检查（§2.5）
        if self._serial is None:
            raise ConnectionError("transport not open")
        data = serialize(frame)
        self._serial.write(data)

    def read_line(self) -> Optional[str]:
        if self._serial is None:
            return None
        try:
            line = self._serial.readline()
        except OSError:
            return None
        if not line:
            return None
        return line.decode("utf-8", errors="replace")

    def close(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            finally:
                self._serial = None
