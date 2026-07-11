"""Adapter 配置：默认值、配置文件（TOML/JSON）加载、环境变量覆盖。

字段对齐系统设计 §数据模型 AdapterConfig。
"""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Optional


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass
class AdapterConfig:
    """本机 adapter 配置。所有字段均可被配置文件与环境变量覆盖。"""

    # HTTP receiver（只绑定 loopback，见 protocol §3.1）
    http_host: str = "127.0.0.1"
    http_port: int = 8765
    # USB serial
    serial_port: Optional[str] = None
    baudrate: int = 115200
    # 行为开关
    privacy_mode: bool = False
    sound_enabled_default: bool = True
    done_ttl_ms: int = 5000
    session_ttl_ms: int = 300_000  # attention stale 超时（BR-007/BR-008）
    # feature flags
    debug_event_log: bool = False
    message_display_capture: bool = False
    # 日志目录（None 表示用默认 ~/.claude_code_buddy/logs）
    log_dir: Optional[str] = None

    # ---- 加载 ----
    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "AdapterConfig":
        valid = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in data.items() if k in valid}
        return cls(**kwargs)

    @classmethod
    def from_file(cls, path: str | Path) -> "AdapterConfig":
        path = Path(path)
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".toml":
            data = tomllib.loads(text)
        elif path.suffix.lower() == ".json":
            data = json.loads(text)
        else:
            raise ValueError(f"unsupported config file type: {path}")
        # 允许 pyproject 风格 [tool.buddy] 段，也允许顶层平铺
        tool = data.get("tool") if isinstance(data, dict) else None
        if isinstance(tool, dict) and "buddy" in tool:
            data = tool["buddy"]
        return cls.from_mapping(data)

    def apply_env(self, prefix: str = "BUDDY_") -> "AdapterConfig":
        """用环境变量就地覆盖，返回 self。"""
        env = os.environ
        if f"{prefix}HTTP_HOST" in env:
            self.http_host = env[f"{prefix}HTTP_HOST"]
        if f"{prefix}HTTP_PORT" in env:
            self.http_port = _env_int(f"{prefix}HTTP_PORT", self.http_port)
        if f"{prefix}SERIAL_PORT" in env:
            self.serial_port = env[f"{prefix}SERIAL_PORT"] or None
        if f"{prefix}BAUDRATE" in env:
            self.baudrate = _env_int(f"{prefix}BAUDRATE", self.baudrate)
        if f"{prefix}PRIVACY_MODE" in env:
            self.privacy_mode = _env_bool(f"{prefix}PRIVACY_MODE", self.privacy_mode)
        if f"{prefix}SOUND_ENABLED" in env:
            self.sound_enabled_default = _env_bool(f"{prefix}SOUND_ENABLED", self.sound_enabled_default)
        if f"{prefix}DONE_TTL_MS" in env:
            self.done_ttl_ms = _env_int(f"{prefix}DONE_TTL_MS", self.done_ttl_ms)
        if f"{prefix}SESSION_TTL_MS" in env:
            self.session_ttl_ms = _env_int(f"{prefix}SESSION_TTL_MS", self.session_ttl_ms)
        if f"{prefix}DEBUG_EVENT_LOG" in env:
            self.debug_event_log = _env_bool(f"{prefix}DEBUG_EVENT_LOG", self.debug_event_log)
        if f"{prefix}MESSAGE_DISPLAY_CAPTURE" in env:
            self.message_display_capture = _env_bool(
                f"{prefix}MESSAGE_DISPLAY_CAPTURE", self.message_display_capture
            )
        if f"{prefix}LOG_DIR" in env:
            self.log_dir = env[f"{prefix}LOG_DIR"] or None
        return self

    @classmethod
    def load(
        cls, config_path: str | Path | None = None, env: bool = True
    ) -> "AdapterConfig":
        """默认值 → 配置文件 → 环境变量，依次覆盖。"""
        cfg = cls()
        if config_path is not None and Path(config_path).exists():
            cfg = cls.from_file(config_path)
        if env:
            cfg.apply_env()
        return cfg

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
