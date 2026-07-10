#!/usr/bin/env python3
"""debug/capture_payloads.py — 捕获 Claude Code hooks/statusLine 真实 raw payload。

ADP-P9-T01 工具：装好 ``install-claude`` 配置后，停掉 adapter，用本脚本监听
8765，让真实 Claude Code session 触发 hooks/statusLine，把 raw payload 落盘到
指定目录，用于 normalizer 校准与 fixture 入库。

用法::

    conda run -n claude_code_buddy_adapter python debug/capture_payloads.py \\
        --port 8765 --out tests/fixtures/real/

每个 payload 落盘为 ``{source}_{event}_{counter}.json``。Ctrl-C 停止并打印统计。

注意：本脚本只接收并落盘，不驱动状态机，与 adapter 互斥占用 8765——运行前需
先停 adapter（``buddy-adapter run``），采集完再重启 adapter。helper 脚本的
``curl -m 2 ... || true`` 保证即便本脚本未运行也不阻塞 Claude Code。
"""

from __future__ import annotations

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

COUNTER = {"n": 0}


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(s))[:40]


class Handler(BaseHTTPRequestHandler):
    out_dir: Path = Path(".")

    def _capture(self, source: str) -> None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            payload = {"_raw": raw.decode("utf-8", "replace"), "_parse_error": True}
        event = None
        if isinstance(payload, dict):
            event = payload.get("hook_event_name")
        if not event:
            event = "statusline" if source == "statusline" else "unknown"
        COUNTER["n"] += 1
        name = f"{source}_{_safe(event)}_{COUNTER['n']:03d}.json"
        path = self.out_dir / name
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"[capture] {source}/{event} -> {path.name}")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def do_POST(self) -> None:
        if self.path.endswith("/statusline"):
            self._capture("statusline")
        elif self.path.endswith("/hook"):
            self._capture("hook")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt, *args) -> None:  # 安静
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description="捕获 Claude Code 真实 raw payload")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--out", default="tests/fixtures/real")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    Handler.out_dir = out
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"capture_payloads: 监听 127.0.0.1:{args.port}, 落盘到 {out}/")
    print("Ctrl-C 停止")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print(f"\n停止。共捕获 {COUNTER['n']} 个 payload。")


if __name__ == "__main__":
    main()
