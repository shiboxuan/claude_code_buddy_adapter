"""ADP-P7: run / dump-state 子命令集成测试（subprocess，fake serial）。"""

from __future__ import annotations

import inspect
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUDDY = [sys.executable, "-m", "claude_code_buddy_adapter.cli"]


def test_wait_for_adapter_requires_spawned_process_and_target_base():
    parameters = list(inspect.signature(_wait_for_adapter).parameters)
    assert parameters[:2] == ["proc", "base"]


def test_wait_for_adapter_rejects_unrelated_healthy_service(monkeypatch):
    class ExitedProcess:
        def poll(self):
            return 1

    class HealthyResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: HealthyResponse())

    assert not _wait_for_adapter(ExitedProcess(), "http://127.0.0.1:1", timeout_s=0.5)


def _wait_for_adapter(proc, base: str, timeout_s: float = 15.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        time.sleep(0.3)
        try:
            with urllib.request.urlopen(f"{base}/v1/state", timeout=1) as r:
                if r.status == 200 and proc.poll() is None:
                    return True
        except Exception:
            continue
    return False


def _unused_non_production_port() -> int:
    while True:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        if port != 8765:
            return port


def _stop_process(proc: subprocess.Popen, timeout_s: float = 5.0) -> tuple[str, str]:
    if proc.poll() is None:
        proc.terminate()
    try:
        return proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        return proc.communicate(timeout=timeout_s)


@pytest.fixture
def running_adapter():
    port = _unused_non_production_port()
    base = f"http://127.0.0.1:{port}"
    env = {
        **os.environ,
        "BUDDY_HTTP_HOST": "127.0.0.1",
        "BUDDY_HTTP_PORT": str(port),
        "BUDDY_SERIAL_PORT": "",
    }
    proc = subprocess.Popen(
        [*BUDDY, "run"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    if not _wait_for_adapter(proc, base):
        stdout, stderr = _stop_process(proc)
        pytest.fail(
            "spawned adapter did not start on its isolated port\n"
            f"stdout:\n{stdout}\nstderr:\n{stderr}"
        )
    yield proc, base, env
    _stop_process(proc)


def test_run_accepts_http_and_drives_state(running_adapter):
    proc, base, _ = running_adapter
    assert proc.poll() is None
    assert not base.endswith(":8765")
    data = json.dumps({"session_id": "s1", "hook_event_name": "PreToolUse"}).encode()
    req = urllib.request.Request(
        f"{base}/v1/claude/hook", data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=2) as r:
        assert r.status == 200
    with urllib.request.urlopen(f"{base}/v1/state", timeout=2) as r:
        state = json.loads(r.read())
    assert state["counts"]["working"] == 1
    assert state["sessions"][0]["session_id"] == "s1"


def test_dump_state_with_running_adapter(running_adapter):
    _, _, env = running_adapter
    r = subprocess.run(
        [*BUDDY, "dump-state"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert r.returncode == 0
    state = json.loads(r.stdout)
    assert "sessions" in state
    assert "metrics" in state
    assert "global_state" in state


def test_run_graceful_exit_on_sigterm(running_adapter):
    proc, _, _ = running_adapter
    proc.terminate()  # SIGTERM
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        pytest.fail("adapter 未在 SIGTERM 后 5s 内优雅退出")
    assert proc.returncode is not None
