"""ADP-P0-T04: AdapterConfig 默认值 / 配置文件 / 环境变量覆盖。"""

from __future__ import annotations

import json

from claude_code_buddy_adapter.config import AdapterConfig


def test_defaults():
    cfg = AdapterConfig()
    assert cfg.http_host == "127.0.0.1"
    assert cfg.http_port == 8765
    assert cfg.serial_port is None
    assert cfg.baudrate == 115200
    assert cfg.privacy_mode is False
    assert cfg.sound_enabled_default is True
    assert cfg.done_ttl_ms == 5000
    assert cfg.session_ttl_ms == 300_000
    assert cfg.debug_event_log is False
    assert cfg.message_display_capture is False


def test_load_defaults_no_file():
    cfg = AdapterConfig.load(config_path=None)
    assert cfg.http_port == 8765


def test_from_json_file(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"http_port": 9000, "privacy_mode": True}))
    cfg = AdapterConfig.from_file(p)
    assert cfg.http_port == 9000
    assert cfg.privacy_mode is True


def test_from_toml_file(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('http_port = 9100\nserial_port = "/dev/ttyACM0"\n')
    cfg = AdapterConfig.from_file(p)
    assert cfg.http_port == 9100
    assert cfg.serial_port == "/dev/ttyACM0"


def test_from_toml_tool_buddy_section(tmp_path):
    p = tmp_path / "pyproject.toml"
    p.write_text("[tool.buddy]\nhttp_port = 9200\n")
    cfg = AdapterConfig.from_file(p)
    assert cfg.http_port == 9200


def test_env_override(monkeypatch):
    monkeypatch.setenv("BUDDY_HTTP_PORT", "7777")
    monkeypatch.setenv("BUDDY_PRIVACY_MODE", "true")
    monkeypatch.setenv("BUDDY_SERIAL_PORT", "/dev/ttyUSB0")
    cfg = AdapterConfig.load()
    assert cfg.http_port == 7777
    assert cfg.privacy_mode is True
    assert cfg.serial_port == "/dev/ttyUSB0"


def test_env_overrides_file(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"http_port": 9000}))
    monkeypatch.setenv("BUDDY_HTTP_PORT", "8888")
    cfg = AdapterConfig.load(config_path=p)
    assert cfg.http_port == 8888


def test_unknown_keys_ignored(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"http_port": 9000, "unknown_field": "x"}))
    cfg = AdapterConfig.from_file(p)
    assert cfg.http_port == 9000


def test_unsupported_file_type(tmp_path):
    p = tmp_path / "config.txt"
    p.write_text("foo")
    try:
        AdapterConfig.from_file(p)
    except ValueError:
        return
    raise AssertionError("expected ValueError for unsupported file type")


def test_env_int_invalid_value_falls_back(monkeypatch):
    monkeypatch.setenv("BUDDY_HTTP_PORT", "abc")
    cfg = AdapterConfig.load()
    assert cfg.http_port == 8765  # 非法值回退默认，不崩溃
