"""JSONL event log for tracking USB/IP operations."""

import json
import os
from datetime import datetime, timezone

from .constants import EVENTS_FILE


def now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def write_event(
    event_type: str,
    detail: str,
    device: str = "",
    server: str = "",
    events_file: str | None = None,
) -> None:
    """Append an event to the JSONL event log.

    Args:
        event_type: Event type (attach_ok, attach_fail, detach_ok, etc.).
        detail: Human-readable description.
        device: Device name or identifier.
        server: Server address.
        events_file: Path to events file (default: EVENTS_FILE constant).
    """
    if events_file is None:
        events_file = EVENTS_FILE
    entry = {
        "ts": now_iso(),
        "type": event_type,
        "device": device,
        "server": server,
        "detail": detail,
    }
    try:
        with open(events_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def read_events(limit: int = 200, events_file: str | None = None) -> list[dict]:
    """Read most-recent events from the JSONL file.

    Args:
        limit: Maximum number of events to return.
        events_file: Path to events file (default: EVENTS_FILE constant).

    Returns:
        List of event dicts, most recent last.
    """
    if events_file is None:
        events_file = EVENTS_FILE
    if not os.path.exists(events_file):
        return []
    try:
        with open(events_file, "r") as f:
            lines = f.readlines()
        events = []
        for ln in lines[-limit:]:
            ln = ln.strip()
            if ln:
                try:
                    events.append(json.loads(ln))
                except json.JSONDecodeError:
                    pass
        return events
    except OSError:
        return []
