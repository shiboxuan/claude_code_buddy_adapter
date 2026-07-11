# claude_code_buddy_adapter

Claude Code Buddy 桌宠设备的 Python adapter。聚合多个 Claude Code session 的 hooks/statusLine 事件，转换为状态机与设备展示快照，通过 USB serial 下发给 M5Stack StickS3 固件。

> 设备按钮只做本地页面切换与静音，不控制 Claude Code 的执行决策。

## 架构

```
Claude Code ──HTTP/loopback──▶ adapter ──USB serial(JSON Lines)──▶ StickS3 firmware
```

- HTTP receiver 绑定 `127.0.0.1:8765`（仅 loopback，不暴露局域网）。
- 事件 → normalizer → reducer/arbiter → display composer → serial 协议帧。

## 环境要求

- Python 3.11
- conda（推荐）

## 安装

```bash
# 1. 创建 conda 环境
conda env create -f environment.yml
conda activate claude_code_buddy_adapter

# 2. 可编辑安装本包（含 dev 依赖）
pip install -e ".[dev]"
```

## 运行

```bash
buddy-adapter --version
buddy-adapter run                       # 启动 HTTP receiver + serial bridge（无设备自动用 fake serial）
buddy-adapter doctor                    # 环境自检：Python / serial / Claude Code 配置 / firmware
buddy-adapter install-claude --print    # 打印 statusLine/hooks helper 脚本与 settings.json 片段
buddy-adapter replay <file.jsonl>       # 回放 JSONL 事件流，输出最终状态
buddy-adapter dump-state                # 输出运行中 adapter 的 sessions/focus/counts/metrics
```

## 配置

默认配置见 `claude_code_buddy_adapter/config.py`。可通过 TOML/JSON 配置文件或环境变量覆盖：

| 字段 | 环境变量 | 默认值 |
|---|---|---|
| http_host | `BUDDY_HTTP_HOST` | `127.0.0.1` |
| http_port | `BUDDY_HTTP_PORT` | `8765` |
| serial_port | `BUDDY_SERIAL_PORT` | (自动发现) |
| baudrate | `BUDDY_BAUDRATE` | `115200` |
| privacy_mode | `BUDDY_PRIVACY_MODE` | `false` |
| sound_enabled_default | `BUDDY_SOUND_ENABLED` | `true` |
| done_ttl_ms | `BUDDY_DONE_TTL_MS` | `5000` |
| session_ttl_ms | `BUDDY_SESSION_TTL_MS` | `300000` |
| debug_event_log | `BUDDY_DEBUG_EVENT_LOG` | `false` |
| message_display_capture | `BUDDY_MESSAGE_DISPLAY_CAPTURE` | `false` |

## 测试

```bash
pytest
```

## 打包分发

用 Nuitka 打成单文件可执行，方便分发给未装 Python/conda 的用户。产物等价于 `buddy-adapter` 命令：无参默认拉起 adapter，也可透传 `doctor` / `install-claude` / `replay` / `dump-state`。

```bash
# 1. 安装打包依赖（一次性）
pip install -e ".[build]"

# 2. 打包（默认 onefile 单文件，产出 dist/buddy-adapter）
./scripts/build.sh

# 或产出目录形态（启动更快，但分发是一组文件）
./scripts/build.sh --mode standalone

# 3. 验证
./dist/buddy-adapter --version
```

**架构说明（重要）**：Nuitka 不支持交叉编译，本脚本做的是**本机架构构建**--在 x86_64 机器上产出 x86_64 包，在 arm64 机器上产出 arm64 包。要给 Apple Silicon (arm64) 用户出包，必须在 arm64 环境跑同一脚本：

- 借一台 Apple Silicon Mac 原生跑；或
- 在 CI 的 arm64 runner 上跑（如 GitHub Actions `macos-14`/`macos-15` runner 即 arm64）。

无法在 x86 Mac 上直接产出 arm64 包。若需要一个包通吃 x86 + arm64，分别在两种架构各 build 一份，再用 `lipo -create` 合并成 universal2。

**macOS 首次运行**：未签名产物分发后，接收方需解除 quarantine 标记：

```bash
xattr -d com.apple.quarantine buddy-adapter
```

## HTTP 框架

使用 **FastAPI + Uvicorn**（异步，便于 P95 < 50ms 压测与集成测试）。statusLine / hook helper 脚本读取 stdin 后 POST 到 loopback endpoint，且无论 adapter 返回什么都 `exit 0`，避免被 Claude Code 判定为 hook 失败。

## 技术栈

- Python 3.11、pyserial、FastAPI、Uvicorn
- serial 协议版本：`ccb-serial-v1`
