"""Helpers for persisted latency history used by WebUI server-status graph."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from .constants import LATENCY_HISTORY_FILE, LATENCY_HISTORY_WINDOW_SECONDS
from .events import now_iso


def _parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    value = ts
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _normalize_servers(servers: dict | None) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    if not isinstance(servers, dict):
        return out
    for server, value in servers.items():
        if not server:
            continue
        if value is None:
            out[str(server)] = None
            continue
        try:
            out[str(server)] = float(value)
        except (TypeError, ValueError):
            out[str(server)] = None
    return out


def should_persist_change(
    previous: float | None,
    current: float | None,
    *,
    abs_threshold_ms: float,
    rel_threshold: float,
) -> bool:
    """Return True when latency transition is significant enough to persist."""
    if previous is None or current is None:
        return previous != current

    delta = abs(current - previous)
    if delta > abs_threshold_ms:
        return True
    if previous <= 0:
        return False
    return (delta / previous) > rel_threshold


def _read_samples(
    *,
    history_file: str,
    window_seconds: int,
    now_ts: datetime | None = None,
) -> list[dict]:
    now_dt = now_ts or datetime.now(timezone.utc)
    cutoff = now_dt - timedelta(seconds=window_seconds)
    rows: list[dict] = []

    try:
        with open(history_file, encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue

                ts = payload.get("ts")
                dt = _parse_iso(ts)
                if dt is None or dt < cutoff:
                    continue

                rows.append(
                    {
                        "ts": dt,
                        "ts_iso": ts,
                        "servers": _normalize_servers(payload.get("servers")),
                    }
                )
    except OSError:
        return []

    rows.sort(key=lambda item: item["ts"])
    return rows


def append_latency_samples(
    samples: list[dict],
    *,
    history_file: str = LATENCY_HISTORY_FILE,
    window_seconds: int = LATENCY_HISTORY_WINDOW_SECONDS,
) -> bool:
    """Append new samples, prune to time window, and rewrite compact JSONL file."""
    if not samples:
        return True

    merged: list[dict] = _read_samples(
        history_file=history_file,
        window_seconds=window_seconds,
    )

    now_dt = datetime.now(timezone.utc)
    for sample in samples:
        ts = sample.get("ts") or now_iso()
        dt = _parse_iso(ts)
        if dt is None:
            continue
        merged.append(
            {
                "ts": dt,
                "ts_iso": ts,
                "servers": _normalize_servers(sample.get("servers")),
            }
        )
        if dt > now_dt:
            now_dt = dt

    cutoff = now_dt - timedelta(seconds=window_seconds)
    merged = [sample for sample in merged if sample["ts"] >= cutoff]
    merged.sort(key=lambda item: item["ts"])

    try:
        with open(history_file, "w", encoding="utf-8") as handle:
            for sample in merged:
                handle.write(
                    json.dumps(
                        {
                            "ts": sample["ts_iso"],
                            "servers": sample["servers"],
                        },
                        separators=(",", ":"),
                    )
                    + "\n"
                )
    except OSError:
        return False
    return True


def read_latency_window(
    *,
    server_ips: list[str] | None = None,
    history_file: str = LATENCY_HISTORY_FILE,
    window_seconds: int = LATENCY_HISTORY_WINDOW_SECONDS,
) -> dict:
    """Return aligned timestamps + per-server series for latency graph rendering."""
    rows = _read_samples(history_file=history_file, window_seconds=window_seconds)

    if server_ips:
        servers = list(dict.fromkeys(server_ips))
    else:
        servers = sorted(
            {
                server
                for row in rows
                for server in row.get("servers", {}).keys()
                if server
            }
        )

    timestamps = [row["ts_iso"] for row in rows]
    series = {server: [] for server in servers}
    for row in rows:
        row_servers = row.get("servers", {})
        for server in servers:
            series[server].append(row_servers.get(server))

    return {
        "window_seconds": window_seconds,
        "sample_interval_seconds": 30,
        "timestamps": timestamps,
        "series": series,
    }
