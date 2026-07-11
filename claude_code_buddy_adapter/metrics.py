"""指标计数器骨架，供 dump-state / GET /v1/state 读取。

指标名对齐系统设计 §可观测性与运维。
counter 单调递增；gauge 可设可清；latency 记录 last/count/avg。
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Any

COUNTERS = (
    "events_received_total",
    "events_parse_error_total",
    "serial_reconnect_total",
    "snapshot_sent_total",
    "snapshot_send_failure_total",
    "attention_events_total",
)
GAUGES = (
    "sessions_active",
    "device_connected",
)
LATENCIES = ("state_transition_latency_ms",)


class Metrics:
    """线程安全的指标寄存器。"""

    def __init__(self, history: int = 256) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {n: 0 for n in COUNTERS}
        self._gauges: dict[str, int | float] = {n: 0 for n in GAUGES}
        self._latency_last: dict[str, float] = {n: 0.0 for n in LATENCIES}
        self._latency_count: dict[str, int] = {n: 0 for n in LATENCIES}
        self._latency_sum: dict[str, float] = {n: 0.0 for n in LATENCIES}
        self._latency_history: dict[str, deque] = {
            n: deque(maxlen=history) for n in LATENCIES
        }

    def inc(self, name: str, n: int = 1) -> None:
        with self._lock:
            if name not in self._counters:
                raise KeyError(f"unknown counter: {name}")
            self._counters[name] += n

    def set(self, name: str, value: int | float) -> None:
        with self._lock:
            if name not in self._gauges:
                raise KeyError(f"unknown gauge: {name}")
            self._gauges[name] = value

    def observe(self, name: str, ms: float) -> None:
        with self._lock:
            if name not in self._latency_last:
                raise KeyError(f"unknown latency: {name}")
            self._latency_last[name] = ms
            self._latency_count[name] += 1
            self._latency_sum[name] += ms
            self._latency_history[name].append(ms)

    def get(self, name: str) -> Any:
        with self._lock:
            if name in self._counters:
                return self._counters[name]
            if name in self._gauges:
                return self._gauges[name]
            if name in self._latency_last:
                count = self._latency_count[name]
                total = self._latency_sum[name]
                return {
                    "last_ms": self._latency_last[name],
                    "count": count,
                    "avg_ms": (total / count) if count else 0.0,
                }
            raise KeyError(f"unknown metric: {name}")

    def snapshot(self) -> dict[str, Any]:
        """返回所有指标的快照，适合 dump-state / /v1/state。"""
        with self._lock:
            out: dict[str, Any] = {}
            out.update(self._counters)
            out.update(self._gauges)
            for n in LATENCIES:
                count = self._latency_count[n]
                total = self._latency_sum[n]
                out[n] = {
                    "last_ms": self._latency_last[n],
                    "count": count,
                    "avg_ms": (total / count) if count else 0.0,
                }
            return out


# 进程级默认实例
METRICS = Metrics()
