"""ADP-P7: run / dump-state 子命令集成测试（subprocess，fake serial）。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

BUDDY = Path(sys.executable).parent / "buddy-adapter"
BASE = "http://127.0.0.1:8765"


def _wait_for_adapter(timeout_s: float = 15.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        time.sleep(0.3)
        try:
            with urllib.request.urlopen(f"{BASE}/v1/state", timeout=1) as r:
                if r.status == 200:
                    return True
        except Exception:
            continue
    return False


@pytest.fixture
def running_adapter():
    if not BUDDY.exists():
        pytest.skip("buddy-adapter 不在 conda env bin")
    proc = subprocess.Popen(
        [str(BUDDY), "run"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env={**os.environ, "BUDDY_SERIAL_PORT": ""},  # 强制 fake serial
    )
    if not _wait_for_adapter():
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        pytest.skip("adapter 未在超时内启动（环境慢）")
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def test_run_accepts_http_and_drives_state(running_adapter):
    data = json.dumps({"session_id": "s1", "hook_event_name": "PreToolUse"}).encode()
    req = urllib.request.Request(
        f"{BASE}/v1/claude/hook", data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=2) as r:
        assert r.status == 200
    with urllib.request.urlopen(f"{BASE}/v1/state", timeout=2) as r:
        state = json.loads(r.read())
    assert state["counts"]["working"] == 1
    assert state["sessions"][0]["session_id"] == "s1"


def test_dump_state_with_running_adapter(running_adapter):
    r = subprocess.run([str(BUDDY), "dump-state"], capture_output=True, text=True, timeout=5)
    assert r.returncode == 0
    state = json.loads(r.stdout)
    assert "sessions" in state
    assert "metrics" in state
    assert "global_state" in state


def test_run_graceful_exit_on_sigterm():
    if not BUDDY.exists():
        pytest.skip("buddy-adapter 不在 conda env bin")
    proc = subprocess.Popen(
        [str(BUDDY), "run"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env={**os.environ, "BUDDY_SERIAL_PORT": ""},
    )
    if not _wait_for_adapter():
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        pytest.skip("adapter 未启动")
    proc.terminate()  # SIGTERM
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        pytest.fail("adapter 未在 SIGTERM 后 5s 内优雅退出")
    assert proc.returncode is not None
