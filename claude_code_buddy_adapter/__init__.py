"""claude_code_buddy_adapter — Claude Code Buddy 桌宠 adapter。

把 Claude Code hooks/statusLine 事件聚合为多 session 状态，并通过 USB serial
将设备展示快照下发给 StickS3 固件。
"""

__version__ = "0.1.0"

PROTOCOL_VERSION = "ccb-serial-v1"
