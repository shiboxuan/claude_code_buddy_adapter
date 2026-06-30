# claude_code_buddy_adapter

Claude Code Buddy 桌宠设备的 Python adapter。聚合多个 Claude Code session 的 hooks/statusLine 事件，转换为状态机与设备展示快照，通过 USB serial 下发给 M5Stack StickS3 固件。

> 设备按钮只做本地页面切换与静音，不控制 Claude Code 的执行决策。

## 架构

```
Claude Code ──HTTP/loopback──▶ adapter ──USB serial(JSON Lines)──▶ StickS3 firmware
```

- HTTP receiver 绑定 `127.0.0.1:8765`（仅 loopback，不暴露局域网）。
- 事件 → normalizer → reducer/arbiter → display composer → serial 协议帧。
- 详见 `docs/claude_code_buddy/` 下的系统设计与协议文档。

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
buddy-adapter run                       # 启动 HTTP receiver + serial bridge（ADP-P7 实现）
buddy-adapter doctor                    # 环境自检（ADP-P7 实现）
buddy-adapter install-claude --print    # 生成 Claude Code 配置片段（ADP-P7 实现）
buddy-adapter replay <file.jsonl>       # 回放事件流（ADP-P7 实现）
buddy-adapter dump-state                # 输出当前状态（ADP-P7 实现）
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

## HTTP 框架

使用 **FastAPI + Uvicorn**（异步，便于 P95 < 50ms 压测与集成测试）。statusLine / hook helper 脚本读取 stdin 后 POST 到 loopback endpoint，且无论 adapter 返回什么都 `exit 0`，避免被 Claude Code 判定为 hook 失败。

## 技术栈

- Python 3.11、pyserial、FastAPI、Uvicorn
- serial 协议版本：`ccb-serial-v1`
