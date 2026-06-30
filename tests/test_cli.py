"""ADP-P0/P7: CLI 入口测试（version/help + 五子命令实装）。"""

from __future__ import annotations

import json

import pytest

from claude_code_buddy_adapter.cli import (
    _hook_helper_script,
    _settings_fragment,
    _statusline_helper_script,
    main,
)

SUBCOMMANDS = ["run", "doctor", "install-claude", "replay", "dump-state"]


def test_no_command_prints_help(capsys):
    assert main([]) == 0
    assert "buddy-adapter" in capsys.readouterr().out


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "buddy-adapter" in capsys.readouterr().out


@pytest.mark.parametrize("cmd", SUBCOMMANDS)
def test_subcommand_help(cmd, capsys):
    with pytest.raises(SystemExit) as exc:
        main([cmd, "--help"])
    assert exc.value.code == 0


def test_install_claude_options_in_help(capsys):
    with pytest.raises(SystemExit):
        main(["install-claude", "--help"])
    out = capsys.readouterr().out
    assert "--print" in out and "--write" in out


# ---- install-claude --print ----

def test_install_claude_print_outputs_scripts_and_settings(capsys):
    rc = main(["install-claude", "--print"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "claude-code-buddy-statusline" in out
    assert "claude-code-buddy-hook" in out
    assert "/v1/claude/statusline" in out
    assert "/v1/claude/hook" in out
    assert "exit 0" in out
    assert "statusLine" in out
    assert "hooks" in out


def test_install_claude_default_prints(capsys):
    # 无 --print/--write 也打印
    rc = main(["install-claude"])
    assert rc == 0
    assert "statusLine" in capsys.readouterr().out


def test_install_claude_settings_fragment_valid():
    frag = _settings_fragment()
    assert frag["statusLine"]["type"] == "command"
    assert frag["statusLine"]["refreshInterval"] == 2
    for ev in ["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
               "Notification", "Stop", "StopFailure", "SessionEnd"]:
        assert ev in frag["hooks"]
    # PreToolUse/PostToolUse 带 matcher
    assert frag["hooks"]["PreToolUse"][0]["matcher"] == "*"
    assert frag["hooks"]["PostToolUse"][0]["matcher"] == "*"
    # SessionStart 不带 matcher
    assert "matcher" not in frag["hooks"]["SessionStart"][0]
    json.dumps(frag)  # JSON 合法


def test_helper_scripts_exit_0_and_curl():
    for script in (_statusline_helper_script(), _hook_helper_script()):
        assert "exit 0" in script
        assert "curl" in script
        assert "|| true" in script  # curl 失败也继续


def test_install_claude_write_not_implemented_yet(capsys):
    rc = main(["install-claude", "--write"])
    assert rc == 2  # ADP-P9 实现


# ---- doctor ----

def test_doctor_runs_and_reports(capsys):
    rc = main(["doctor"])
    assert rc in (0, 1)
    out = capsys.readouterr().out.lower()
    assert "python" in out
    assert "serial" in out
    assert "claude" in out
    assert "firmware" in out


# ---- replay ----

def test_replay_missing_file(capsys):
    rc = main(["replay", "/nonexistent/file.jsonl"])
    assert rc == 2


def test_replay_fixture(tmp_path, capsys):
    events = [
        {"event": {"source": "hook", "session_id": "s1", "hook_event_name": "SessionStart", "received_at_ms": 1000}},
        {"event": {"source": "hook", "session_id": "s1", "hook_event_name": "PreToolUse", "received_at_ms": 2000}},
        {"event": {"source": "hook", "session_id": "s1", "hook_event_name": "Stop", "received_at_ms": 3000}},
    ]
    f = tmp_path / "events.jsonl"
    f.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
    rc = main(["replay", str(f)])
    assert rc == 0
    state = json.loads(capsys.readouterr().out)
    assert state["counts"]["sessions"] == 1
    assert state["sessions"][0]["state"] == "done_recent"
    assert state["sessions"][0]["session_id"] == "s1"


def test_replay_skips_bad_lines(tmp_path, capsys):
    f = tmp_path / "events.jsonl"
    f.write_text(
        json.dumps({"event": {"source": "hook", "session_id": "s1", "hook_event_name": "PreToolUse"}}) + "\n"
        "not json line\n"
        + json.dumps({"event": {"source": "hook", "session_id": "s1", "hook_event_name": "Stop"}}) + "\n",
        encoding="utf-8",
    )
    rc = main(["replay", str(f)])
    assert rc == 0  # 坏行跳过，不崩


# ---- dump-state（无 adapter 运行时返回 1）----

def test_dump_state_no_adapter(capsys):
    rc = main(["dump-state"])
    assert rc == 1  # 无 adapter 连接
