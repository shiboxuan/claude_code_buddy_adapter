"""字段限长 / 截断工具：repo basename、路径 tail、session_id_short、像素等价宽度截断。

对齐 protocol §2.5 + system-design §UI 设计「小屏幕布局原则」：
- 展示文本按**像素等价宽度**限长，不按字符数。
- 中文 / 全角字符按 2 宽，ASCII 半角按 1 宽。
- repo 取 basename；路径取 tail segment；session_id_short 取前 6–8 位。
- 截断由 adapter 预先完成（firmware 只做最后防线）。
"""

from __future__ import annotations

import unicodedata
from typing import Optional

# 像素等价宽度限长（protocol §2.5）
TITLE_MAX_WIDTH = 20
LINE_MAX_WIDTH = 28
SESSION_ID_SHORT_LEN = 8  # 取前 6–8 位，这里用 8


def char_width(ch: str) -> int:
    """单字符显示宽度：中文/全角(W/F) 算 2，其余算 1。"""
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 2
    return 1


def display_width(s: str) -> int:
    """字符串的像素等价宽度。"""
    return sum(char_width(ch) for ch in s)


def truncate_width(s: Optional[str], max_width: int, ellipsis: str = "") -> str:
    """按显示宽度截断 ``s`` 至不超过 ``max_width``。

    超限时截断；``ellipsis`` 的宽度计入 ``max_width``（如 "…"）。
    None / 空串返回空串。
    """
    if not s:
        return ""
    if display_width(s) <= max_width:
        return s
    ell_w = display_width(ellipsis) if ellipsis else 0
    limit = max_width - ell_w
    out: list[str] = []
    w = 0
    for ch in s:
        cw = char_width(ch)
        if w + cw > limit:
            break
        out.append(ch)
        w += cw
    return "".join(out) + (ellipsis if ellipsis else "")


def repo_basename(repo: object) -> Optional[str]:
    """repo 取 basename：支持 dict{name}、str（取最后一段）、空值返回 None。"""
    if isinstance(repo, dict):
        name = repo.get("name")
        if name:
            return str(name)
        return None
    if isinstance(repo, str) and repo:
        return repo.rstrip("/").rsplit("/", 1)[-1] or repo
    return None


def cwd_tail(cwd: Optional[str]) -> Optional[str]:
    """路径取 tail segment（最后一级目录）。"""
    if not cwd:
        return None
    return cwd.rstrip("/").rsplit("/", 1)[-1] or cwd


def session_id_short(session_id: Optional[str], n: int = SESSION_ID_SHORT_LEN) -> Optional[str]:
    """session_id 取前 ``n`` 位（默认 8，落在 6–8 区间）。"""
    if not session_id:
        return None
    return session_id[:n]
