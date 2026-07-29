"""statusLine 渲染：读 Claude Code statusLine payload -> 彩色单行 stdout。

纯标准库实现，既作为包内模块供 adapter import（测试 / doctor），又可作为独立脚本
被工程自带的 vendor python 直接执行（``python render_statusline.py``）--不依赖
系统 python、不依赖第三方包。statusLine helper 调用它渲染状态栏文本，避免在无原
statusLine 时状态栏空白。

字段（容错，缺失则省略对应段，不让状态栏出现 null）：
- ``model.display_name`` / ``model.id``   模型名
- ``context_window.used_percentage``       上下文百分比（早期可能为 null）
- ``effort.level``                         reasoning effort（low/medium/high/xhigh/max，
                                           旧版 Claude Code 或不支持 effort 的模型缺失）
- ``cost.total_cost_usd``                  计费

样式（ANSI 256 色）::

    Opus 4.8  ▕██████░░░░▕ 35%  ⚡ high  $0.42

进度条已用部分固定绿色，未用灰色；不随百分比变色。
"""

from __future__ import annotations

import json
import sys
from typing import Any, Optional


# ---- ANSI 256 色 ----
def _fg(n: int) -> str:
    return f"\033[38;5;{n}m"


BOLD = "\033[1m"
RESET = "\033[0m"

C_MODEL = _fg(141)       # 紫：模型名
C_BAR_USED = _fg(46)     # 亮绿：进度条已用（固定绿，不随百分比变色）
C_BAR_EMPTY = _fg(240)   # 灰：进度条未用
C_PCT = _fg(46)          # 亮绿：百分比（与进度条已用一致）
C_COST = _fg(34)         # 深绿：计费

EFFORT_COLOR = {
    "low": _fg(240),     # 灰
    "medium": _fg(38),   # 青
    "high": _fg(220),    # 黄
    "xhigh": _fg(208),   # 橙
    "max": _fg(196),     # 红
}

BAR_WIDTH = 10


def _safe_get(container: Any, key: str) -> Any:
    if isinstance(container, dict):
        return container.get(key)
    return None


def _coerce_pct(value: Any) -> Optional[float]:
    """只接受真数值（拒绝 None/bool/str），夹到 [0,100]。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(0.0, min(100.0, float(value)))


def _bar(pct: Optional[float]) -> str:
    """10 格进度条：已用绿、未用灰；pct 为 None 时全灰（表示未知）。"""
    if pct is None:
        return f"{C_BAR_EMPTY}{'░' * BAR_WIDTH}{RESET}"
    filled = round(pct / 100 * BAR_WIDTH)
    return (
        f"{C_BAR_USED}{'█' * filled}{RESET}"
        f"{C_BAR_EMPTY}{'░' * (BAR_WIDTH - filled)}{RESET}"
    )


def _pct_text(pct: Optional[float]) -> str:
    if pct is None:
        return ""
    return f"{C_PCT}{pct:g}%{RESET}"


def _effort(level: Any) -> str:
    if not isinstance(level, str) or not level:
        return ""
    color = EFFORT_COLOR.get(level, _fg(245))
    return f"{color}⚡ {level}{RESET}"


def _cost(usd: Any) -> str:
    if usd is None or isinstance(usd, bool):
        return ""
    try:
        return f"{C_COST}${float(usd):.2f}{RESET}"
    except (TypeError, ValueError):
        return ""


def _model(payload: dict) -> str:
    model = _safe_get(payload, "model")
    name = _safe_get(model, "display_name") or _safe_get(model, "id")
    if not isinstance(name, str) or not name:
        return ""
    return f"{BOLD}{C_MODEL}{name}{RESET}"


def render_statusline(payload: Any) -> str:
    """渲染彩色 statusLine 单行。payload 非 dict 或字段全缺时返回空串。"""
    if not isinstance(payload, dict):
        return ""

    parts: list[str] = []

    model = _model(payload)
    if model:
        parts.append(model)

    pct = _coerce_pct(_safe_get(_safe_get(payload, "context_window"), "used_percentage"))
    bar_segment = f"{_bar(pct)} {_pct_text(pct)}".rstrip()
    if bar_segment:
        parts.append(bar_segment)

    effort = _effort(_safe_get(_safe_get(payload, "effort"), "level"))
    if effort:
        parts.append(effort)

    cost = _cost(_safe_get(_safe_get(payload, "cost"), "total_cost_usd"))
    if cost:
        parts.append(cost)

    return "  ".join(parts)


def main() -> int:
    """脚本入口：读 stdin JSON -> 渲染 -> stdout。任何异常都静默 exit 0（不连累 helper）。

    Windows 默认 stdin/stdout 编码是 locale（中文系统 cp936/GBK），无法编码/解码
    █░ 等 unicode 块字符 -> 强制 utf-8（Claude Code 按 utf-8 传/收 statusLine payload）。
    """
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    sys.stdout.write(render_statusline(payload) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
