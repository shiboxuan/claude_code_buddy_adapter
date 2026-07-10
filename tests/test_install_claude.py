"""ADP-P9-T02: install-claude --write 单元测试。

覆盖：路径解析、helper 写入、备份、追加合并 hooks（保留原配置/幂等）、
statusLine 冲突处理、找不到配置中断、--create 新建、坏 JSON 容错。
全部用 tmp_path，不触碰真实 ~/.claude。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from claude_code_buddy_adapter import install_claude as ic


# ---- 路径解析 ----
def test_resolve_claude_dir_explicit_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/some/env/dir")
    assert ic.resolve_claude_dir(str(tmp_path)) == tmp_path


def test_resolve_claude_dir_env_fallback(monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/env/claude")
    assert ic.resolve_claude_dir(None) == Path("/env/claude")


def test_resolve_claude_dir_default(monkeypatch):
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    assert ic.resolve_claude_dir(None) == ic.DEFAULT_CLAUDE_DIR


def test_resolve_settings_path_overrides_claude_dir(tmp_path):
    sp = tmp_path / "custom.json"
    assert ic.resolve_settings_path(str(tmp_path), str(sp)) == sp


# ---- is_buddy_command ----
def test_is_buddy_command_absolute(tmp_path):
    hk = tmp_path / ic.HOOK_HELPER_NAME
    assert ic.is_buddy_command(str(hk), hk)


def test_is_buddy_command_tilde(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    hk = tmp_path / ic.HOOK_HELPER_NAME
    assert ic.is_buddy_command(f"~/{ic.HOOK_HELPER_NAME}", hk)


def test_is_buddy_command_non_match(tmp_path):
    hk = tmp_path / ic.HOOK_HELPER_NAME
    assert not ic.is_buddy_command("/some/other/script", hk)
    assert not ic.is_buddy_command(None, hk)
    assert not ic.is_buddy_command("", hk)


# ---- write_helpers ----
def test_write_helpers_creates_executable(tmp_path):
    sl, hk = ic.write_helpers(tmp_path)
    assert sl.exists() and hk.exists()
    assert "curl" in sl.read_text()
    assert "exit 0" in hk.read_text()
    assert os.access(sl, os.X_OK)
    assert os.access(hk, os.X_OK)


# ---- merge_hooks（追加写入，保留原配置，幂等）----
def test_merge_hooks_into_empty(tmp_path):
    hk = tmp_path / ic.HOOK_HELPER_NAME
    frag = ic.settings_fragment(tmp_path / "sl", hk)["hooks"]
    merged, added = ic.merge_hooks(None, frag, hk)
    assert set(added) == set(ic.HOOK_EVENTS)
    assert ic._event_list_has_buddy(merged["PreToolUse"], hk)


def test_merge_hooks_preserves_existing_other_events(tmp_path):
    hk = tmp_path / ic.HOOK_HELPER_NAME
    frag = ic.settings_fragment(tmp_path / "sl", hk)["hooks"]
    existing = {
        "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "/other"}]}],
        "SomeOtherEvent": [{"hooks": [{"type": "command", "command": "/x"}]}],
    }
    merged, added = ic.merge_hooks(existing, frag, hk)
    # 保留原有 matcher-group 不动
    assert merged["PreToolUse"][0]["matcher"] == "Bash"
    assert merged["PreToolUse"][0]["hooks"][0]["command"] == "/other"
    # buddy 追加到末尾
    assert ic.is_buddy_command(merged["PreToolUse"][-1]["hooks"][0]["command"], hk)
    # 其他 event 原样保留
    assert merged["SomeOtherEvent"] == existing["SomeOtherEvent"]
    assert "SomeOtherEvent" not in added


def test_merge_hooks_idempotent(tmp_path):
    hk = tmp_path / ic.HOOK_HELPER_NAME
    frag = ic.settings_fragment(tmp_path / "sl", hk)["hooks"]
    merged1, added1 = ic.merge_hooks({}, frag, hk)
    merged2, added2 = ic.merge_hooks(merged1, frag, hk)
    assert added2 == []
    for ev in ic.HOOK_EVENTS:
        assert len(merged2[ev]) == len(merged1[ev]) == 1


# ---- merge_statusline ----
def test_merge_statusline_empty(tmp_path):
    sl = tmp_path / ic.STATUSLINE_HELPER_NAME
    frag = ic.settings_fragment(sl, tmp_path / "hk")["statusLine"]
    new, action = ic.merge_statusline(None, frag, sl, force=False)
    assert action == "set"
    assert new["command"] == str(sl)


def test_merge_statusline_buddy_idempotent(tmp_path):
    sl = tmp_path / ic.STATUSLINE_HELPER_NAME
    frag = ic.settings_fragment(sl, tmp_path / "hk")["statusLine"]
    existing = {"type": "command", "command": str(sl), "refreshInterval": 5}
    new, action = ic.merge_statusline(existing, frag, sl, force=False)
    assert action == "idempotent"
    assert new["refreshInterval"] == 5  # 保留原配置


def test_merge_statusline_conflict(tmp_path):
    sl = tmp_path / ic.STATUSLINE_HELPER_NAME
    frag = ic.settings_fragment(sl, tmp_path / "hk")["statusLine"]
    existing = {"type": "command", "command": "/other/statusline"}
    _, action = ic.merge_statusline(existing, frag, sl, force=False)
    assert action == "conflict"


def test_merge_statusline_force_overrides(tmp_path):
    sl = tmp_path / ic.STATUSLINE_HELPER_NAME
    frag = ic.settings_fragment(sl, tmp_path / "hk")["statusLine"]
    existing = {"type": "command", "command": "/other/statusline"}
    new, action = ic.merge_statusline(existing, frag, sl, force=True)
    assert action == "set"
    assert new["command"] == str(sl)


# ---- backup ----
def test_backup_settings_creates_bak(tmp_path):
    sp = tmp_path / "settings.json"
    sp.write_text('{"a": 1}', encoding="utf-8")
    bak = ic.backup_settings(sp)
    assert bak.exists()
    assert bak.name.startswith("settings.json.bak")
    assert bak.read_text() == '{"a": 1}'
    assert sp.read_text() == '{"a": 1}'  # 原文件不动


def test_backup_settings_does_not_overwrite_existing(tmp_path):
    sp = tmp_path / "settings.json"
    sp.write_text('{"a": 1}', encoding="utf-8")
    bak1 = ic.backup_settings(sp)
    bak2 = ic.backup_settings(sp)
    assert bak1 != bak2
    assert bak1.exists() and bak2.exists()


# ---- apply_install 端到端 ----
def test_apply_install_missing_settings_aborts(tmp_path):
    with pytest.raises(ic.InstallError, match="找不到"):
        ic.apply_install(str(tmp_path))
    # 中断时不落任何文件
    assert not (tmp_path / ic.SETTINGS_NAME).exists()
    assert not (tmp_path / ic.HOOK_HELPER_NAME).exists()


def test_apply_install_create_new(tmp_path):
    r = ic.apply_install(str(tmp_path), create=True)
    assert r.created is True
    assert r.backup_path is None  # 新建不备份
    data = json.loads((tmp_path / ic.SETTINGS_NAME).read_text())
    assert "statusLine" in data and "hooks" in data
    assert ic.is_buddy_command(
        data["statusLine"]["command"], tmp_path / ic.STATUSLINE_HELPER_NAME
    )
    assert set(r.added_hook_events) == set(ic.HOOK_EVENTS)


def test_apply_install_merges_preserving_existing(tmp_path):
    sp = tmp_path / ic.SETTINGS_NAME
    sp.write_text(json.dumps({
        "permissions": {"allow": ["Bash"]},
        "model": "claude-opus-4-8",
        "hooks": {
            "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "/other"}]}],
        },
        "statusLine": None,
    }), encoding="utf-8")
    r = ic.apply_install(str(tmp_path))
    data = json.loads(sp.read_text())
    # 原有 key 原样保留
    assert data["permissions"] == {"allow": ["Bash"]}
    assert data["model"] == "claude-opus-4-8"
    # 原有 hook 保留 + buddy 追加到末尾
    assert data["hooks"]["PreToolUse"][0]["matcher"] == "Bash"
    assert ic.is_buddy_command(
        data["hooks"]["PreToolUse"][-1]["hooks"][0]["command"],
        tmp_path / ic.HOOK_HELPER_NAME,
    )
    # 备份存在
    assert r.backup_path and Path(r.backup_path).exists()


def test_apply_install_idempotent(tmp_path):
    ic.apply_install(str(tmp_path), create=True)
    r2 = ic.apply_install(str(tmp_path))
    assert r2.added_hook_events == []
    assert r2.statusline_action == "idempotent"
    data = json.loads((tmp_path / ic.SETTINGS_NAME).read_text())
    for ev in ic.HOOK_EVENTS:
        assert len(data["hooks"][ev]) == 1  # 没重复添加


def test_apply_install_statusline_conflict_aborts(tmp_path):
    sp = tmp_path / ic.SETTINGS_NAME
    sp.write_text(
        json.dumps({"statusLine": {"type": "command", "command": "/other/statusline"}}),
        encoding="utf-8",
    )
    with pytest.raises(ic.InstallError, match="statusLine"):
        ic.apply_install(str(tmp_path))
    # 原文件未被改写
    data = json.loads(sp.read_text())
    assert data["statusLine"]["command"] == "/other/statusline"


def test_apply_install_force_statusline(tmp_path):
    sp = tmp_path / ic.SETTINGS_NAME
    sp.write_text(
        json.dumps({"statusLine": {"type": "command", "command": "/other/statusline"}}),
        encoding="utf-8",
    )
    r = ic.apply_install(str(tmp_path), force_statusline=True)
    assert r.statusline_action == "set"
    data = json.loads(sp.read_text())
    assert ic.is_buddy_command(
        data["statusLine"]["command"], tmp_path / ic.STATUSLINE_HELPER_NAME
    )


def test_apply_install_bad_json_aborts(tmp_path):
    sp = tmp_path / ic.SETTINGS_NAME
    sp.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(ic.InstallError, match="解析失败"):
        ic.apply_install(str(tmp_path))


def test_apply_install_settings_path_outside_claude_dir(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    sp = other / "mysettings.json"
    sp.write_text("{}", encoding="utf-8")
    r = ic.apply_install(str(tmp_path), settings_path=str(sp))
    assert Path(r.settings_path) == sp
    data = json.loads(sp.read_text())
    assert "hooks" in data
