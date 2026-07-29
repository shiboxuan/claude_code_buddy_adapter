#!/usr/bin/env bash
# claude-code-buddy-adapter Nuitka 打包脚本。
#
# 本机架构构建：在 x86_64 机器上产出 x86_64 可执行，在 arm64 机器上产出 arm64 可执行。
# Nuitka 不支持交叉编译——要打特定架构的包，必须在对应架构的机器（或 CI runner）上跑本脚本。
#
# 用法：
#   pip install -e ".[build]"          # 装 nuitka + zstandard（一次性）
#   ./scripts/build.sh                 # 默认 onefile，产出 dist/buddy-adapter（单文件）
#   ./scripts/build.sh --mode standalone  # 产出 dist/buddy-adapter.dist/ 目录（启动更快）
#   PYTHON=python3.11 ./scripts/build.sh  # 指定解释器
#
# 产物入口等价于 `buddy-adapter`：无参默认拉起 adapter（run），也可透传子命令
# （doctor / install-claude / replay / dump-state）。

set -euo pipefail

# ---- 定位项目根 ----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

# ---- 默认参数 ----
MODE="onefile"
ENTRY="run.py"
OUTPUT_NAME="buddy-adapter"
OUTPUT_DIR="dist"

# vendor python（python-build-standalone）：随 onefile 内嵌，install-claude 时释放到
# ~/.claude/vendor/，statusLine helper 调用它跑渲染脚本，不依赖系统 python。
PBS_TAG="${PBS_TAG:-20260728}"
PBS_PY_VER="${PBS_PY_VER:-3.11.15}"

usage() {
  cat <<EOF
用法: $0 [选项]
  --mode onefile|standalone   打包模式（默认 onefile）
  --entry <file.py>           入口脚本（默认 run.py）
  --output-name <name>        产物文件名（默认 buddy-adapter）
  --help, -h                  显示帮助
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) MODE="$2"; shift 2 ;;
    --entry) ENTRY="$2"; shift 2 ;;
    --output-name) OUTPUT_NAME="$2"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "未知参数: $1" >&2; usage; exit 2 ;;
  esac
done

if [[ "$MODE" != "onefile" && "$MODE" != "standalone" ]]; then
  echo "错误: --mode 只能是 onefile 或 standalone" >&2
  exit 2
fi

# ---- Python 环境（>= 3.11）----
PY="${PYTHON:-python3}"
if ! "$PY" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>/dev/null; then
  echo "错误: 需要 Python >= 3.11（当前 $("$PY" --version 2>&1)）" >&2
  echo "  conda 用户: conda run -n claude_code_buddy_adapter $0" >&2
  exit 1
fi

# ---- 检查 nuitka ----
if ! "$PY" -c "import nuitka" 2>/dev/null; then
  echo "错误: 未安装 nuitka。请先执行:" >&2
  echo "  pip install -e \".[build]\"" >&2
  exit 1
fi

# ---- macOS: 检查 Xcode Command Line Tools（Nuitka 编译需要 clang）----
if [[ "$(uname)" == "Darwin" ]]; then
  if ! xcode-select -p >/dev/null 2>&1; then
    echo "错误: 未检测到 Xcode Command Line Tools（macOS 构建需要）" >&2
    echo "  请执行: xcode-select --install" >&2
    exit 1
  fi
fi

# ---- vendor python：下载 python-build-standalone 到 vendor/python（statusLine 渲染用）----
detect_pbs_target() {
  local os arch
  os="$(uname -s)"; arch="$(uname -m)"
  case "$os" in
    MINGW*|MSYS*|CYGWIN*) echo "x86_64-pc-windows-msvc" ;;
    Darwin)
      case "$arch" in
        arm64|aarch64) echo "aarch64-apple-darwin" ;;
        x86_64) echo "x86_64-apple-darwin" ;;
        *) echo "错误: 不支持的 mac 架构 $arch" >&2; return 1 ;;
      esac ;;
    Linux)
      case "$arch" in
        x86_64|amd64) echo "x86_64-unknown-linux-gnu" ;;
        aarch64|arm64) echo "aarch64-unknown-linux-gnu" ;;
        *) echo "错误: 不支持的 linux 架构 $arch" >&2; return 1 ;;
      esac ;;
    *) echo "错误: 不支持的平台 $os" >&2; return 1 ;;
  esac
}

ensure_vendor_python() {
  local target fname url vdir vzip tmp
  target="$(detect_pbs_target)" || exit 1
  fname="cpython-${PBS_PY_VER}+${PBS_TAG}-${target}-install_only.tar.gz"
  url="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/${fname}"
  vdir="$ROOT_DIR/vendor/python"
  vzip="$ROOT_DIR/vendor/python.zip"
  if [ -f "$vzip" ]; then
    echo "==> vendor python zip 已就位: $vzip（删除可强制重下）"
    return 0
  fi
  echo "==> 下载 vendor python: $fname"
  rm -rf "$ROOT_DIR/vendor"
  mkdir -p "$ROOT_DIR/vendor"
  tmp="$(mktemp -d)"
  if ! curl -sL --fail -o "$tmp/$fname" "$url"; then
    echo "错误: 下载 vendor python 失败: $url" >&2
    echo "  可用 PBS_TAG / PBS_PY_VER 环境变量覆盖版本。" >&2
    rm -rf "$tmp"; exit 1
  fi
  tar -xzf "$tmp/$fname" -C "$ROOT_DIR/vendor"
  rm -rf "$tmp"
  if [ ! -d "$vdir" ]; then
    echo "错误: 解压后未找到 $vdir" >&2; exit 1
  fi
  # 打成 zip 作为单文件数据打包（--include-data-files），避免 --include-data-dir 在
  # onefile 下丢失 python.exe（nuitka 对数据目录里的 .exe 处理异常）
  "$PY" -c "import shutil; shutil.make_archive('vendor/python', 'zip', 'vendor', 'python')"
  echo "==> vendor python zip: $(du -sh "$vzip" | awk '{print $1}')"
}

ensure_vendor_python

# ---- 清理旧产物 ----
rm -rf "$OUTPUT_DIR" "${ENTRY%.py}.build" "${OUTPUT_NAME}.build" "${OUTPUT_NAME}.dist"

# ---- 组装 Nuitka 参数 ----
NUITKA_ARGS=(
  --assume-yes-for-downloads
  --remove-output
  --output-dir="$OUTPUT_DIR"
  --output-filename="$OUTPUT_NAME"
  --main="$ENTRY"
  # fastapi/uvicorn/starlette/pydantic 动态 import 较多，显式整包编入，
  # 避免运行时 ModuleNotFoundError（uvicorn 用 importlib 加载 protocols/loops.auto 尤甚）
  --include-package=fastapi
  --include-package=starlette
  --include-package=pydantic
  --include-package-data=pydantic   # pydantic-core(Rust C 扩展) + 数据文件
  --include-package=uvicorn         # importlib 动态加载 protocols/loops.auto，必须显式
  --include-package=sniffio         # anyio 惰性 import，follow-imports 静态扫描扫不到
  --include-package=serial          # pyserial 的真实导入包名
  # anyio/h11/idna 等纯静态传递依赖由 --follow-imports 自动编入，无需显式 include。
  # vendor python（打成 zip 内嵌）+ 渲染脚本随 onefile 分发：install-claude 释放到
  # ~/.claude/vendor/，statusLine helper 调 vendor python 跑渲染脚本，不依赖系统 python。
  # 用 zip 单文件数据而非 --include-data-dir：onefile 下数据目录里的 python.exe 会被
  # nuitka 异常排除，zip 内的二进制不受影响。
  --include-data-files="$ROOT_DIR/vendor/python.zip"=vendor/python.zip
  --include-data-file="$ROOT_DIR/claude_code_buddy_adapter/statusline_render.py"=claude_code_buddy_adapter/statusline_render.py
)

if [[ "$MODE" == "onefile" ]]; then
  NUITKA_ARGS+=(--onefile)
  # 固定 onefile 解压目录到缓存，避免每次启动重新解压 vendor python（~30MB）
  NUITKA_ARGS+=('--onefile-tempdir-spec={CACHE_DIR}/claude-code-buddy-adapter')
else
  NUITKA_ARGS+=(--standalone)
fi

# ---- 构建 ----
echo "==> 架构: $(uname -m)   平台: $(uname -s)"
echo "==> 模式: $MODE   入口: $ENTRY   产物: $OUTPUT_DIR/$OUTPUT_NAME"
echo "==> nuitka $("$PY" -m nuitka --version 2>&1 | head -1)"
"$PY" -m nuitka "${NUITKA_ARGS[@]}"

# ---- 汇报 ----
if [[ "$MODE" == "onefile" ]]; then
  BIN="$OUTPUT_DIR/$OUTPUT_NAME"
else
  BIN="$OUTPUT_DIR/$OUTPUT_NAME.dist/$OUTPUT_NAME"
fi
# Windows 可执行文件需要 .exe 扩展名（macOS/Linux 不加）
if [[ "$(uname -s)" == MINGW* || "$(uname -s)" == MSYS* || "$(uname -s)" == CYGWIN* ]]; then
  BIN="${BIN}.exe"
fi
echo
if [[ -f "$BIN" ]]; then
  echo "==> 构建完成"
  echo "    产物: $BIN"
  echo "    架构: $(uname -m)（仅适用于同架构的 $(uname -s)）"
  echo "    大小: $(du -h "$BIN" | awk '{print $1}')"
  echo "    验证: $BIN --version"
  if [[ "$(uname)" == "Darwin" ]]; then
    echo "    注意: 未签名产物分发后，接收方首次运行需解除 quarantine:"
    echo "      xattr -d com.apple.quarantine $OUTPUT_NAME"
  fi
else
  echo "错误: 未找到产物 $BIN" >&2
  exit 1
fi
