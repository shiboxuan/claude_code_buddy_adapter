"""statusLine 渲染模块测试。

覆盖：完整 payload / 各字段缺失降级 / 进度条格数与固定绿色 / effort 各等级 /
null 百分比 / 非 dict 容错 / 脚本端到端（用当前 python 模拟 vendor python）。
"""

from __future__ import annotations

import io
import json
import pathlib
import subprocess
import sys

from claude_code_buddy_adapter import statusline_render as sr

FULL = {
    "model": {"id": "claude-opus-4-8", "display_name": "Opus 4.8"},
    "context_window": {"used_percentage": 35.5},
    "effort": {"level": "high"},
    "cost": {"total_cost_usd": 0.42},
}


# ---- 字段渲染 ----
def test_full_payload_renders_all_fields():
    out = sr.render_statusline(FULL)
    assert "Opus 4.8" in out
    assert "35.5%" in out
    assert "high" in out
    assert "$0.42" in out
    assert "█" in out and "░" in out
    assert "\033[" in out  # 含 ANSI 颜色码


def test_model_falls_back_to_id():
    out = sr.render_statusline({"model": {"id": "claude-opus-4-8"}})
    assert "claude-opus-4-8" in out


def test_missing_model_omitted():
    out = sr.render_statusline({"context_window": {"used_percentage": 10}})
    assert "Opus" not in out
    assert "claude-" not in out


def test_missing_cost_omitted():
    out = sr.render_statusline({"model": {"display_name": "Opus"}})
    assert "$" not in out


def test_missing_effort_omitted():
    out = sr.render_statusline({"model": {"display_name": "Opus"}, "context_window": {"used_percentage": 10}})
    assert "⚡" not in out
    assert "high" not in out


def test_effort_levels_all_rendered():
    for level in ["low", "medium", "high", "xhigh", "max"]:
        out = sr.render_statusline({"effort": {"level": level}})
        assert level in out


# ---- 进度条 ----
def test_progress_bar_proportional_half():
    out = sr.render_statusline({"context_window": {"used_percentage": 50}})
    assert out.count("█") == 5
    assert out.count("░") == 5


def test_progress_bar_full():
    out = sr.render_statusline({"context_window": {"used_percentage": 100}})
    assert out.count("█") == 10
    assert out.count("░") == 0


def test_progress_bar_zero():
    out = sr.render_statusline({"context_window": {"used_percentage": 0}})
    assert out.count("█") == 0
    assert out.count("░") == 10


def test_progress_bar_used_is_fixed_green():
    """已用部分固定绿色，不随百分比变红/黄。"""
    green = "\033[38;5;46m"
    for pct in (10, 50, 89, 95):
        out = sr.render_statusline({"context_window": {"used_percentage": pct}})
        assert green in out, f"pct={pct} 进度条已用应为绿色"


def test_progress_bar_empty_is_grey_not_green():
    green = "\033[38;5;46m"
    grey = "\033[38;5;240m"
    out = sr.render_statusline({"context_window": {"used_percentage": 30}})
    assert grey in out  # 未用部分灰色
    # 绿色段后紧跟 █，灰色段后紧跟 ░
    assert green + "█" in out
    assert grey + "░" in out


def test_null_percentage_shows_empty_bar_no_number():
    out = sr.render_statusline({"context_window": {"used_percentage": None}})
    assert out.count("░") == 10
    assert out.count("█") == 0
    assert "%" not in out


def test_missing_context_window_shows_empty_bar_no_number():
    out = sr.render_statusline({"model": {"display_name": "Opus"}})
    assert out.count("░") == 10
    assert "%" not in out


def test_percentage_clamped():
    out_over = sr.render_statusline({"context_window": {"used_percentage": 250}})
    assert out_over.count("█") == 10  # 夹到 100%
    out_neg = sr.render_statusline({"context_window": {"used_percentage": -5}})
    assert out_neg.count("█") == 0  # 夹到 0%


# ---- 容错 ----
def test_non_dict_payload_returns_empty():
    assert sr.render_statusline(None) == ""
    assert sr.render_statusline("str") == ""
    assert sr.render_statusline([]) == ""
    assert sr.render_statusline(123) == ""


def test_empty_dict_returns_empty_bar_only():
    out = sr.render_statusline({})
    assert out.count("░") == 10  # 只有全灰进度条
    assert "Opus" not in out and "$" not in out and "⚡" not in out


def test_cost_non_numeric_omitted():
    out = sr.render_statusline({"cost": {"total_cost_usd": "n/a"}})
    assert "$" not in out


# ---- main / 脚本入口 ----
def test_main_reads_stdin_json(capsys):
    old = sys.stdin
    sys.stdin = io.StringIO(json.dumps(FULL))
    try:
        assert sr.main() == 0
    finally:
        sys.stdin = old
    out = capsys.readouterr().out
    assert "Opus 4.8" in out
    assert "35.5%" in out


def test_main_bad_json_returns_zero(capsys):
    old = sys.stdin
    sys.stdin = io.StringIO("not json")
    try:
        assert sr.main() == 0
    finally:
        sys.stdin = old
    assert capsys.readouterr().out == ""


def test_main_can_run_as_standalone_script():
    """端到端：用当前 python 跑渲染脚本（模拟 vendor python 执行）。"""
    script = pathlib.Path(sr.__file__)
    out = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(FULL),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert out.returncode == 0
    assert "Opus 4.8" in out.stdout
    assert "35.5%" in out.stdout
    assert "high" in out.stdout
    assert "$0.42" in out.stdout
