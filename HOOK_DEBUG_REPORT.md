# Buddy-Adapter Hook 调试报告

> 生成时间：2026-07-12 00:18（本地）
> 目的：实测验证"CC 停下来问用户问题时，S3 小怪物是否会进 attention（黄）"。
> 状态：初步版。Stop / idle Notification 的实测结论由 00:22 的自检 cron 补全（见"实测结果"末尾）。

## 0. 隔离方案（生产零污染）

- **未改 adapter 代码、未重启 adapter 进程**（生产 adapter PID 39044 一直在 8765 跑，桌宠不中断）。
- 调试日志加在 **helper 脚本层**：`~/.claude/claude-code-buddy-hook` 被临时改成"读 stdin → 落盘一份到 `/tmp/buddy_hook_debug.jsonl` → 照常 curl 给 adapter"。
- 原脚本已备份到 `~/.claude/claude-code-buddy-hook.bak`。
- 调试完还原命令：
  ```bash
  cp ~/.claude/claude-code-buddy-hook.bak ~/.claude/claude-code-buddy-hook
  rm -f /tmp/buddy_hook_debug.jsonl /tmp/buddy_debug_start.txt
  ```
- 日志格式：每行一个 JSON `{ts, hook_event_name, raw}`，raw 是 CC 发给 helper 的完整 payload。

## 1. 代码侧事实（已核实，属实）

- `cli.py:27` 的 `HOOK_EVENTS` 只有 8 个：`SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, Notification, Stop, StopFailure, SessionEnd`。**不含** `PermissionRequest` / `Elicitation`。
- `~/.claude/settings.json` 实际注册的也是这 8 个，与代码一致。
- `reducer.py:41-42` 的 `HOOK_STATE_MAP` **有** `PermissionRequest`/`Elicitation` → `attention` 的映射——reducer 准备好了，但这俩 hook 没注册，永远不会进 adapter。
- 在已注册的 8 个 hook 里，能触发 `attention` 的只有 `Notification`（`reducer.py:117`，`ATTENTION_EVENTS`）。

## 2. 文档侧事实（已核实，来自 Claude Code 官方 hooks 文档）

| hook | 何时触发 |
|---|---|
| `PreToolUse` | 工具调用执行前 |
| `PostToolUse` | 工具调用成功后 |
| `PermissionRequest` | 权限弹窗出现时（allow/deny） |
| `Notification` | CC 发通知时；其 `type` 含 `permission_prompt / idle_prompt / auth_success / elicitation_dialog / elicitation_complete / elicitation_response / agent_needs_input / agent_completed` |
| `Elicitation` | **MCP server** 在工具调用中请求用户输入时（仅 MCP，不含内置 AskUserQuestion） |
| `Stop` | CC 回复结束时 |

- 文档 PreToolUse matcher **明确列出 `AskUserQuestion` 是一个 tool**（与 Bash/Edit/Write/Read 并列）。
- 所以解释里"AskUserQuestion 走 PermissionRequest hook"是**错的**。AskUserQuestion 是 tool → 走 `PreToolUse`/`PostToolUse`（已注册 → `working`）。

## 3. 实测结果

### 3.1 PreToolUse / PostToolUse（实测确认 ✅）

连续调用 Read / Bash 等工具，日志确认：每次工具调用产生 `PreToolUse` + `PostToolUse` 一对，`tool_name` 字段记录具体工具。reducer 把它们映射到 `working`。

→ **工具调用期间小怪物 = working，不是 attention。**

### 3.2 Stop（待 00:22 自检补全）

本轮回复结束时 CC 发 `Stop` → reducer 映射 `done_recent` → 5s 后 `idle`。

### 3.3 idle Notification / attention（待 00:22 自检补全）

假设：CC 回复完进入"等待用户输入"后，约 60s 发 `Notification(type=idle_prompt)` → 已注册 → `attention`。这应能解释用户观察到的"完成后过一段时间变黄"。

### 3.4 AskUserQuestion（无法实测，基于文档+代码强推断）

- 不调真实 AskUserQuestion：会弹问题板阻塞，等用户回答，与"今晚出结论"冲突。
- 推断：AskUserQuestion 是 tool → `PreToolUse`（→ `working`）+ 用户回答后 `PostToolUse`。**不会进 attention**。
- **唯一不确定点**：AskUserQuestion 弹板时，CC 是否额外发一条 `Notification(type=elicitation_dialog)`。若发了，则因 Notification 已注册 → 会变 attention。文档把 `elicitation_dialog` 与 MCP elicitation 并列，暗示是 MCP 场景，**倾向不发**，但无法 100% 排除。
- 要彻底确认，需在交互会话里实测（见 §5）。

### 3.5 权限弹窗（本会话无法实测）

- 本会话 `permission_mode = bypassPermissions`（payload 自带），工具调用不弹权限窗。
- 所以 `PermissionRequest` 和 `Notification(type=permission_prompt)` 在本会话都不会触发。
- **注意**：即便在 default 模式下弹了权限窗，由于 `Notification(type=permission_prompt)` 是 Notification 的一种，而 Notification 已注册 → **权限弹窗很可能也会让小怪物变黄**（经 Notification，而非 PermissionRequest）。这推翻了解释里"权限走 PermissionRequest 没监听所以不变黄"的推论。需 default 模式实测确认。

## 4. 结论（回答你的核心问题）

> "CC 停下来问用户问题，不会触发 attention，真的吗？"

- **如果指"CC 用 AskUserQuestion 工具弹选项板"**：基本成立——AskUserQuestion 是 tool，走 PreToolUse → `working`，**不变 attention**。但原因不是解释说的"PermissionRequest 没注册"，而是"它是 tool 走 working"。唯一残留不确定：是否额外触发 `Notification(elicitation_dialog)`（倾向不会）。
- **如果指"CC 回完一轮等你输入"**：**会变 attention**——空闲后 CC 发 `Notification(idle_prompt)`，已注册 → attention。这正是你看到的"完成后过一段时间变黄"。**待 00:22 实测确认。**

解释里的事实性错误：
1. "AskUserQuestion 走 PermissionRequest" —— 错。AskUserQuestion 是 tool，走 PreToolUse。
2. "权限走 PermissionRequest 没监听所以不变黄" —— 推论存疑。权限弹窗很可能同时发 `Notification(permission_prompt)`（已注册），反而会变黄。

## 5. 限制与明天自测方法

本会话 two 个场景没实测到：AskUserQuestion、权限弹窗（因 bypassPermissions）。明天可在交互会话里复核：

1. 先确认 helper 脚本是否仍为调试版（若已还原，重新加 tee，或用下面的一键命令）。
2. 在一个 **default 权限模式**的会话里：
   - 让 CC 调 AskUserQuestion → 看 `/tmp/buddy_hook_debug.jsonl` 是否出现 `Notification` 且 type 含 `elicitation`。
   - 触发一个权限弹窗（执行需 allow/deny 的命令）→ 看是否出现 `Notification(type=permission_prompt)`。
3. 一键重开调试（若脚本已还原）：
   ```bash
   cp ~/.claude/claude-code-buddy-hook ~/.claude/claude-code-buddy-hook.bak
   # 然后把 00:18 写入的调试版脚本内容贴回（见 git 无版本，可从 .bak 之外的备份恢复）
   ```
   （更稳的做法：把调试日志做成 adapter 侧 env 守卫模块，下次再做。）
