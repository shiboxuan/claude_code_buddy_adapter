"""install-claude：生成 helper 脚本 + 合并写入 Claude Code settings.json。

对齐 system-design §Claude Code 配置方式、protocol §3.1（helper exit 0）。

设计要点（ADP-P9-T02）：
- **追加写入**：只动 ``statusLine`` / ``hooks`` 两个 key；hooks 内只把 buddy 的
  matcher-group 追加到对应 event 的 list 末尾，绝不替换整个 hooks dict、绝不
  删除用户已有的其他 event 或 matcher-group。settings.json 其余 key 原样保留。
- **幂等**：重复 ``--write`` 不重复添加（按 helper 路径匹配检测已存在的 buddy entry）。
- **备份**：写回前先复制到 ``settings.json.bak.<ts>``，不覆盖已有备份。
- **找不到配置文件**：默认中断并提示用 ``--claude-dir`` / ``--settings-path`` 指定位置，
  或加 ``--create`` 新建；不自作主张创建，避免搞乱环境。
- **statusLine 冲突**：Claude Code 只允许一个 statusLine。检测到非 buddy 的 statusLine
  时中断提示，需 ``--force-statusline`` 才覆盖；覆盖时原 command 存进 sidecar
  (``.claude-code-buddy-statusline.orig``)，helper 透传其 stdout，原状态栏显示不丢失。
- **statusLine helper 输出 stdout**：Claude Code 用 command 的 stdout 作状态栏内容。
  helper 既把 payload POST 给 adapter，又输出文本给 Claude Code 显示（有原 command 就
  透传，否则从 payload 自生成 ``model | ctx N%``），避免状态栏空白。
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

ADAPTER_HOST = "127.0.0.1"
ADAPTER_PORT = 8765

DEFAULT_CLAUDE_DIR = Path.home() / ".claude"
STATUSLINE_HELPER_NAME = "claude-code-buddy-statusline"
# sidecar：单行存「被 buddy 接管的原 statusLine command」。helper 读它决定透传原输出还是自生成。
STATUSLINE_ORIG_NAME = ".claude-code-buddy-statusline.orig"
HOOK_HELPER_NAME = "claude-code-buddy-hook"
SETTINGS_NAME = "settings.json"

# install-claude 注册的 hook 事件（MVP 最小集，对齐 reducer 状态机）
HOOK_EVENTS = [
    "SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
    "PermissionRequest", "Notification", "Stop", "StopFailure",
    "Elicitation", "ElicitationResult", "SessionEnd",
]
HOOK_EVENTS_WITH_MATCHER = {"PreToolUse", "PostToolUse"}


class InstallError(Exception):
    """安装流程中可预期的失败（配置缺失/冲突/解析失败），CLI 层据此返回非 0。"""


@dataclass
class InstallResult:
    claude_dir: str
    settings_path: str
    statusline_helper: str
    hook_helper: str
    added_hook_events: list[str] = field(default_factory=list)
    statusline_action: str = ""  # "set" | "idempotent" | "kept_existing"
    backup_path: Optional[str] = None
    created: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "claude_dir": self.claude_dir,
            "settings_path": self.settings_path,
            "statusline_helper": self.statusline_helper,
            "hook_helper": self.hook_helper,
            "added_hook_events": self.added_hook_events,
            "statusline_action": self.statusline_action,
            "backup_path": self.backup_path,
            "created": self.created,
        }


# ---- 路径解析 ----
def resolve_claude_dir(claude_dir: Optional[str] = None) -> Path:
    """优先级：显式参数 > $CLAUDE_CONFIG_DIR > ~/.claude。"""
    if claude_dir:
        return Path(claude_dir).expanduser()
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    if env:
        return Path(env).expanduser()
    return DEFAULT_CLAUDE_DIR


def resolve_settings_path(
    claude_dir: Optional[str] = None, settings_path: Optional[str] = None
) -> Path:
    if settings_path:
        return Path(settings_path).expanduser()
    return resolve_claude_dir(claude_dir) / SETTINGS_NAME


# ---- helper 脚本 ----
# statusLine 自生成行用的 python 片段（无单引号，可整体塞进 bash 单引号字符串）。
# 从 payload 取 model.display_name 与 context_window.used_percentage，拼成 "model | ctx N%"。
_STATUSLINE_PY = (
    "import sys, json\n"
    "try:\n"
    "    d = json.load(sys.stdin)\n"
    '    m = (d.get("model") or {}).get("display_name") or (d.get("model") or {}).get("id") or ""\n'
    '    cw = (d.get("context_window") or {}).get("used_percentage")\n'
    '    parts = [p for p in [m, (f"ctx {cw:g}%" if cw is not None else None)] if p]\n'
    '    print(" | ".join(parts) if parts else "")\n'
    "except Exception:\n"
    "    pass\n"
)


def statusline_helper_script(sidecar_path: Path) -> str:
    """statusLine helper 脚本：读 stdin -> POST adapter -> 输出 statusline 文本 -> exit 0。

    Claude Code 用 command 的 stdout 作为状态栏内容，故必须输出文本（否则状态栏空白）：
    - sidecar 存在且非空（被 buddy 接管的原 statusLine command）-> 把 payload 透传给原
      command，输出其 stdout；
    - 否则 -> 从 payload 自生成一行（``model | ctx N%``）。
    POST 仍 fire-and-forget，不影响 adapter 采集。
    """
    return (
        "#!/usr/bin/env bash\n"
        "# claude-code-buddy-statusline: 读 stdin -> POST adapter -> 输出 statusline 文本 -> exit 0\n"
        "payload=$(cat)\n"
        f'curl -s -m 2 -o /dev/null -X POST -H "Content-Type: application/json" \\\n'
        f'  -d "$payload" http://{ADAPTER_HOST}:{ADAPTER_PORT}/v1/claude/statusline || true\n'
        f'ORIG_FILE="{sidecar_path}"\n'
        'if [ -s "$ORIG_FILE" ]; then\n'
        '  orig_cmd=$(cat "$ORIG_FILE")\n'
        "  printf '%s' \"$payload\" | sh -c \"$orig_cmd\" 2>/dev/null || true\n"
        "else\n"
        "  printf '%s' \"$payload\" | python3 -c '\n"
        + _STATUSLINE_PY
        + "' 2>/dev/null || true\n"
        "fi\n"
        "exit 0\n"
    )


def hook_helper_script() -> str:
    return (
        "#!/usr/bin/env bash\n"
        "# claude-code-buddy-hook: 读 stdin -> POST adapter -> exit 0\n"
        "payload=$(cat)\n"
        f'curl -s -m 2 -o /dev/null -X POST -H "Content-Type: application/json" \\\n'
        f'  -d "$payload" http://{ADAPTER_HOST}:{ADAPTER_PORT}/v1/claude/hook || true\n'
        "exit 0\n"
    )


def _chmod_exec(path: Path) -> None:
    try:
        path.chmod(0o755)
    except OSError:
        pass


def write_helpers(claude_dir: Path) -> tuple[Path, Path]:
    """写两个 helper 脚本到 claude_dir 并设可执行权限，返回 (statusline_path, hook_path)。"""
    claude_dir = Path(claude_dir)
    claude_dir.mkdir(parents=True, exist_ok=True)
    sl = claude_dir / STATUSLINE_HELPER_NAME
    hk = claude_dir / HOOK_HELPER_NAME
    sl.write_text(statusline_helper_script(claude_dir / STATUSLINE_ORIG_NAME), encoding="utf-8")
    hk.write_text(hook_helper_script(), encoding="utf-8")
    _chmod_exec(sl)
    _chmod_exec(hk)
    return sl, hk


def write_statusline_orig(claude_dir: Path, orig_cmd: Optional[str]) -> None:
    """写/清 sidecar：存被 buddy 接管的原 statusLine command。

    ``orig_cmd`` 非空 -> 单行写入（helper 透传其 stdout，保留原状态栏显示）；
    为空 -> 删除 sidecar（helper 走自生成分支）。文件不存在时删除静默忽略。
    """
    sidecar = Path(claude_dir) / STATUSLINE_ORIG_NAME
    if not orig_cmd:
        try:
            sidecar.unlink()
        except FileNotFoundError:
            pass
        return
    sidecar.write_text(orig_cmd, encoding="utf-8")


# ---- settings 片段 ----
def settings_fragment(statusline_path: Path, hook_path: Path) -> dict[str, Any]:
    """构造 buddy 的 statusLine + hooks 片段（command 用绝对路径）。"""
    hooks: dict[str, list] = {}
    for ev in HOOK_EVENTS:
        entry: dict[str, Any] = {"hooks": [{"type": "command", "command": str(hook_path)}]}
        if ev in HOOK_EVENTS_WITH_MATCHER:
            entry["matcher"] = "*"
        hooks[ev] = [entry]
    return {
        "statusLine": {
            "type": "command",
            "command": str(statusline_path),
            "refreshInterval": 2,
        },
        "hooks": hooks,
    }


# ---- 合并逻辑 ----
def is_buddy_command(cmd: Any, helper_path: Path) -> bool:
    """判断一个 hook/statusLine command 是否指向 buddy helper。

    容忍 ``~``/``$HOME`` 前缀与绝对路径混用：展开后比较，或末尾段匹配文件名。
    """
    if not isinstance(cmd, str) or not cmd:
        return False
    target = str(helper_path)
    expanded = os.path.expanduser(cmd).replace("$HOME", str(Path.home()))
    if expanded == target:
        return True
    # 容忍 cmd 写成 ~/... 而 helper_path 是绝对路径
    if expanded == os.path.expanduser(target):
        return True
    return cmd.rstrip("/").endswith("/" + helper_path.name) and helper_path.name in (
        STATUSLINE_HELPER_NAME, HOOK_HELPER_NAME,
    )


def _entry_has_buddy(entry: Any, helper_path: Path) -> bool:
    """单个 matcher-group entry 的 hooks 列表里是否含 buddy command。"""
    if not isinstance(entry, dict):
        return False
    hooks = entry.get("hooks")
    if not isinstance(hooks, list):
        return False
    for h in hooks:
        if isinstance(h, dict) and is_buddy_command(h.get("command"), helper_path):
            return True
    return False


def _event_list_has_buddy(entries: Any, helper_path: Path) -> bool:
    if not isinstance(entries, list):
        return False
    return any(_entry_has_buddy(e, helper_path) for e in entries)


def merge_hooks(
    existing: Any, fragment_hooks: dict[str, list], hook_helper: Path
) -> tuple[dict[str, list], list[str]]:
    """把 buddy hook entries 追加合并进 existing hooks。

    - existing 非 dict 时视为空 dict（不抛异常，容错）。
    - 对每个 buddy event：若该 event 的 list 已含 buddy entry -> 跳过（幂等）；
      否则把 fragment 的 matcher-group 追加到 list 末尾。
    - 绝不改动其他 event / 其他 matcher-group。
    返回 (merged_hooks, added_event_names)。
    """
    merged: dict[str, list] = dict(existing) if isinstance(existing, dict) else {}
    added: list[str] = []
    for ev, frag_entries in fragment_hooks.items():
        cur = merged.get(ev)
        if not isinstance(cur, list):
            cur = []
            merged[ev] = cur
        if _event_list_has_buddy(cur, hook_helper):
            continue  # 幂等
        cur.extend(frag_entries)
        added.append(ev)
    return merged, added


def merge_statusline(
    existing: Any,
    fragment_statusline: dict[str, Any],
    statusline_helper: Path,
    force: bool,
) -> tuple[dict[str, Any], str]:
    """合并 statusLine。返回 (new_statusline, action)。

    action:
    - ``set``：写入 buddy statusLine（原为空或 force 覆盖）
    - ``idempotent``：已是 buddy statusLine，保留
    - ``conflict``：存在非 buddy statusLine 且未 force，调用方应中断
    """
    if not isinstance(existing, dict) or not existing:
        return dict(fragment_statusline), "set"
    if is_buddy_command(existing.get("command"), statusline_helper):
        return existing, "idempotent"
    if force:
        return dict(fragment_statusline), "set"
    return existing, "conflict"


# ---- 备份 ----
def backup_settings(settings_path: Path) -> Path:
    """复制到 settings.json.bak.<ts>，不覆盖已有备份。"""
    ts = time.strftime("%Y%m%d-%H%M%S")
    bak = settings_path.with_name(f"{settings_path.name}.bak.{ts}")
    idx = 0
    while bak.exists():
        idx += 1
        bak = settings_path.with_name(f"{settings_path.name}.bak.{ts}.{idx}")
    shutil.copy2(settings_path, bak)
    return bak


# ---- 主流程 ----
def apply_install(
    claude_dir: Optional[str] = None,
    *,
    settings_path: Optional[str] = None,
    create: bool = False,
    force_statusline: bool = False,
) -> InstallResult:
    """执行 install-claude --write 的完整流程。

    1. 定位 settings.json（找不到则按 create 决定中断/新建）；2. 读现有 JSON；
    3. 备份；4. 追加合并 hooks + 处理 statusLine（冲突在此中断，不落 helper）；
    5. 写 helper 脚本；6. 写 statusLine sidecar；7. 写回 settings.json。
    任何可预期失败抛 :class:`InstallError`。
    """
    cdir = resolve_claude_dir(claude_dir)
    spath = resolve_settings_path(claude_dir, settings_path)

    created = False
    if not spath.exists():
        if not create:
            raise InstallError(
                f"找不到 Claude Code 配置文件: {spath}\n"
                f"  请用 --claude-dir <dir> 或 --settings-path <file> 指定配置文件位置；\n"
                f"  若确认要新建，请加 --create。"
            )
        spath.parent.mkdir(parents=True, exist_ok=True)
        spath.write_text("{}", encoding="utf-8")
        created = True

    # 先读 settings：statusLine 冲突要在落 helper 前中断，避免遗留半成品 helper
    try:
        data = json.loads(spath.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        raise InstallError(
            f"settings.json 解析失败 ({spath}): {e}\n"
            f"  请手动修复 JSON 语法后重试。"
        ) from e
    if not isinstance(data, dict):
        raise InstallError(f"settings.json 顶层不是 JSON object: {spath}")

    backup_path = None if created else backup_settings(spath)

    # helper 绝对路径（fragment/merge 用；文件稍后落）
    sl_path = cdir / STATUSLINE_HELPER_NAME
    hk_path = cdir / HOOK_HELPER_NAME

    frag = settings_fragment(sl_path, hk_path)
    merged_hooks, added_events = merge_hooks(data.get("hooks"), frag["hooks"], hk_path)
    new_statusline, sl_action = merge_statusline(
        data.get("statusLine"), frag["statusLine"], sl_path, force_statusline
    )
    if sl_action == "conflict":
        raise InstallError(
            f"settings.json 已有非 buddy 的 statusLine: {data.get('statusLine')!r}\n"
            f"  Claude Code 只允许一个 statusLine。请用 --force-statusline 覆盖"
            f"（buddy 会把原 command 存进 sidecar 并透传其输出，不丢失原状态栏显示），"
            f"或手动合并。原文件未改动（备份: {backup_path}）。"
        )

    # 冲突已排除，至此落 helper（找不到配置且无 --create 时上面已中断，不会到这里）
    sl_path, hk_path = write_helpers(cdir)

    # sidecar：force 覆盖非 buddy -> 保留原 command（透传其输出）；原无 statusLine -> 清空（自生成）；
    # idempotent -> 不动（保留首次安装时记下的原 command）
    existing_sl = data.get("statusLine")
    if sl_action == "set":
        if isinstance(existing_sl, dict) and existing_sl and not is_buddy_command(
            existing_sl.get("command"), sl_path
        ):
            write_statusline_orig(cdir, existing_sl.get("command"))
        else:
            write_statusline_orig(cdir, None)

    data["hooks"] = merged_hooks
    data["statusLine"] = new_statusline
    spath.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    return InstallResult(
        claude_dir=str(cdir),
        settings_path=str(spath),
        statusline_helper=str(sl_path),
        hook_helper=str(hk_path),
        added_hook_events=added_events,
        statusline_action=sl_action,
        backup_path=str(backup_path) if backup_path else None,
        created=created,
    )
