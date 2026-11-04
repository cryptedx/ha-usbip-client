"""JSONL event log for tracking USB/IP operations."""

import fcntl
import json
import os
from collections import deque
from datetime import datetime, timezone
from typing import BinaryIO, Iterator

from .constants import EVENTS_FILE, EVENTS_MAX_BYTES, EVENTS_RETAINED_LINES

_READ_CHUNK_BYTES = 64 * 1024


def now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _iter_complete_records_reverse(
    handle: BinaryIO,
    max_record_bytes: int,
) -> Iterator[bytes]:
    """Yield complete newline-terminated records newest first."""
    handle.seek(0, os.SEEK_END)
    file_size = handle.tell()
    if file_size == 0 or max_record_bytes <= 0:
        return

    handle.seek(file_size - 1)
    ends_with_newline = handle.read(1) == b"\n"
    position = file_size - 1 if ends_with_newline else file_size
    is_complete = ends_with_newline
    fragments: deque[bytes] = deque()
    fragment_bytes = 0
    record_too_large = False

    def add_fragment(fragment: bytes) -> None:
        nonlocal fragment_bytes, record_too_large
        if not fragment or record_too_large:
            return
        if fragment_bytes + len(fragment) + 1 > max_record_bytes:
            fragments.clear()
            fragment_bytes = 0
            record_too_large = True
            return
        fragments.appendleft(fragment)
        fragment_bytes += len(fragment)

    while position > 0:
        read_size = min(_READ_CHUNK_BYTES, position)
        position -= read_size
        handle.seek(position)
        chunk = handle.read(read_size)
        segment_end = len(chunk)

        while True:
            newline_index = chunk.rfind(b"\n", 0, segment_end)
            if newline_index < 0:
                add_fragment(chunk[:segment_end])
                break

            add_fragment(chunk[newline_index + 1 : segment_end])
            record = None
            if is_complete and not record_too_large:
                record = b"".join(fragments) + b"\n"

            fragments.clear()
            fragment_bytes = 0
            record_too_large = False
            is_complete = True
            segment_end = newline_index

            if record is not None:
                yield record

    if is_complete and not record_too_large:
        yield b"".join(fragments) + b"\n"


def _is_valid_jsonl_record(record: bytes) -> bool:
    try:
        json.loads(record[:-1].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return True


def _select_valid_tail(
    handle: BinaryIO,
    *,
    max_bytes: int,
    max_lines: int,
) -> tuple[list[bytes], int]:
    """Select the newest complete valid records within both caps."""
    handle.seek(0, os.SEEK_END)
    file_size = handle.tell()
    if max_bytes <= 0 or max_lines <= 0:
        return [], file_size

    newest_first = []
    selected_bytes = 0
    for record in _iter_complete_records_reverse(handle, max_bytes):
        if not _is_valid_jsonl_record(record):
            continue
        if selected_bytes + len(record) > max_bytes:
            break
        newest_first.append(record)
        selected_bytes += len(record)
        if len(newest_first) == max_lines:
            break

    newest_first.reverse()
    return newest_first, file_size


def _rewrite_locked(handle: BinaryIO, records: list[bytes]) -> None:
    """Replace file contents while its exclusive lock is held."""
    handle.seek(0)
    handle.truncate()
    handle.writelines(records)
    handle.flush()


def write_event(
    event_type: str,
    detail: str,
    device: str = "",
    server: str = "",
    data: dict | None = None,
    events_file: str | None = None,
    *,
    max_bytes: int = EVENTS_MAX_BYTES,
    retained_lines: int = EVENTS_RETAINED_LINES,
) -> None:
    """Append an event and keep only the newest bounded valid JSONL records."""
    if events_file is None:
        events_file = EVENTS_FILE
    entry = {
        "ts": now_iso(),
        "type": event_type,
        "device": device,
        "server": server,
        "detail": detail,
    }
    if data is not None:
        entry["data"] = data
    encoded_event = (json.dumps(entry) + "\n").encode("utf-8")

    try:
        with open(events_file, "a+b") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            records, file_size = _select_valid_tail(
                handle,
                max_bytes=max_bytes,
                max_lines=retained_lines,
            )
            selected_bytes = sum(map(len, records))
            existing_is_normalized = selected_bytes == file_size

            if max_bytes <= 0 or retained_lines <= 0 or len(encoded_event) > max_bytes:
                if not existing_is_normalized:
                    _rewrite_locked(handle, records)
                return

            bounded_records = deque(records)
            bounded_records.append(encoded_event)
            bounded_bytes = selected_bytes + len(encoded_event)
            dropped_record = False
            while len(bounded_records) > retained_lines or bounded_bytes > max_bytes:
                bounded_bytes -= len(bounded_records.popleft())
                dropped_record = True

            if existing_is_normalized and not dropped_record:
                handle.seek(0, os.SEEK_END)
                handle.write(encoded_event)
                handle.flush()
            else:
                _rewrite_locked(handle, list(bounded_records))
    except OSError:
        pass


def clear_events(events_file: str | None = None) -> None:
    """Clear the event log under the same exclusive lock used by writers."""
    if events_file is None:
        events_file = EVENTS_FILE
    try:
        with open(events_file, "a+b") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            handle.seek(0)
            handle.truncate()
            handle.flush()
    except OSError:
        pass


def read_events(limit: int = 200, events_file: str | None = None) -> list[dict]:
    """Read the bounded tail of complete valid events, most recent last."""
    if events_file is None:
        events_file = EVENTS_FILE
    if limit <= 0:
        return []
    try:
        with open(events_file, "rb") as handle:
            fcntl.flock(handle, fcntl.LOCK_SH)
            records, _ = _select_valid_tail(
                handle,
                max_bytes=EVENTS_MAX_BYTES,
                max_lines=limit,
            )
        return [json.loads(record[:-1].decode("utf-8")) for record in records]
    except OSError:
        return []
