"""buddy-adapter CLI 入口。

子命令：run / doctor / install-claude / replay / dump-state（ADP-P7 实装）。
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import urllib.request
from pathlib import Path
from typing import Optional, Sequence

from . import __version__
from . import install_claude as _install

CLAUDE_DIR = Path.home() / ".claude"
STATUSLINE_HELPER = CLAUDE_DIR / "claude-code-buddy-statusline"
HOOK_HELPER = CLAUDE_DIR / "claude-code-buddy-hook"
SETTINGS_JSON = CLAUDE_DIR / "settings.json"

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="buddy-adapter", description="Claude Code Buddy 桌宠 adapter"
    )
    parser.add_argument(
        "--version", action="version", version=f"buddy-adapter {__version__}"
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.add_parser("run", help="启动 HTTP receiver + serial bridge")
    sub.add_parser("doctor", help="检查 Python env / serial / Claude Code 配置 / firmware")
    p_install = sub.add_parser(
        "install-claude", help="生成或安装 Claude Code hooks/statusLine 配置"
    )
    p_install.add_argument("--print", action="store_true", help="只打印配置片段，不写文件")
    p_install.add_argument(
        "--write", action="store_true",
        help="写 helper 脚本并追加合并进 settings.json（先备份；幂等）",
    )
    p_install.add_argument(
        "--claude-dir", default=None,
        help="Claude Code 配置目录（默认 $CLAUDE_CONFIG_DIR 或 ~/.claude）",
    )
    p_install.add_argument(
        "--settings-path", default=None,
        help="直接指定 settings.json 路径（优先于 --claude-dir）",
    )
    p_install.add_argument(
        "--create", action="store_true",
        help="settings.json 不存在时新建（默认找不到则中断提示）",
    )
    p_install.add_argument(
        "--force-statusline", action="store_true",
        help="覆盖已有非 buddy 的 statusLine（Claude Code 仅允许一个 statusLine）",
    )
    p_replay = sub.add_parser("replay", help="回放 JSONL 事件流到状态机")
    p_replay.add_argument("file", help="JSONL 事件文件")
    sub.add_parser("dump-state", help="输出当前 sessions / focus / counts / metrics")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    handlers = {
        "run": _cmd_run,
        "doctor": _cmd_doctor,
        "install-claude": _cmd_install_claude,
        "replay": _cmd_replay,
        "dump-state": _cmd_dump_state,
    }
    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        return 0
    return handler(args)


# ---- run ----
def _make_transport_factory(config):
    """返回 callable：重新 discover/open 端口，返回已 open 的 transport，无设备返 None。

    真机断线重连时由 bridge._reconnect_loop 周期调用（INT-5）。
    """
    from .device.discovery import SerialDiscovery
    from .device.transport import SerialTransport

    def factory():
        port = config.serial_port or SerialDiscovery().find()
        if not port:
            return None
        transport = SerialTransport(port, config.baudrate)
        transport.open()
        return transport

    return factory


def _build_runtime(config):
    from .device.bridge import SerialBridge
    from .device.fake_transport import FakeSerialTransport
    from .metrics import METRICS
    from .receiver.http_server import create_app
    from .session.snapshot import DisplayComposer
    from .session.store import SessionStore

    store = SessionStore(
        done_ttl_ms=config.done_ttl_ms,
        session_ttl_ms=config.session_ttl_ms,
        working_ttl_ms=config.working_ttl_ms,
    )
    composer = DisplayComposer(config)
    metrics = METRICS
    factory = _make_transport_factory(config)
    try:
        transport = factory()
    except Exception:
        transport = None
    if transport is None:
        # 无设备：fallback fake，不启用自动重连（ADP-P5 行为）
        transport = FakeSerialTransport()
        transport_factory = None
    else:
        transport_factory = factory
    bridge = SerialBridge(
        transport, store, composer, config, metrics=metrics,
        transport_factory=transport_factory,
    )
    app = create_app(store, composer, config, bridge=bridge, metrics=metrics)
    return store, composer, bridge, app


def _cmd_run(args) -> int:
    import uvicorn

    from .config import AdapterConfig
    from .logging_setup import setup_logging

    config = AdapterConfig.load()
    setup_logging(config)
    _, _, bridge, app = _build_runtime(config)
    bridge.start()
    try:
        uvicorn.run(
            app, host=config.http_host, port=config.http_port, log_level="warning"
        )
    except KeyboardInterrupt:
        pass
    finally:
        bridge.stop()
    return 0


# ---- doctor ----
def _check_claude_settings() -> bool:
    if not SETTINGS_JSON.exists():
        return False
    try:
        data = json.loads(SETTINGS_JSON.read_text(encoding="utf-8"))
    except Exception:
        return False
    return "claude-code-buddy" in json.dumps(data)


def _cmd_doctor(args) -> int:
    checks: list[tuple[str, str, str]] = []

    py_ok = sys.version_info >= (3, 11)
    checks.append(("python env", "PASS" if py_ok else "FAIL", f"Python {sys.version.split()[0]}"))

    try:
        from .device.discovery import SerialDiscovery

        port = SerialDiscovery().find()
        checks.append(("serial device", "PASS" if port else "FAIL", port or "未发现 StickS3"))
    except Exception as e:  # noqa: BLE001
        checks.append(("serial device", "FAIL", str(e)))

    settings_ok = _check_claude_settings()
    checks.append((
        "claude settings",
        "PASS" if settings_ok else "FAIL",
        f"{SETTINGS_JSON} 含 buddy 配置" if settings_ok else f"{SETTINGS_JSON} 未含 buddy 配置",
    ))

    checks.append(("firmware protocol", "SKIP", "无设备在线或留待真机联调（ADP-P9）"))

    for name, status, detail in checks:
        print(f"[{status}] {name}: {detail}")
    return 0 if all(s in ("PASS", "SKIP") for _, s, _ in checks) else 1


# ---- install-claude ----
def _statusline_helper_script() -> str:
    return _install.statusline_helper_script()


def _hook_helper_script() -> str:
    return _install.hook_helper_script()


def _settings_fragment() -> dict:
    return _install.settings_fragment(STATUSLINE_HELPER, HOOK_HELPER)


def _cmd_install_claude(args) -> int:
    # 默认（无 --write）或显式 --print：只打印配置片段，不写文件
    if not args.write:
        cdir = _install.resolve_claude_dir(args.claude_dir)
        sl = cdir / _install.STATUSLINE_HELPER_NAME
        hk = cdir / _install.HOOK_HELPER_NAME
        print("# === {0} ===".format(sl))
        print(_statusline_helper_script(), end="")
        print("# === {0} ===".format(hk))
        print(_hook_helper_script(), end="")
        print("# === settings.json 片段（手动合并，或用 --write 自动追加合并） ===")
        print(json.dumps(_install.settings_fragment(sl, hk), indent=2, ensure_ascii=False))
        return 0

    # --write：写 helper + 追加合并 settings.json（先备份；幂等）
    try:
        result = _install.apply_install(
            args.claude_dir,
            settings_path=args.settings_path,
            create=args.create,
            force_statusline=args.force_statusline,
        )
    except _install.InstallError as e:
        print(f"install-claude: {e}", file=sys.stderr)
        return 2
    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    return 0


# ---- replay ----
def _cmd_replay(args) -> int:
    from .claude.normalizer import normalize
    from .session.store import SessionStore

    path = Path(args.file)
    if not path.exists():
        print(f"replay: 文件不存在 {path}", file=sys.stderr)
        return 2
    store = SessionStore()
    last_ms = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        event = obj.get("event", obj) if isinstance(obj, dict) else {}
        source = event.get("source", "hook")
        raw = event.get("raw") if isinstance(event.get("raw"), dict) else {}
        if event.get("session_id"):
            raw = {**raw, "session_id": event["session_id"]}
        if event.get("hook_event_name"):
            raw = {**raw, "hook_event_name": event["hook_event_name"]}
        ev = normalize(raw, source, received_at_ms=event.get("received_at_ms"))
        store.apply_event(ev)
        if ev.received_at_ms is not None:
            last_ms = max(last_ms, ev.received_at_ms)
    # 用回放流最后事件时间 dump，复现回放时刻状态（避免真实时间把 done_recent 误降级）
    focus = store.focus(now_ms=last_ms)
    state = {
        "global_state": store.global_state(device_connected=False, now_ms=last_ms),
        "focus_session_id": focus.session_id if focus else None,
        "sessions": [
            {"session_id": s.session_id, "state": s.state.value,
             "repo": s.repo_name, "updated_at_ms": s.updated_at_ms}
            for s in store.active(now_ms=last_ms)
        ],
        "counts": store.counts(now_ms=last_ms),
    }
    print(json.dumps(state, indent=2, ensure_ascii=False))
    return 0


# ---- dump-state ----
def _http_get(url: str):
    with urllib.request.urlopen(url, timeout=2) as r:
        return json.loads(r.read().decode("utf-8"))


def _cmd_dump_state(args) -> int:
    from .config import AdapterConfig

    config = AdapterConfig.load()
    base = f"http://{config.http_host}:{config.http_port}"
    try:
        state = _http_get(f"{base}/v1/state")
        metrics = _http_get(f"{base}/v1/metrics").get("metrics", {})
    except Exception as e:  # noqa: BLE001
        print(f"dump-state: 无法连接 adapter ({e})", file=sys.stderr)
        return 1
    out = {**state, "metrics": metrics}
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
