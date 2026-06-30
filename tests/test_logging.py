"""ADP-P0-T05: 四类日志框架。"""

from __future__ import annotations

from claude_code_buddy_adapter.config import AdapterConfig
from claude_code_buddy_adapter.logging_setup import (
    LOGGERS,
    RingBufferHandler,
    get_logger,
    setup_logging,
)


def test_setup_logging_returns_four_loggers(tmp_path):
    cfg = AdapterConfig(log_dir=str(tmp_path))
    loggers = setup_logging(cfg)
    assert set(loggers.keys()) == set(LOGGERS)


def test_app_log_stdout_and_file(tmp_path, capsys):
    cfg = AdapterConfig(log_dir=str(tmp_path), debug_event_log=False)
    setup_logging(cfg)
    app = get_logger("app")
    app.info("hello adapter")
    out = capsys.readouterr().out
    assert "hello adapter" in out
    assert (tmp_path / "app.log").exists()


def test_event_log_ring_buffer_when_disabled(tmp_path, capsys):
    cfg = AdapterConfig(log_dir=str(tmp_path), debug_event_log=False)
    setup_logging(cfg)
    event = get_logger("event")
    event.info("an event")
    out = capsys.readouterr().out
    assert "an event" not in out  # 关闭时不进 stdout
    handlers = [h for h in event.handlers if isinstance(h, RingBufferHandler)]
    assert handlers
    assert any("an event" in s for s in handlers[0].snapshot())


def test_event_log_stdout_when_enabled(tmp_path, capsys):
    cfg = AdapterConfig(log_dir=str(tmp_path), debug_event_log=True)
    setup_logging(cfg)
    event = get_logger("event")
    event.info("visible event")
    out = capsys.readouterr().out
    assert "visible event" in out
    assert (tmp_path / "event.log").exists()


def test_state_log_file(tmp_path):
    cfg = AdapterConfig(log_dir=str(tmp_path))
    setup_logging(cfg)
    state = get_logger("state")
    state.info("idle -> working")
    state.handlers[0].flush()
    assert (tmp_path / "state.log").exists()


def test_serial_log_ring_buffer_only(tmp_path, capsys):
    cfg = AdapterConfig(log_dir=str(tmp_path))
    setup_logging(cfg)
    serial = get_logger("serial")
    serial.info('{"type":"device_snapshot","line2":"secret command"}')
    out = capsys.readouterr().out
    # serial 默认不进 stdout（只 ring buffer）
    assert "secret command" not in out
    handlers = [h for h in serial.handlers if isinstance(h, RingBufferHandler)]
    assert handlers


def test_setup_logging_idempotent(tmp_path):
    cfg = AdapterConfig(log_dir=str(tmp_path))
    setup_logging(cfg)
    app = get_logger("app")
    n1 = len(app.handlers)
    setup_logging(cfg)
    n2 = len(app.handlers)
    assert n1 == n2  # 重复配置不累积 handler


def test_file_log_includes_level_and_timestamp(tmp_path):
    cfg = AdapterConfig(log_dir=str(tmp_path), debug_event_log=True)
    setup_logging(cfg)
    app = get_logger("app")
    app.info("formatted line")
    for h in app.handlers:
        h.flush()
    content = (tmp_path / "app.log").read_text(encoding="utf-8")
    assert "formatted line" in content
    assert "INFO" in content  # file handler 设了 formatter，含级别
    assert "claude_code_buddy_adapter.app" in content  # 含 logger 名
