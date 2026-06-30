"""pytest 共享夹具与初始化。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 保险：即便未 editable install 也能导入源码
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest


@pytest.fixture(autouse=True)
def _clean_buddy_env(monkeypatch):
    """每个测试前清除 BUDDY_* 环境变量，避免污染配置测试。"""
    for k in list(os.environ):
        if k.startswith("BUDDY_"):
            monkeypatch.delenv(k, raising=False)
