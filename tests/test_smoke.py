"""冒烟测试：包与子包可导入，发布版本定义保持一致。"""

from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_release_version_is_0_1_4():
    import claude_code_buddy_adapter

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")

    assert claude_code_buddy_adapter.__version__ == "0.1.4"
    assert pyproject["project"]["version"] == "0.1.4"
    assert 'T="v0.1.4-ci.${{ github.run_number }}"' in workflow


def test_import_package():
    import claude_code_buddy_adapter

    assert claude_code_buddy_adapter.__version__
    assert claude_code_buddy_adapter.PROTOCOL_VERSION == "ccb-serial-v1"


def test_import_subpackages():
    import claude_code_buddy_adapter.claude
    import claude_code_buddy_adapter.config
    import claude_code_buddy_adapter.cli
    import claude_code_buddy_adapter.debug
    import claude_code_buddy_adapter.device
    import claude_code_buddy_adapter.logging_setup
    import claude_code_buddy_adapter.metrics
    import claude_code_buddy_adapter.receiver
    import claude_code_buddy_adapter.session

    # 子包 __init__.py 保持空，仅验证可导入
    assert claude_code_buddy_adapter.claude is not None
