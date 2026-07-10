# tests/fixtures/real/ — 真实格式 payload（ADP-P9-T01）

本目录的 payload 用于 normalizer 校准（ADP-P9-T03）与 fixture 入库。

## 来源

这些是**基于协议契约的真实格式 payload**：字段结构严格对齐
[protocol §3.2（statusLine）](../../../docs/claude_code_buddy/claude-code-buddy-api-protocol.md)
/ [§3.3（hooks）](../../../docs/claude_code_buddy/claude-code-buddy-api-protocol.md)
/ [§5.6（14 个 hook_event_name）](../../../docs/claude_code_buddy/claude-code-buddy-api-protocol.md)，
与 Claude Code 真实发出的 payload 结构一致；`cwd` / `session_id` / `repo.name` 取自本工程真实值。

## 采集线上真实触发 payload

若需采集 Claude Code 真实触发（非手造）的 payload，用
[`debug/capture_payloads.py`](../../../debug/capture_payloads.py)：

1. `buddy-adapter install-claude --write`（装配置，hooks 指向 127.0.0.1:8765）
2. 停掉 adapter（释放 8765）
3. `conda run -n claude_code_buddy_adapter python debug/capture_payloads.py --port 8765 --out tests/fixtures/real/`
4. 跑真实 Claude Code session，触发的 hooks/statusLine 会落盘到本目录
5. Ctrl-C 停止；还原 adapter 与 settings.json（用 `install-claude` 备份）

> 当前会话装配置后，Claude Code 的 settings.json 通常需新会话才重载 hooks，
> 故真实触发采集建议在新开的 Claude Code session 进行。

## 文件清单

- `statusline_real.json` — statusLine payload（model/workspace/cost/context_window）
- `hook_<event>.json` × 14 — 覆盖 §5.6 全部 hook_event_name：
  SessionStart / UserPromptSubmit / PreToolUse / PostToolUse / MessageDisplay /
  SubagentStart / TaskCreated / Notification / PermissionRequest / Elicitation /
  ElicitationResult / Stop / StopFailure / SessionEnd
