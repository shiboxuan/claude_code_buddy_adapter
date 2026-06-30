"""ADP-P0-T08: 指标计数器自增与读取。"""

from __future__ import annotations

import threading

from claude_code_buddy_adapter.metrics import COUNTERS, GAUGES, LATENCIES, METRICS, Metrics


def test_counter_inc_and_get():
    m = Metrics()
    m.inc("events_received_total")
    m.inc("events_received_total", 2)
    assert m.get("events_received_total") == 3


def test_all_counters_present():
    m = Metrics()
    snap = m.snapshot()
    for name in COUNTERS:
        assert name in snap
        assert snap[name] == 0


def test_gauge_set():
    m = Metrics()
    m.set("sessions_active", 5)
    assert m.get("sessions_active") == 5
    m.set("device_connected", 1)
    assert m.get("device_connected") == 1


def test_gauges_present():
    m = Metrics()
    snap = m.snapshot()
    for name in GAUGES:
        assert name in snap


def test_latency_observe():
    m = Metrics()
    m.observe("state_transition_latency_ms", 10.0)
    m.observe("state_transition_latency_ms", 30.0)
    info = m.get("state_transition_latency_ms")
    assert info["count"] == 2
    assert info["last_ms"] == 30.0
    assert info["avg_ms"] == 20.0


def test_latency_present():
    m = Metrics()
    snap = m.snapshot()
    for name in LATENCIES:
        assert name in snap
        assert snap[name]["count"] == 0


def test_unknown_metric_raises():
    m = Metrics()
    try:
        m.inc("nope")
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError")


def test_thread_safety():
    m = Metrics()

    def worker():
        for _ in range(1000):
            m.inc("events_received_total")

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert m.get("events_received_total") == 8000


def test_default_instance():
    assert METRICS.get("events_received_total") == 0
