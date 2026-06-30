"""ADP-P5-T01: SerialDiscovery 单测（mock list_ports）。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from claude_code_buddy_adapter.device.discovery import DEFAULT_VID, SerialDiscovery


def _port(device, vid=None, pid=None, product=None, description=None):
    p = MagicMock()
    p.device = device
    p.vid = vid
    p.pid = pid
    p.product = product
    p.description = description
    return p


@patch("serial.tools.list_ports.comports")
def test_find_by_vid(mock_comports):
    mock_comports.return_value = [_port("/dev/ttyUSB0", vid=DEFAULT_VID, product="M5StickS3")]
    assert SerialDiscovery().find() == "/dev/ttyUSB0"


@patch("serial.tools.list_ports.comports")
def test_find_by_name_when_vid_none(mock_comports):
    mock_comports.return_value = [_port("/dev/ttyACM0", vid=None, product="M5Stack StickS3")]
    assert SerialDiscovery(vid=None).find() == "/dev/ttyACM0"


@patch("serial.tools.list_ports.comports")
def test_find_no_match(mock_comports):
    mock_comports.return_value = [_port("/dev/ttyUSB0", vid=0x1234, product="Other Device")]
    assert SerialDiscovery().find() is None


@patch("serial.tools.list_ports.comports")
def test_find_empty(mock_comports):
    mock_comports.return_value = []
    assert SerialDiscovery().find() is None


@patch("serial.tools.list_ports.comports")
def test_list_ports(mock_comports):
    mock_comports.return_value = [_port("/dev/a"), _port("/dev/b")]
    assert SerialDiscovery().list_ports() == ["/dev/a", "/dev/b"]


@patch("serial.tools.list_ports.comports")
def test_find_pid_filter(mock_comports):
    mock_comports.return_value = [
        _port("/dev/a", vid=DEFAULT_VID, pid=0x1001),
        _port("/dev/b", vid=DEFAULT_VID, pid=0x1002),
    ]
    assert SerialDiscovery(vid=DEFAULT_VID, pid=0x1002).find() == "/dev/b"
