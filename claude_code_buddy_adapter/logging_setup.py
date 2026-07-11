"""四类日志框架：app / event / state / serial。

- app: 启动/配置/serial connect/disconnect/protocol error，默认 file + stdout。
- event: normalized ClaudeEvent，受 ``debug_event_log`` 控制；关闭时进 ring buffer。
- state: session state transition，落 state.log。
- serial: host/device frame，默认只进 ring buffer，不记完整敏感文本。

对齐系统设计 §可观测性与运维。
"""

from __future__ import annotations

import logging
import sys
from collections import deque
from pathlib import Path

from .config import AdapterConfig

LOGGERS = ("app", "event", "state", "serial")
DEFAULT_LOG_DIR = Path.home() / ".claude_code_buddy" / "logs"
_FMT = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")


class RingBufferHandler(logging.Handler):
    """内存 ring buffer，用于默认不落盘的 event/serial 日志。"""

    def __init__(self, capacity: int = 1024) -> None:
        super().__init__()
        self._records: deque[logging.LogRecord] = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        self._records.append(record)

    def snapshot(self) -> list[str]:
        return [self.format(r) for r in self._records]


def _make_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(f"claude_code_buddy_adapter.{name}")
    logger.setLevel(level)
    logger.propagate = False
    return logger


def get_logger(name: str = "app") -> logging.Logger:
    """获取指定类别的 logger（未配置时也可用，仅无 handler）。"""
    if name not in LOGGERS:
        raise ValueError(f"unknown logger category: {name}")
    return _make_logger(name)


def _stdout_handler() -> logging.StreamHandler:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(_FMT)
    return h


def _file_handler(path: Path) -> logging.FileHandler:
    h = logging.FileHandler(path, encoding="utf-8")
    h.setFormatter(_FMT)
    return h


def setup_logging(config: AdapterConfig) -> dict[str, logging.Logger]:
    """按 config 配置四类日志，返回 logger 字典。可重复调用（先清旧 handler）。"""
    log_dir = Path(config.log_dir) if config.log_dir else DEFAULT_LOG_DIR
    loggers: dict[str, logging.Logger] = {}

    for category in LOGGERS:
        logger = _make_logger(category)
        for h in list(logger.handlers):
            logger.removeHandler(h)

        if category == "app":
            logger.addHandler(_stdout_handler())
            try:
                log_dir.mkdir(parents=True, exist_ok=True)
                logger.addHandler(_file_handler(log_dir / "app.log"))
            except OSError:
                pass
            logger.setLevel(logging.INFO)

        elif category == "event":
            if config.debug_event_log:
                logger.addHandler(_stdout_handler())
                try:
                    log_dir.mkdir(parents=True, exist_ok=True)
                    logger.addHandler(_file_handler(log_dir / "event.log"))
                except OSError:
                    pass
                logger.setLevel(logging.DEBUG)
            else:
                rb = RingBufferHandler()
                rb.setFormatter(_FMT)
                logger.addHandler(rb)
                logger.setLevel(logging.INFO)

        elif category == "state":
            try:
                log_dir.mkdir(parents=True, exist_ok=True)
                logger.addHandler(_file_handler(log_dir / "state.log"))
            except OSError:
                logger.addHandler(_stdout_handler())
            logger.setLevel(logging.INFO)

        elif category == "serial":
            # 默认不记完整敏感文本：只进 ring buffer
            rb = RingBufferHandler()
            rb.setFormatter(_FMT)
            logger.addHandler(rb)
            logger.setLevel(logging.DEBUG)

        loggers[category] = logger

    return loggers
