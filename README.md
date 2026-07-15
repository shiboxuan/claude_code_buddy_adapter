# claude_code_buddy_adapter

Claude Code Buddy 桌宠设备的 Python adapter。聚合多个 Claude Code session 的 hooks/statusLine 事件，转换为状态机与设备展示快照，通过 USB serial 下发给 M5Stack StickS3 固件。

> 设备按钮只做本地页面切换与静音，不控制 Claude Code 的执行决策。

## 架构

```
Claude Code ──HTTP/loopback──▶ adapter ──USB serial(JSON Lines)──▶ StickS3 firmware
```

- HTTP receiver 绑定 `127.0.0.1:8765`（仅 loopback，不暴露局域网）。
- 事件 → normalizer → reducer/arbiter → display composer → serial 协议帧。

## 开发环境要求

- Python 3.11
- conda（推荐）

## 开发环境部署

```bash
# 1. 创建 conda 环境
conda env create -f environment.yml
conda activate claude_code_buddy_adapter

# 2. 可编辑安装本包（含 dev 依赖）
pip install -e ".[dev]"
```

## 运行命令

```bash
buddy-adapter --version
buddy-adapter run                       # 启动 HTTP receiver + serial bridge（无设备自动用 fake serial）
buddy-adapter doctor                    # 环境自检：Python / serial / Claude Code 配置 / firmware
buddy-adapter install-claude --print    # 打印 statusLine/hooks helper 脚本与 settings.json 片段
buddy-adapter replay <file.jsonl>       # 回放 JSONL 事件流，输出最终状态
buddy-adapter dump-state                # 输出运行中 adapter 的 sessions/focus/counts/metrics
```

## 运行产物：Intel macOS 使用预编译二进制（其他芯片架构的产物运行方式类似）

下面以下载到用户主目录的 `~/buddy-adapter-macos-x86_64` 为例。该文件只适用于 Intel（x86_64）Mac；先确认本机与文件架构：

```bash
uname -m
file ~/buddy-adapter-macos-x86_64
```

Intel Mac 的 `uname -m` 应输出 `x86_64`，`file` 输出中应包含 `Mach-O 64-bit executable x86_64`。

### 1. 添加可执行权限

下载后的文件可能没有执行权限，需要先执行：

```bash
chmod +x ~/buddy-adapter-macos-x86_64
```

可以用下面的命令确认权限；输出中应包含 `x`，例如 `-rwxr-xr-x`：

```bash
ls -l ~/buddy-adapter-macos-x86_64
```

### 2. 允许 macOS 首次运行

该二进制目前没有使用 Apple Developer ID 签名和公证，首次运行时可能被 Gatekeeper 拦截。**只有在确认文件来自[本项目 Releases](https://github.com/shiboxuan/claude_code_buddy_adapter/releases)、且文件未被篡改时，才应覆盖 macOS 的安全拦截。**

先尝试运行一次，让 macOS 生成对应的安全提示：

```bash
~/buddy-adapter-macos-x86_64 --version
```

如果系统提示“无法验证开发者”“Apple 无法检查其是否包含恶意软件”或阻止打开，请按 [Apple 官方说明](https://support.apple.com/guide/mac-help/open-an-app-by-overriding-security-settings-mh40617/mac) 强制允许：

1. 打开“系统设置” → “隐私与安全性”。
2. 向下滚动到“安全性”，找到刚刚被阻止的 `buddy-adapter-macos-x86_64`。
3. 点击“仍要打开”（Open Anyway），输入登录密码，再在确认窗口中点击“打开”。
4. “仍要打开”按钮通常只在尝试运行后的约一小时内出现；看不到时，重新执行一次上面的 `--version` 命令。

也可以在**确认来源可信**后，通过终端检查并移除浏览器下载时附加的 quarantine 属性：

```bash
xattr -l ~/buddy-adapter-macos-x86_64
xattr -d com.apple.quarantine ~/buddy-adapter-macos-x86_64
```

如果 `xattr -l` 没有显示 `com.apple.quarantine`，说明该属性已经不存在，无需执行删除命令。放行后重新验证：

```bash
~/buddy-adapter-macos-x86_64 --version
~/buddy-adapter-macos-x86_64 doctor
```

### 3. 安装 Claude Code 配置

让二进制写入 hooks/statusLine helper，并合并到现有 `~/.claude/settings.json`（写入前会备份，重复执行不会重复添加）：

```bash
~/buddy-adapter-macos-x86_64 install-claude --write
```

如果 `~/.claude/settings.json` 还不存在，按命令提示增加 `--create`：

```bash
~/buddy-adapter-macos-x86_64 install-claude --write --create
```

### 4. 前台运行

```bash
~/buddy-adapter-macos-x86_64 run
```

程序会启动 HTTP receiver 与 serial bridge；没有发现设备时会自动使用 fake serial。按 `Control-C` 停止。该打包产物不带子命令时也会默认执行 `run`，但显式写出 `run` 更容易辨认当前用途。

### 5. 使用 nohup 在后台运行

启动前先确认没有旧实例，避免同时运行多份服务：

```bash
pgrep -fl buddy-adapter-macos-x86_64
```

没有输出时，再启动后台进程：

```bash
nohup ~/buddy-adapter-macos-x86_64 run \
  > ~/buddy-adapter.log 2>&1 &

echo $! > ~/buddy-adapter.pgid
```

如果不希望产生运行日志，可以把标准输出和错误输出都丢弃到 `/dev/null`，并在同一行保存进程组 ID：

```bash
nohup ~/buddy-adapter-macos-x86_64 run >/dev/null 2>&1 & echo $! > ~/buddy-adapter.pgid
```

这个静默运行命令不会创建新的 `buddy-adapter.log` 或 `nohup.out`，但也无法通过日志排查启动、端口或串口错误；已经存在的旧日志文件不会被自动删除。

关闭终端后程序仍会继续运行。这里保存的是后台任务的**进程组 ID**；onefile 启动进程稍后退出时，实际工作进程仍留在同一个进程组中。常用检查命令：

```bash
# 查看 nohup 启动的进程组
pgrep -g "$(cat ~/buddy-adapter.pgid)" -fl

# 查看所有相关进程
pgrep -fl buddy-adapter-macos-x86_64

# 查看日志
tail -f ~/buddy-adapter.log

# 检查 HTTP receiver
curl -fsS http://127.0.0.1:8765/v1/state
```

停止 nohup 启动的实例：

```bash
kill -TERM -- -"$(cat ~/buddy-adapter.pgid)"
```

稍等片刻后检查是否已全部退出：

```bash
pgrep -fl buddy-adapter-macos-x86_64
```

如果仍有残留子进程，再按完整路径停止该二进制的所有进程：

```bash
pkill -f "$HOME/buddy-adapter-macos-x86_64"
```

不要同时使用 `nohup` 和下面的 LaunchAgent，否则会启动两组实例并争用同一个 HTTP 端口。

### 6. 登录后自动启动（可选）

需要每次登录 macOS 后自动启动时，可以使用用户级 `launchd`。下面的命令会把当前用户主目录展开为 plist 所需的绝对路径；plist 内不能直接使用 `~`：

```bash
BIN="$HOME/buddy-adapter-macos-x86_64"
PLIST="$HOME/Library/LaunchAgents/com.claudecodebuddy.adapter.plist"
OUT_LOG="$HOME/Library/Logs/buddy-adapter.log"
ERR_LOG="$HOME/Library/Logs/buddy-adapter-error.log"

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.claudecodebuddy.adapter</string>

    <key>ProgramArguments</key>
    <array>
        <string>${BIN}</string>
        <string>run</string>
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>${OUT_LOG}</string>

    <key>StandardErrorPath</key>
    <string>${ERR_LOG}</string>
</dict>
</plist>
EOF

plutil -lint "$PLIST"
launchctl bootstrap "gui/$(id -u)" "$PLIST"
```

检查运行状态和日志：

```bash
launchctl print "gui/$(id -u)/com.claudecodebuddy.adapter"
tail -f "$HOME/Library/Logs/buddy-adapter.log"
tail -f "$HOME/Library/Logs/buddy-adapter-error.log"
```

修改 plist 后，先卸载再重新加载：

```bash
launchctl bootout "gui/$(id -u)" \
  "$HOME/Library/LaunchAgents/com.claudecodebuddy.adapter.plist"
launchctl bootstrap "gui/$(id -u)" \
  "$HOME/Library/LaunchAgents/com.claudecodebuddy.adapter.plist"
```

停止并取消登录自动启动：

```bash
launchctl bootout "gui/$(id -u)" \
  "$HOME/Library/LaunchAgents/com.claudecodebuddy.adapter.plist"
```

### 常见现象

- **看到两个同名进程**：onefile 二进制运行时可能先保留一个启动进程，并创建一个实际工作子进程。用 `ps -o pid,ppid,pgid,state,lstart,command -p PID1,PID2` 检查；如果第二个进程的 `PPID` 等于第一个进程的 PID，它们是父子关系，通常不是重复启动。启动进程退出后也可能只剩一个工作进程，其 `PPID` 会变成 `1`，但 `PGID` 仍可用于停止整个后台任务。
- **启动新任务时显示旧任务 `Killed: 9`**：例如先输出 `[3] 37291`，随后显示 `[2] Killed: 9 ...`，表示新任务 `[3]` 已启动，而 shell 此时才补报旧后台任务 `[2]` 曾收到 `SIGKILL`。用 `jobs -l`、`pgrep -fl buddy-adapter-macos-x86_64` 和日志确认当前实例即可。
- **端口已被占用**：通常是旧的 nohup 实例或已加载的 LaunchAgent 仍在运行。先用 `pgrep` 和 `launchctl print "gui/$(id -u)/com.claudecodebuddy.adapter"` 分别检查，不要再次直接启动。

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

用 Nuitka 打成单文件可执行，方便分发给未装 Python/conda 的用户。产物无参时默认拉起 adapter（等价于显式传入 `run`），也可透传 `doctor` / `install-claude` / `replay` / `dump-state`。

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

**macOS 首次运行**：未签名产物分发后，接收方需要添加可执行权限，并通过“隐私与安全性”或 `xattr` 放行 Gatekeeper。完整步骤见上面的“Intel macOS 使用预编译二进制”；其他架构只需替换二进制文件名。

## HTTP 框架

使用 **FastAPI + Uvicorn**（异步，便于 P95 < 50ms 压测与集成测试）。statusLine / hook helper 脚本读取 stdin 后 POST 到 loopback endpoint，且无论 adapter 返回什么都 `exit 0`，避免被 Claude Code 判定为 hook 失败。

## 技术栈

- Python 3.11、pyserial、FastAPI、Uvicorn
- serial 协议版本：`ccb-serial-v1`

## 配套
- firmware工程在：https://github.com/shiboxuan/claude_code_buddy
- 可以使用m5stack stick s3进行编译和烧录
