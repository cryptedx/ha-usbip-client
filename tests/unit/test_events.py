"""Unit tests for usbip_lib.events module."""

import json
import os

import pytest

from usbip_lib.events import now_iso, read_events, write_event


class TestNowIso:
    def test_returns_string(self):
        result = now_iso()
        assert isinstance(result, str)
        assert "T" in result  # ISO format contains T separator


class TestWriteEvent:
    def test_creates_file(self, tmp_events_file):
        assert not os.path.exists(tmp_events_file)
        write_event("test", "detail", events_file=tmp_events_file)
        assert os.path.exists(tmp_events_file)

    def test_appends(self, tmp_events_file):
        write_event("first", "detail1", events_file=tmp_events_file)
        write_event("second", "detail2", events_file=tmp_events_file)
        with open(tmp_events_file) as f:
            lines = f.readlines()
        assert len(lines) == 2

    def test_json_format(self, tmp_events_file):
        write_event(
            "attach_ok",
            "attached",
            device="Stick",
            server="192.168.1.44",
            events_file=tmp_events_file,
        )
        with open(tmp_events_file) as f:
            data = json.loads(f.readline())
        assert data["type"] == "attach_ok"
        assert data["detail"] == "attached"
        assert data["device"] == "Stick"
        assert data["server"] == "192.168.1.44"
        assert "ts" in data

    def test_write_to_bad_path(self):
        # Should not raise
        write_event("test", "detail", events_file="/nonexistent/path/events.jsonl")


class TestReadEvents:
    def test_empty_file(self, tmp_events_file):
        with open(tmp_events_file, "w") as f:
            pass
        result = read_events(events_file=tmp_events_file)
        assert result == []

    def test_missing_file(self, tmp_path):
        result = read_events(events_file=str(tmp_path / "missing.jsonl"))
        assert result == []

    def test_returns_events(self, tmp_events_file):
        write_event("a", "1", events_file=tmp_events_file)
        write_event("b", "2", events_file=tmp_events_file)
        write_event("c", "3", events_file=tmp_events_file)
        result = read_events(events_file=tmp_events_file)
        assert len(result) == 3
        assert result[0]["type"] == "a"
        assert result[2]["type"] == "c"

    def test_limit(self, tmp_events_file):
        for i in range(10):
            write_event(f"ev{i}", str(i), events_file=tmp_events_file)
        result = read_events(limit=3, events_file=tmp_events_file)
        assert len(result) == 3
        # Should return the last 3
        assert result[0]["type"] == "ev7"

    def test_skips_malformed_lines(self, tmp_events_file):
        with open(tmp_events_file, "w") as f:
            f.write('{"type": "good", "ts": "t", "detail": "", "device": "", "server": ""}\n')
            f.write("not json\n")
            f.write('{"type": "also_good", "ts": "t", "detail": "", "device": "", "server": ""}\n')
        result = read_events(events_file=tmp_events_file)
        assert len(result) == 2
        assert result[0]["type"] == "good"
        assert result[1]["type"] == "also_good"

    def test_handles_os_error(self, mocker, tmp_events_file):
        # Mock open to raise OSError
        mocker.patch("builtins.open", side_effect=OSError("Permission denied"))
        result = read_events(events_file=tmp_events_file)
        assert result == []
