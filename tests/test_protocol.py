"""ADP-P4: serial protocol 帧序列化 / seq / 限长 / error code 单测。"""

from __future__ import annotations

import threading

import pytest

from claude_code_buddy_adapter.device.protocol import (
    KEY_FRAMES,
    MAX_FRAME_BYTES,
    PROTOCOL_VERSION,
    ErrorCode,
    FrameParseError,
    FrameTooLargeError,
    SeqCounter,
    assert_within_max,
    frame_size,
    make_alert,
    make_config,
    make_device_snapshot,
    make_hello_ack,
    make_ping,
    parse_frame,
    serialize,
)


def test_protocol_version():
    assert PROTOCOL_VERSION == "ccb-serial-v1"


def test_error_code_enum_complete():
    values = {e.value for e in ErrorCode}
    assert values == {
        "json_parse_error", "missing_required_field", "unknown_message_type",
        "frame_too_large", "version_mismatch", "internal_error",
    }


def test_key_frames_are_seq_carriers():
    assert KEY_FRAMES == {"hello_ack", "device_snapshot", "session_snapshot", "alert", "config"}


# ---- seq ----

def test_seq_starts_at_1():
    s = SeqCounter()
    assert s.next() == 1
    assert s.next() == 2


def test_seq_uint32_wraparound_skips_zero():
    s = SeqCounter(start=0xFFFFFFFF)
    assert s.next() == 0xFFFFFFFF
    assert s.next() == 1  # 回绕跳过 0


def test_seq_thread_safety_no_duplicates():
    s = SeqCounter()
    seen: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        local: list[int] = []
        for _ in range(100):
            local.append(s.next())
        with lock:
            seen.extend(local)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(seen)) == 800  # 无重复


# ---- serialize / parse round-trip ----

def test_serialize_ends_with_single_newline():
    data = serialize(make_ping(123))
    assert data.endswith(b"\n")
    assert b"\n" not in data[:-1]  # 行内无换行


def test_round_trip_ping():
    frame = make_ping(123)
    assert parse_frame(serialize(frame).decode("utf-8")) == frame


def test_round_trip_device_snapshot():
    frame = make_device_snapshot(
        seq=1, global_state="working", color="red",
        focus_session={"id": "s"}, counts={"sessions": 1}, alert=None,
    )
    assert parse_frame(serialize(frame).decode()) == frame


def test_round_trip_alert():
    frame = make_alert(seq=5, kind="attention", sound=True, session_id="s1")
    assert parse_frame(serialize(frame).decode()) == frame


def test_parse_bad_json_raises():
    with pytest.raises(FrameParseError):
        parse_frame("not json")


def test_parse_empty_raises():
    with pytest.raises(FrameParseError):
        parse_frame("   ")


def test_parse_non_object_raises():
    with pytest.raises(FrameParseError):
        parse_frame("[1,2,3]")


# ---- 限长 ----

def test_frame_size_positive():
    assert frame_size(make_ping(1)) > 0


def test_assert_within_max_ok_for_small_frame():
    assert_within_max(make_ping(1))  # 不抛


def test_assert_within_max_raises_for_oversized():
    big = make_device_snapshot(
        seq=1, global_state="working", color="red",
        focus_session={"id": "x" * 2000}, counts={},
    )
    with pytest.raises(FrameTooLargeError):
        assert_within_max(big)


def test_device_snapshot_under_1024_bytes():
    frame = make_device_snapshot(
        seq=1, global_state="working", color="red",
        focus_session={"id": "s", "title": "Working", "line1": "repo"},
        counts={"sessions": 1, "working": 1, "attention": 0, "error": 0},
    )
    assert frame_size(frame) <= MAX_FRAME_BYTES


# ---- 帧构造 ----

def test_make_hello_ack():
    f = make_hello_ack("0.1.0", 1, True)
    assert f["type"] == "hello_ack"
    assert f["ok"] is True
    assert f["adapter_version"] == "0.1.0"
    assert f["protocol"] == PROTOCOL_VERSION
    assert f["seq"] == 1


def test_make_config_only_sets_provided_fields():
    f = make_config(1, sound_enabled=True)
    assert "sound_enabled" in f
    assert "brightness" not in f
    assert "privacy_mode" not in f


def test_make_alert_omits_session_id_when_none():
    f = make_alert(1, "connected", True)
    assert "session_id" not in f


def test_make_alert_includes_session_id():
    f = make_alert(1, "attention", True, session_id="s1")
    assert f["session_id"] == "s1"
