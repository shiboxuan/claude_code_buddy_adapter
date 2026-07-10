"""PyCharm / 命令行入口：直接运行本文件即可拉起 adapter。

等价于 ``python -m claude_code_buddy_adapter.cli run`` 或 ``buddy-adapter run``。
- 无参数时默认 ``run`` 子命令（启动 HTTP receiver + serial bridge）。
- 也可透传子命令：``python run.py [run|doctor|install-claude|replay|dump-state] [args]``

PyCharm 用法：右键本文件 -> Run 'run'（Script path 方式，无需配 Module name）。
本文件为本地开发便利入口，不随包打包（``pyproject.toml`` 只打包 ``claude_code_buddy_adapter*``）；
分发给他人的正式入口仍是 ``buddy-adapter`` 命令。
"""

import sys
from pathlib import Path

# 兜底：确保项目根在 sys.path（PyCharm Script path 通常已含，此处防止 cwd 异常）
_ROOT = str(Path(__file__).resolve().parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from claude_code_buddy_adapter.cli import main


if __name__ == "__main__":
    if len(sys.argv) == 1:
        sys.argv = [sys.argv[0], "run"]  # 无参默认拉起 adapter
    raise SystemExit(main())
