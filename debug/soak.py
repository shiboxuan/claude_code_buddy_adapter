#!/usr/bin/env python3
"""debug/soak.py - ADP-P9-T06 8 小时稳定性 soak 脚本。

向运行中的 adapter（127.0.0.1:8765）周期注入各类 hook/statusLine 事件，
定期查询 /v1/metrics 监控 serial 不丢连接、进程存活、坏 payload 隔离。
默认 8 小时（28800s），可用 --duration 缩短做冒烟。

用法::

    # 先启动 adapter: buddy-adapter run（真机或 fake）
    conda run -n claude_code_buddy_adapter python debug/soak.py --duration 28800

验收: 8h 后进程存活、device_connected 稳定、serial_reconnect_total 无异常暴涨、
events_received_total 持续递增、无崩溃、坏 payload 被隔离不崩。
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request

BASE = "http://127.0.0.1:8765"

# 一个 session 的生命周期事件序列（循环注入）
EVENT_CYCLE = [
    ("hook", {"hook_event_name": "SessionStart"}),
    ("hook", {"hook_event_name": "UserPromptSubmit"}),
    ("hook", {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}}),
    ("hook", {"hook_event_name": "PostToolUse", "tool_name": "Bash"}),
    ("hook", {"hook_event_name": "Notification", "message": "soak 测试"}),
    ("hook", {"hook_event_name": "Stop"}),
    ("hook", {"hook_event_name": "SessionEnd"}),
]
# 偶发坏 payload（验证隔离，不应崩进程）
BAD_PAYLOADS = ["not json", "{bad", json.dumps([1, 2])]


def post(path: str, body: bytes):
    req = urllib.request.Request(
        BASE + path, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            return r.status
    except Exception as e:  # noqa: BLE001
        return f"ERR:{e}"


def get_metrics() -> dict:
    try:
        with urllib.request.urlopen(BASE + "/v1/metrics", timeout=3) as r:
            return json.loads(r.read()).get("metrics", {})
    except Exception as e:  # noqa: BLE001
        return {"_err": str(e)}


def main() -> None:
    ap = argparse.ArgumentParser(description="ADP-P9-T06 8h soak")
    ap.add_argument("--duration", type=int, default=28800, help="秒，默认 28800=8h")
    ap.add_argument("--interval", type=float, default=1.0, help="注入间隔秒")
    ap.add_argument("--report-every", type=int, default=600, help="每 N 秒打印一次指标")
    args = ap.parse_args()

    deadline = time.time() + args.duration
    n = 0
    last_report = time.time()
    sessions = ["soak-a", "soak-b"]
    print(f"soak: 持续 {args.duration}s，间隔 {args.interval}s，报告每 {args.report_every}s")
    start_metrics = get_metrics()
    print("start metrics:", json.dumps(start_metrics, ensure_ascii=False))

    while time.time() < deadline:
        sid = sessions[n % len(sessions)]
        path, payload = EVENT_CYCLE[n % len(EVENT_CYCLE)]
        payload = {"session_id": sid, "cwd": "/tmp/soak", **payload}
        post(f"/v1/claude/{path}", json.dumps(payload).encode())
        n += 1
        if n % 50 == 0:  # 偶发坏 payload
            post("/v1/claude/hook", BAD_PAYLOADS[n % len(BAD_PAYLOADS)].encode())
        if time.time() - last_report >= args.report_every:
            m = get_metrics()
            if "_err" in m:
                print(f"[{n}] adapter 不可达: {m['_err']}")
            else:
                print(
                    f"[sent={n}] "
                    f"device_connected={m.get('device_connected')} "
                    f"reconnect={m.get('serial_reconnect_total')} "
                    f"events={m.get('events_received_total')} "
                    f"send_fail={m.get('snapshot_send_failure_total')}"
                )
            last_report = time.time()
        time.sleep(args.interval)

    end_metrics = get_metrics()
    print(f"\nsoak 完成: sent={n}")
    print("start:", json.dumps(start_metrics, ensure_ascii=False))
    print("end:  ", json.dumps(end_metrics, ensure_ascii=False))


if __name__ == "__main__":
    main()
