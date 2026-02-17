"""Unit tests for usbip_lib.latency_history module."""

import json
from datetime import datetime, timedelta, timezone

from usbip_lib.latency_history import (
    append_latency_samples,
    read_latency_window,
    should_persist_change,
)


class TestShouldPersistChange:
    def test_detects_online_offline_transition(self):
        assert (
            should_persist_change(
                20.0,
                None,
                abs_threshold_ms=10.0,
                rel_threshold=0.2,
            )
            is True
        )
        assert (
            should_persist_change(
                None,
                18.0,
                abs_threshold_ms=10.0,
                rel_threshold=0.2,
            )
            is True
        )

    def test_ignores_small_delta(self):
        assert (
            should_persist_change(
                50.0,
                55.0,
                abs_threshold_ms=10.0,
                rel_threshold=0.2,
            )
            is False
        )

    def test_detects_absolute_or_relative_delta(self):
        assert (
            should_persist_change(
                50.0,
                65.0,
                abs_threshold_ms=10.0,
                rel_threshold=0.2,
            )
            is True
        )
        assert (
            should_persist_change(
                30.0,
                37.0,
                abs_threshold_ms=10.0,
                rel_threshold=0.2,
            )
            is True
        )


class TestLatencyHistoryPersistence:
    def test_appends_and_reads_aligned_series(self, tmp_path):
        history_file = str(tmp_path / "latency.jsonl")
        base = datetime.now(timezone.utc) - timedelta(minutes=10)
        ts1 = base.isoformat().replace("+00:00", "Z")
        ts2 = (base + timedelta(seconds=30)).isoformat().replace("+00:00", "Z")

        ok = append_latency_samples(
            [
                {
                    "ts": ts1,
                    "servers": {"10.0.0.1": 20.5, "10.0.0.2": None},
                },
                {
                    "ts": ts2,
                    "servers": {"10.0.0.1": 21.0, "10.0.0.2": 44.0},
                },
            ],
            history_file=history_file,
            window_seconds=3600,
        )
        assert ok is True

        payload = read_latency_window(
            server_ips=["10.0.0.1", "10.0.0.2"],
            history_file=history_file,
            window_seconds=3600,
        )

        assert payload["timestamps"] == [ts1, ts2]
        assert payload["series"]["10.0.0.1"] == [20.5, 21.0]
        assert payload["series"]["10.0.0.2"] == [None, 44.0]

    def test_prunes_old_records_on_append(self, tmp_path):
        history_file = str(tmp_path / "latency.jsonl")
        now_dt = datetime.now(timezone.utc)
        old_ts = (now_dt - timedelta(minutes=40)).isoformat().replace("+00:00", "Z")
        fresh_ts = (now_dt - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")

        append_latency_samples(
            [
                {
                    "ts": old_ts,
                    "servers": {"10.0.0.1": 12.0},
                },
                {
                    "ts": fresh_ts,
                    "servers": {"10.0.0.1": 24.0},
                },
            ],
            history_file=history_file,
            window_seconds=1800,
        )

        with open(history_file, encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle if line.strip()]

        assert len(rows) == 1
        assert rows[0]["ts"] == fresh_ts

    def test_skips_malformed_lines_when_reading(self, tmp_path):
        history_file = str(tmp_path / "latency.jsonl")
        ts = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat().replace(
            "+00:00", "Z"
        )
        with open(history_file, "w", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "ts": ts,
                        "servers": {"10.0.0.1": 22.0},
                    }
                )
                + "\n"
            )
            handle.write("not json\n")

        payload = read_latency_window(
            server_ips=["10.0.0.1"],
            history_file=history_file,
            window_seconds=3600,
        )
        assert payload["series"]["10.0.0.1"] == [22.0]