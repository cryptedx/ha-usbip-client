"""Unit tests for usbip_lib.events module."""

import fcntl
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

import usbip_lib.events as events_module
from usbip_lib.constants import EVENTS_MAX_BYTES
from usbip_lib.events import now_iso, read_events, write_event


def read_valid_jsonl(events_file):
    raw = open(events_file, "rb").read()
    assert not raw or raw.endswith(b"\n")
    records = []
    for line in raw.splitlines(keepends=True):
        assert line.endswith(b"\n")
        records.append(json.loads(line.decode("utf-8")))
    return raw, records


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

    def test_includes_optional_data_payload(self, tmp_events_file):
        write_event(
            "flap_warning",
            "unstable",
            device="Stick",
            server="192.168.1.44",
            data={"device_key": "192.168.1.44:1-1.4", "count": 3},
            events_file=tmp_events_file,
        )
        with open(tmp_events_file) as f:
            data = json.loads(f.readline())
        assert data["data"]["device_key"] == "192.168.1.44:1-1.4"
        assert data["data"]["count"] == 3

    def test_write_to_bad_path(self):
        # Should not raise
        write_event("test", "detail", events_file="/nonexistent/path/events.jsonl")

    def test_compacts_to_strict_byte_and_line_limits(self, tmp_events_file):
        max_bytes = 256
        for index in range(10):
            write_event(
                f"event_{index}",
                "x" * 40,
                events_file=tmp_events_file,
                max_bytes=max_bytes,
                retained_lines=3,
            )

        raw, events = read_valid_jsonl(tmp_events_file)
        event_indexes = [int(event["type"].removeprefix("event_")) for event in events]

        assert len(raw) <= max_bytes
        assert len(events) <= 3
        assert event_indexes == list(range(10 - len(events), 10))

    def test_retained_lines_is_a_secondary_hard_cap(self, tmp_events_file):
        for index in range(10):
            write_event(
                f"event_{index}",
                str(index),
                events_file=tmp_events_file,
                max_bytes=10_000,
                retained_lines=3,
            )

        raw, events = read_valid_jsonl(tmp_events_file)

        assert len(raw) <= 10_000
        assert [event["type"] for event in events] == [
            "event_7",
            "event_8",
            "event_9",
        ]

    def test_rejects_single_event_larger_than_max_bytes(self, tmp_events_file):
        max_bytes = 256
        write_event(
            "kept",
            "short",
            events_file=tmp_events_file,
            max_bytes=max_bytes,
            retained_lines=10,
        )
        before = open(tmp_events_file, "rb").read()

        write_event(
            "too_large",
            "x" * max_bytes,
            events_file=tmp_events_file,
            max_bytes=max_bytes,
            retained_lines=10,
        )

        raw, events = read_valid_jsonl(tmp_events_file)
        assert raw == before
        assert len(raw) <= max_bytes
        assert [event["type"] for event in events] == ["kept"]

    def test_repairs_unterminated_tail_before_appending(self, tmp_events_file):
        write_event("before", "valid", events_file=tmp_events_file)
        with open(tmp_events_file, "ab") as handle:
            handle.write(b'{"type":"broken"')

        write_event("after", "valid", events_file=tmp_events_file)

        _, events = read_valid_jsonl(tmp_events_file)
        assert [event["type"] for event in events] == ["before", "after"]

    def test_removes_corrupt_and_invalid_utf8_tail_before_appending(
        self, tmp_events_file
    ):
        write_event("before", "valid", events_file=tmp_events_file)
        with open(tmp_events_file, "ab") as handle:
            handle.write(b"not-json\n\xff\xfe\n")

        write_event("after", "valid", events_file=tmp_events_file)

        _, events = read_valid_jsonl(tmp_events_file)
        assert [event["type"] for event in events] == ["before", "after"]

    @pytest.mark.parametrize(
        "held_lock",
        [
            pytest.param(fcntl.LOCK_SH, id="reader"),
            pytest.param(fcntl.LOCK_EX, id="writer"),
        ],
    )
    def test_clear_waits_for_active_file_lock(self, tmp_events_file, mocker, held_lock):
        write_event("before", "valid", events_file=tmp_events_file)
        real_flock = fcntl.flock
        lock_attempted = threading.Event()

        def tracked_flock(handle, operation):
            if (
                threading.current_thread() is not threading.main_thread()
                and operation == fcntl.LOCK_EX
            ):
                lock_attempted.set()
            return real_flock(handle, operation)

        with open(tmp_events_file, "a+b") as blocker:
            real_flock(blocker, held_lock)
            mocker.patch(
                "usbip_lib.events.fcntl.flock",
                side_effect=tracked_flock,
            )
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    events_module.clear_events,
                    events_file=tmp_events_file,
                )
                assert lock_attempted.wait(timeout=1)
                assert not future.done()
                real_flock(blocker, fcntl.LOCK_UN)
                future.result(timeout=1)

        assert open(tmp_events_file, "rb").read() == b""


class TestReadEvents:
    def test_empty_file(self, tmp_events_file):
        open(tmp_events_file, "w").close()
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

    def test_non_positive_limit_returns_empty(self, tmp_events_file):
        write_event("a", "1", events_file=tmp_events_file)

        assert read_events(limit=0, events_file=tmp_events_file) == []
        assert read_events(limit=-1, events_file=tmp_events_file) == []

    def test_skips_malformed_lines(self, tmp_events_file):
        with open(tmp_events_file, "w") as f:
            f.write(
                '{"type": "good", "ts": "t", "detail": "", "device": "", "server": ""}\n'
            )
            f.write("not json\n")
            f.write(
                '{"type": "also_good", "ts": "t", "detail": "", "device": "", "server": ""}\n'
            )
        result = read_events(events_file=tmp_events_file)
        assert len(result) == 2
        assert result[0]["type"] == "good"
        assert result[1]["type"] == "also_good"

    def test_handles_os_error(self, mocker, tmp_events_file):
        # Mock open to raise OSError
        mocker.patch("builtins.open", side_effect=OSError("Permission denied"))
        result = read_events(events_file=tmp_events_file)
        assert result == []

    def test_huge_unterminated_tail_uses_fixed_size_binary_reads(
        self, mocker, tmp_events_file
    ):
        write_event("old", "valid", events_file=tmp_events_file)
        with open(tmp_events_file, "r+b") as handle:
            handle.seek(EVENTS_MAX_BYTES * 2)
            handle.write(b"x")

        real_open = open
        read_sizes = []

        class GuardedBinaryReader:
            def __init__(self, handle):
                self.handle = handle

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return self.handle.__exit__(*args)

            def __getattr__(self, name):
                return getattr(self.handle, name)

            def __iter__(self):
                raise AssertionError("event reads must not iterate unbounded lines")

            def read(self, size=-1):
                assert 0 < size <= 64 * 1024
                read_sizes.append(size)
                return self.handle.read(size)

        def guarded_open(path, mode="r", *args, **kwargs):
            assert mode == "rb"
            return GuardedBinaryReader(real_open(path, mode, *args, **kwargs))

        mocker.patch("builtins.open", side_effect=guarded_open)

        events = read_events(limit=10, events_file=tmp_events_file)

        assert [event["type"] for event in events] == ["old"]
        assert read_sizes
        assert max(read_sizes) <= 64 * 1024
