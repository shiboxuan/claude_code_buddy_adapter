"""ADP-P0-T06: CLI 入口骨架（--version 与五子命令 help / stub）。"""

from __future__ import annotations

import pytest

from claude_code_buddy_adapter.cli import main

SUBCOMMANDS = ["run", "doctor", "install-claude", "replay", "dump-state"]


def test_no_command_prints_help(capsys):
    rc = main([])
    assert rc == 0
    out = capsys.readouterr().out
    assert "buddy-adapter" in out


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "buddy-adapter" in out


@pytest.mark.parametrize("cmd", SUBCOMMANDS)
def test_subcommand_help(cmd, capsys):
    with pytest.raises(SystemExit) as exc:
        main([cmd, "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert cmd in out or "usage" in out.lower()


@pytest.mark.parametrize("cmd", SUBCOMMANDS)
def test_subcommand_stub(cmd, capsys):
    rc = main([cmd])
    assert rc == 2
    err = capsys.readouterr().err
    assert "尚未实现" in err


def test_install_claude_options_in_help(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["install-claude", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--print" in out
    assert "--write" in out
