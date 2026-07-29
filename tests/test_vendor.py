"""vendor python / 渲染脚本释放逻辑测试。

开发模式跑：无真实内嵌 vendor python zip，用 monkeypatch 模拟。跨平台路径用 sys.platform
分支构造假 stub，打成 zip（模拟 nuitka 内嵌的单文件数据）。
"""

from __future__ import annotations

import sys
from pathlib import Path

from claude_code_buddy_adapter import vendor


def test_extract_render_script_writes_runnable_script(tmp_path):
    dst = vendor.extract_render_script(tmp_path)
    assert dst.exists()
    assert dst.name == vendor.RENDER_SCRIPT_NAME
    text = dst.read_text(encoding="utf-8")
    assert "def render_statusline" in text
    assert "if __name__" in text  # 可被 vendor python 直接执行


def test_resolve_renderer_dev_mode_uses_sys_executable(tmp_path, monkeypatch):
    monkeypatch.setattr(vendor, "_embedded_vendor_zip", lambda: None)
    py_bin, script = vendor.resolve_renderer(tmp_path)
    assert Path(py_bin).name == Path(sys.executable).name  # 回退 sys.executable
    assert vendor.RENDER_SCRIPT_NAME in script
    assert "\\" not in py_bin  # 正斜杠
    assert "\\" not in script


def test_extract_vendor_python_dev_mode_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(vendor, "_embedded_vendor_zip", lambda: None)
    assert vendor.extract_vendor_python(tmp_path) is None


def _make_fake_vendor_python(src_root: Path) -> Path:
    """构造假的内嵌 vendor python zip（含 stub 解释器），返回 zip 路径。"""
    import shutil as _sh

    py_dir = src_root / "vendor" / "python"
    if sys.platform == "win32":
        py_dir.mkdir(parents=True)
        (py_dir / "python.exe").write_text("echo fake-python\n", encoding="utf-8")
    else:
        (py_dir / "bin").mkdir(parents=True)
        exe = py_dir / "bin" / "python3"
        exe.write_text("#!/usr/bin/env bash\necho fake-python\n", encoding="utf-8")
        exe.chmod(0o755)
    _sh.make_archive(str(src_root / "vendor" / "python"), "zip", str(src_root / "vendor"), "python")
    return src_root / "vendor" / "python.zip"


def test_extract_vendor_python_releases_from_embedded(tmp_path, monkeypatch):
    zip_path = _make_fake_vendor_python(tmp_path / "embedded")
    monkeypatch.setattr(vendor, "_embedded_vendor_zip", lambda: zip_path)

    claude_dir = tmp_path / "claude"
    claude_dir.mkdir()
    py_bin = vendor.extract_vendor_python(claude_dir)
    assert py_bin is not None
    assert py_bin.exists()
    # 释放到 claude_dir/vendor/python 下（win python.exe 在该层，unix 在 bin/ 下）
    assert (claude_dir / "vendor" / "python") in py_bin.parents
    vf = claude_dir / "vendor" / vendor.VERSION_FILE_NAME
    assert vf.read_text(encoding="utf-8").strip() == vendor.VENDOR_DATA_VERSION


def test_extract_vendor_python_idempotent_skips_extract(tmp_path, monkeypatch):
    zip_path = _make_fake_vendor_python(tmp_path / "embedded")
    monkeypatch.setattr(vendor, "_embedded_vendor_zip", lambda: zip_path)
    claude_dir = tmp_path / "claude"
    claude_dir.mkdir()
    vendor.extract_vendor_python(claude_dir)  # 首次解压

    calls = []
    orig = vendor.zipfile.ZipFile

    def spy(*a, **k):
        calls.append(a)
        return orig(*a, **k)

    monkeypatch.setattr(vendor.zipfile, "ZipFile", spy)
    bin2 = vendor.extract_vendor_python(claude_dir)  # 版本匹配，应跳过解压
    assert calls == []
    assert bin2 is not None and bin2.exists()


def test_extract_vendor_python_re_releases_on_version_change(tmp_path, monkeypatch):
    zip_path = _make_fake_vendor_python(tmp_path / "embedded")
    monkeypatch.setattr(vendor, "_embedded_vendor_zip", lambda: zip_path)
    claude_dir = tmp_path / "claude"
    claude_dir.mkdir()
    vendor.extract_vendor_python(claude_dir)

    monkeypatch.setattr(vendor, "VENDOR_DATA_VERSION", "999")
    bin2 = vendor.extract_vendor_python(claude_dir)
    assert bin2 is not None and bin2.exists()
    vf = claude_dir / "vendor" / vendor.VERSION_FILE_NAME
    assert vf.read_text(encoding="utf-8").strip() == "999"


def test_resolve_renderer_uses_vendor_python_when_present(tmp_path, monkeypatch):
    zip_path = _make_fake_vendor_python(tmp_path / "embedded")
    monkeypatch.setattr(vendor, "_embedded_vendor_zip", lambda: zip_path)
    claude_dir = tmp_path / "claude"
    claude_dir.mkdir()
    py_bin, script = vendor.resolve_renderer(claude_dir)
    # 用的是释放到 claude_dir 下的 vendor python，不是回退的 sys.executable
    assert py_bin.endswith("python.exe" if sys.platform == "win32" else "python3")
    assert str(claude_dir).replace("\\", "/") in py_bin
    assert vendor.RENDER_SCRIPT_NAME in script
