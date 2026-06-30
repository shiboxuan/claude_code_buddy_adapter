"""SerialDiscovery：枚举本机 serial 端口，按 vid/pid 或设备名匹配 StickS3。

M5Stack StickS3 走 Espressif USB CDC，VID 默认 0x303a；也可按设备名（m5/stick/esp）匹配。
``AdapterConfig.serial_port`` 手动指定时跳过自动发现。
"""

from __future__ import annotations

from typing import Optional

# M5Stack StickS3（Espressif USB CDC）默认 VID
DEFAULT_VID = 0x303A
DEFAULT_NAME_PATTERNS = ("m5", "stick", "esp", "m5stack")


class SerialDiscovery:
    def __init__(
        self,
        vid: Optional[int] = DEFAULT_VID,
        pid: Optional[int] = None,
        name_patterns: tuple[str, ...] = DEFAULT_NAME_PATTERNS,
    ) -> None:
        self._vid = vid
        self._pid = pid
        self._name_patterns = tuple(p.lower() for p in name_patterns)

    def list_ports(self) -> list[str]:
        from serial.tools import list_ports

        return [p.device for p in list_ports.comports()]

    def find(self) -> Optional[str]:
        """返回第一个匹配 StickS3 的端口，无则 None。"""
        from serial.tools import list_ports

        for p in list_ports.comports():
            if self._match(p):
                return p.device
        return None

    def _match(self, port) -> bool:
        # vid/pid 匹配
        if self._vid is not None and port.vid == self._vid:
            if self._pid is None or port.pid == self._pid:
                return True
        # 设备名匹配
        name = (port.product or port.description or port.device or "").lower()
        return any(pat in name for pat in self._name_patterns)
