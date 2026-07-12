"""SessionStore：按 session_id 存储 session，线程安全，TTL 清理，ended 归档，debug JSONL。

receiver 线程与 serial 读线程并发访问，故所有方法加锁。
TTL 用惰性计算（apply_event/cleanup 时 tick），不依赖后台线程。
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Optional

from ..claude.event_model import ClaudeEvent
from ..claude.reducer import Session, SessionState, new_session, reduce_event, tick
from .arbiter import compute_counts, compute_global_state, select_focus


class SessionStore:
    def __init__(
        self,
        done_ttl_ms: int = 5000,
        session_ttl_ms: int = 300_000,
        working_ttl_ms: int = 600_000,
        debug_jsonl: Optional[str] = None,
    ) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, Session] = {}
        self._archived: dict[str, Session] = {}
        self._done_ttl_ms = done_ttl_ms
        self._session_ttl_ms = session_ttl_ms
        self._working_ttl_ms = working_ttl_ms
        self._debug_jsonl = debug_jsonl
        self._revision = 0

    # ---- 增删改查 ----
    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    def _refresh_locked(self, now_ms: int) -> list[Session]:
        """惰性 tick 全部 session 并写回（状态变化时），返回当前 session 列表。调用方须持锁。

        查询路径先调此方法，保证 done_recent/attention/error 在无新事件时也能按 TTL 降级
        （BR-007/BR-008）。
        """
        for sid in list(self._sessions.keys()):
            s = self._sessions[sid]
            ticked = tick(s, now_ms, self._done_ttl_ms, self._session_ttl_ms, self._working_ttl_ms)
            if ticked.state != s.state:
                self._sessions[sid] = ticked
                self._revision += 1
        return list(self._sessions.values())

    @property
    def revision(self) -> int:
        with self._lock:
            return self._revision

    def get(self, session_id: str, now_ms: Optional[int] = None) -> Optional[Session]:
        with self._lock:
            self._refresh_locked(now_ms if now_ms is not None else self._now_ms())
            s = self._sessions.get(session_id)
            return replace(s) if s is not None else None

    def get_archived(self, session_id: str) -> Optional[Session]:
        with self._lock:
            s = self._archived.get(session_id)
            return replace(s) if s is not None else None

    def upsert(self, session: Session) -> None:
        with self._lock:
            self._sessions[session.session_id] = replace(session)
            self._revision += 1

    def apply_event(self, event: ClaudeEvent, now_ms: Optional[int] = None) -> Session:
        """reduce event 到对应 session 并存回；ended 自动归档。返回更新后的副本。"""
        now = now_ms if now_ms is not None else event.received_at_ms
        with self._lock:
            existing = self._sessions.get(event.session_id)
            base = existing if existing is not None else new_session(event.session_id)
            base = tick(base, now, self._done_ttl_ms, self._session_ttl_ms, self._working_ttl_ms)  # 惰性降级
            updated = reduce_event(base, event, now_ms=now)
            self._sessions[event.session_id] = updated
            self._revision += 1
            if updated.state == SessionState.ended:
                self._archive_locked(event.session_id)
            self._write_debug(event, updated)
            return replace(updated)

    def archive(self, session_id: str) -> None:
        with self._lock:
            self._archive_locked(session_id)

    def _archive_locked(self, session_id: str) -> None:
        s = self._sessions.pop(session_id, None)
        if s is not None:
            self._archived[session_id] = s
            self._revision += 1

    # ---- 查询 ----
    def active(self, now_ms: Optional[int] = None) -> list[Session]:
        with self._lock:
            sessions = self._refresh_locked(now_ms if now_ms is not None else self._now_ms())
            return [replace(s) for s in sessions if s.state != SessionState.ended]

    def active_with_revision(
        self, now_ms: Optional[int] = None
    ) -> tuple[list[Session], int]:
        """原子读取 active sessions 与对应 revision，供设备 snapshot 去重。"""
        with self._lock:
            sessions = self._refresh_locked(now_ms if now_ms is not None else self._now_ms())
            active = [replace(s) for s in sessions if s.state != SessionState.ended]
            return active, self._revision

    def all(self, now_ms: Optional[int] = None) -> list[Session]:
        with self._lock:
            sessions = self._refresh_locked(now_ms if now_ms is not None else self._now_ms())
            return [replace(s) for s in sessions]

    def cleanup(self, now_ms: int, ttl_ms: Optional[int] = None) -> int:
        """惰性 tick 全部 session 并归档 ended，返回归档数。"""
        ttl = ttl_ms if ttl_ms is not None else self._session_ttl_ms
        removed = 0
        with self._lock:
            for sid in list(self._sessions.keys()):
                s = self._sessions[sid]
                ticked = tick(s, now_ms, self._done_ttl_ms, ttl, self._working_ttl_ms)
                if ticked.state != s.state:
                    self._sessions[sid] = ticked
                    self._revision += 1
                if ticked.state == SessionState.ended:
                    self._archive_locked(sid)
                    removed += 1
        return removed

    def counts(self, now_ms: Optional[int] = None) -> dict[str, int]:
        with self._lock:
            sessions = self._refresh_locked(now_ms if now_ms is not None else self._now_ms())
            return compute_counts(sessions)

    def focus(self, now_ms: Optional[int] = None) -> Optional[Session]:
        with self._lock:
            sessions = self._refresh_locked(now_ms if now_ms is not None else self._now_ms())
            f = select_focus(sessions)
            return replace(f) if f is not None else None

    def global_state(self, device_connected: bool, now_ms: Optional[int] = None) -> str:
        with self._lock:
            sessions = self._refresh_locked(now_ms if now_ms is not None else self._now_ms())
            return compute_global_state(sessions, device_connected)

    def snapshot(self, device_connected: bool, now_ms: Optional[int] = None) -> dict:
        with self._lock:
            sessions = self._refresh_locked(now_ms if now_ms is not None else self._now_ms())
            f = select_focus(sessions)
            return {
                "device_connected": device_connected,
                "global_state": compute_global_state(sessions, device_connected),
                "focus_session_id": f.session_id if f is not None else None,
                "counts": compute_counts(sessions),
            }

    def _write_debug(self, event: ClaudeEvent, session: Session) -> None:
        if not self._debug_jsonl:
            return
        try:
            line = json.dumps({
                "event_id": event.event_id,
                "source": event.source,
                "hook_event_name": event.hook_event_name,
                "session_id": session.session_id,
                "state": session.state.value,
                "updated_at_ms": session.updated_at_ms,
            }, ensure_ascii=False)
            path = Path(self._debug_jsonl)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass
