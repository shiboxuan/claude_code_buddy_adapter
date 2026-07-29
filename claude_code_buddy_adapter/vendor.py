"""vendor python 解释器 + 渲染脚本的释放与定位。

打包后（nuitka onefile）的 buddy-adapter 自带 python-build-standalone 解释器与
渲染脚本源码（build.sh 下载 + ``--include-data-dir`` / ``--include-data-file`` 内嵌）。
install-claude 时把它们释放到 ``<claude_dir>/vendor/`` 下稳定路径，statusLine helper
直接调用--完全不依赖系统 python、也不依赖 onefile 解压临时目录。

开发模式（``pip install -e``，非 nuitka）下无内嵌 vendor python -> 回退用
``sys.executable`` 跑渲染脚本（开发机本就有 python）。

跨平台：vendor python 可执行路径 win 为 ``python.exe``、unix 为 ``bin/python3``；
注入 bash helper 时路径一律转正斜杠（Windows 反斜杠在 bash 命令名里不稳，正斜杠
win/bash 都识别；mac 路径本就无反斜杠，无影响）。
"""

from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path
from typing import Optional

# 升级 vendor python 或渲染脚本时递增，触发已部署环境重新释放（幂等跳过的判据）。
VENDOR_DATA_VERSION = "1"

VENDOR_DIR_NAME = "vendor"
VENDOR_PYTHON_DIR_NAME = "python"
VENDOR_PYTHON_ZIP_NAME = "python.zip"
RENDER_SCRIPT_NAME = "render_statusline.py"
VERSION_FILE_NAME = ".vendor_data_version"


def _embedded_vendor_zip() -> Optional[Path]:
    """定位 nuitka 内嵌的 vendor python zip（解压目录下 vendor/python.zip）。

    打包时 vendor python 打成 zip 作为单文件数据（``--include-data-files``）--避免
    ``--include-data-dir`` 在 onefile 下丢失 ``python.exe``（nuitka 对数据目录里的
    .exe 处理异常，会单独排除）。包内模块 ``__file__`` 指向解压目录里的
    ``claude_code_buddy_adapter/vendor.py``，故 ``../vendor/python.zip`` 即内嵌数据。
    开发模式（非编译）下该文件不存在 -> 返回 None。
    """
    here = Path(__file__).resolve()
    candidate = here.parent.parent / "vendor" / VENDOR_PYTHON_ZIP_NAME
    return candidate if candidate.is_file() else None


def _read_render_script_source() -> str:
    """读取包内 statusline_render.py 源码（nuitka 下作为 data file 打包进解压目录）。"""
    try:
        import importlib.resources as ir

        return (
            ir.files("claude_code_buddy_adapter")
            .joinpath("statusline_render.py")
            .read_text(encoding="utf-8")
        )
    except Exception:
        # 开发模式 fallback：同目录读源码
        return (Path(__file__).parent / "statusline_render.py").read_text(encoding="utf-8")


def _python_bin(base: Path) -> Path:
    """vendor python 可执行路径：win ``python.exe`` / unix ``bin/python3``。"""
    if sys.platform == "win32":
        return base / "python.exe"
    return base / "bin" / "python3"


def _version_ok(claude_dir: Path) -> bool:
    vf = claude_dir / VENDOR_DIR_NAME / VERSION_FILE_NAME
    try:
        return vf.read_text(encoding="utf-8").strip() == VENDOR_DATA_VERSION
    except OSError:
        return False


def _write_version(claude_dir: Path) -> None:
    vf = claude_dir / VENDOR_DIR_NAME / VERSION_FILE_NAME
    try:
        vf.write_text(VENDOR_DATA_VERSION, encoding="utf-8")
    except OSError:
        pass


def extract_vendor_python(claude_dir: Path) -> Optional[Path]:
    """把内嵌 vendor python zip 解压到 ``<claude_dir>/vendor/python/``，幂等。

    返回释放后的 python 可执行路径；开发模式无内嵌 vendor python 时返回 None
    （调用方回退 ``sys.executable``）。
    """
    src_zip = _embedded_vendor_zip()
    if src_zip is None:
        return None  # 开发模式

    claude_dir = Path(claude_dir)
    dst = claude_dir / VENDOR_DIR_NAME / VENDOR_PYTHON_DIR_NAME
    if _version_ok(claude_dir) and _python_bin(dst).exists():
        return _python_bin(dst)  # 已释放且版本匹配，跳过解压

    if dst.exists():
        shutil.rmtree(dst, ignore_errors=True)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(src_zip) as zf:
        zf.extractall(dst.parent)  # zip 内 python/ -> <dst.parent>/python = dst
    try:
        _python_bin(dst).chmod(0o755)
    except OSError:
        pass
    _write_version(claude_dir)
    return _python_bin(dst)


def extract_render_script(claude_dir: Path) -> Path:
    """释放渲染脚本到 ``<claude_dir>/vendor/render_statusline.py``。每次覆盖（体积小）。"""
    dst = Path(claude_dir) / VENDOR_DIR_NAME / RENDER_SCRIPT_NAME
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(_read_render_script_source(), encoding="utf-8")
    return dst


def _renderer_paths(
    claude_dir: Path, released_py_bin: Optional[Path] = None
) -> tuple[str, str]:
    """计算 ``(python_bin, render_script)`` 正斜杠路径，不释放。

    ``released_py_bin`` 非 None 时用它（已释放的 vendor python）；否则按
    ``_embedded_vendor_python_dir`` 决策--打包模式用 vendor python 释放后路径，
    开发模式回退 ``sys.executable``。渲染脚本恒在 ``<claude_dir>/vendor/``。
    """
    claude_dir = Path(claude_dir)
    if released_py_bin is not None:
        py_bin = released_py_bin
    elif _embedded_vendor_zip() is not None:
        py_bin = _python_bin(claude_dir / VENDOR_DIR_NAME / VENDOR_PYTHON_DIR_NAME)
    else:
        py_bin = Path(sys.executable)
    render_script = claude_dir / VENDOR_DIR_NAME / RENDER_SCRIPT_NAME
    return (_to_bash_path(py_bin), _to_bash_path(render_script))


def renderer_paths(claude_dir: Path) -> tuple[str, str]:
    """只算 helper 要用的路径，不释放（供 ``install-claude --print`` 预览）。"""
    return _renderer_paths(claude_dir)


def resolve_renderer(claude_dir: Path) -> tuple[str, str]:
    """释放 vendor python + 渲染脚本，返回 ``(python_bin, render_script)`` 路径。

    优先 vendor python；开发模式无 vendor python 时回退 ``sys.executable``。
    路径决策与 :func:`renderer_paths` 一致。
    """
    claude_dir = Path(claude_dir)
    py_bin = extract_vendor_python(claude_dir)  # None(开发) 或存在路径(打包)
    extract_render_script(claude_dir)
    return _renderer_paths(claude_dir, released_py_bin=py_bin)


def _to_bash_path(path: Path) -> str:
    """Windows 反斜杠 -> 正斜杠（bash 命令名/参数更稳，mac 无影响）。"""
    return str(path).replace("\\", "/")
