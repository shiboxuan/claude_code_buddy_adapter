"""buddy-adapter CLI 入口。

子命令：run / doctor / install-claude / replay / dump-state。
ADP-P0 仅提供 stub（打印"未实现"并 exit 2），实际实现见 ADP-P7。
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from . import __version__


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="buddy-adapter",
        description="Claude Code Buddy 桌宠 adapter",
    )
    parser.add_argument(
        "--version", action="version", version=f"buddy-adapter {__version__}"
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    sub.add_parser("run", help="启动 HTTP receiver + serial bridge")
    sub.add_parser(
        "doctor",
        help="检查 Python env / serial / Claude Code 配置 / firmware 协议",
    )

    p_install = sub.add_parser(
        "install-claude", help="生成或安装 Claude Code hooks/statusLine 配置"
    )
    p_install.add_argument(
        "--print", action="store_true", help="只打印配置片段，不写文件"
    )
    p_install.add_argument(
        "--write", action="store_true", help="写入 ~/.claude/settings.json（先备份）"
    )

    p_replay = sub.add_parser("replay", help="回放 JSONL 事件流到状态机与设备")
    p_replay.add_argument("file", nargs="?", help="JSONL 事件文件")

    sub.add_parser("dump-state", help="输出当前 sessions / focus / counts / metrics")
    return parser


def _not_implemented(name: str) -> int:
    print(
        f"buddy-adapter: '{name}' 尚未实现（计划在 ADP-P7 完成）",
        file=sys.stderr,
    )
    return 2


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command in {"run", "doctor", "install-claude", "replay", "dump-state"}:
        return _not_implemented(args.command)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
