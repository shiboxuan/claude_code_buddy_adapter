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
    """真实 pyserial 实现。按行读写 JSON Lines（\\n 结束）。

    断线检测：write/read 抛 OSError（USB 物理断开等）时关闭底层 serial 并置空，
    使 is_open 反映真实断开状态，供 bridge 触发重连（§6 断线恢复 / INT-5）。
    pyserial SerialException 继承自 OSError，故 except OSError 已覆盖。
    """

    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 1.0) -> None:
        self._port = port
        self._baudrate = baudrate
        self._timeout = timeout
        self._serial = None  # serial.Serial 实例

    def open(self) -> None:
        import serial

        self._close_serial()  # 先清理可能残留的旧连接
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
        try:
            self._serial.write(data)
        except OSError:
            # USB 断开等：关闭底层 serial 使 is_open=False，触发 bridge 重连；再上抛
            self._close_serial()
            raise

    def read_line(self) -> Optional[str]:
        if self._serial is None:
            return None
        try:
            line = self._serial.readline()
        except OSError:
            # USB 断开：标记断开（is_open=False）
            self._close_serial()
            return None
        if not line:
            return None  # timeout 返回空 bytes，不算断开
        return line.decode("utf-8", errors="replace")

    def _close_serial(self) -> None:
        """关闭并清空底层 serial（忽略已失效时的异常）。"""
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
            finally:
                self._serial = None

    def close(self) -> None:
        self._close_serial()
