"""Helpers for tracking file-read state across a session.

Persists a lightweight JSON dict on the Session row so that repeated
``read_file`` calls for unchanged files can be short-circuited, saving
context-window tokens.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.models.session import Session
from sqlmodel import Session as DBSession, select

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Range helpers
# ---------------------------------------------------------------------------


def _merge_ranges(
    ranges: list[list[int]],
    new_start: int,
    new_end: int,
) -> list[list[int]]:
    """Merge *new_start..new_end* into an existing sorted, non-overlapping
    range list and return the merged result.

    Adjacent ranges (e.g. [1, 400] and [401, 800]) are merged.
    """
    if new_end < new_start:
        return ranges
    merged = [*ranges, [new_start, new_end]]
    merged.sort(key=lambda r: r[0])
    result: list[list[int]] = [merged[0]]
    for start, end in merged[1:]:
        prev_start, prev_end = result[-1]
        if start <= prev_end + 1:
            result[-1] = [prev_start, max(prev_end, end)]
        else:
            result.append([start, end])
    return result


def _is_range_covered(
    ranges: list[list[int]],
    start: int,
    end: int,
) -> bool:
    """Return ``True`` if the closed interval *start..end* is fully covered
    by the union of *ranges*.
    """
    return any(r_start <= start and r_end >= end for r_start, r_end in ranges)


# ---------------------------------------------------------------------------
# Tracker I/O
# ---------------------------------------------------------------------------


def load_tracker(
    session_id: str,
    db_session_factory: Any,
) -> dict[str, Any] | None:
    """Load the tracker dict from the Session row.

    Returns ``None`` when the session cannot be found or the column is empty.
    """
    with db_session_factory() as db:
        session = _get_session(db, session_id)
        if session is None or not session.react_file_read_tracker:
            return None
        try:
            return json.loads(session.react_file_read_tracker)
        except (json.JSONDecodeError, TypeError):
            return None


def save_tracker(
    session_id: str,
    db_session_factory: Any,
    tracker: dict[str, Any],
) -> None:
    """Persist the tracker dict back to the Session row."""
    with db_session_factory() as db:
        session = _get_session(db, session_id)
        if session is None:
            return
        session.react_file_read_tracker = json.dumps(
            tracker, ensure_ascii=False
        )
        db.add(session)
        db.commit()


def clear_tracker(session_id: str, db_session_factory: Any) -> None:
    """Set the tracker to an empty dict (called on compaction)."""
    save_tracker(session_id, db_session_factory, {})


# ---------------------------------------------------------------------------
# Dedup logic
# ---------------------------------------------------------------------------


def check_dedup(
    tracker: dict[str, Any] | None,
    path: str,
    content_hash: str,
    start_line: int,
    end_line: int,
) -> bool:
    """Return ``True`` if the requested range of *path* has already been read
    with the same *content_hash* and is therefore safe to skip.
    """
    if not tracker:
        return False
    entry = tracker.get(path)
    if entry is None:
        return False
    if entry.get("hash") != content_hash:
        return False
    return _is_range_covered(entry.get("read_ranges", []), start_line, end_line)


def record_read(
    tracker: dict[str, Any],
    path: str,
    content_hash: str,
    total_lines: int,
    start_line: int,
    end_line: int,
) -> dict[str, Any]:
    """Record a successful read and return the mutated *tracker*.

    If the file hash changed since last record, ``read_ranges`` is reset.
    """
    entry = tracker.get(path)
    if entry and entry.get("hash") == content_hash:
        existing_ranges = entry.get("read_ranges", [])
    else:
        existing_ranges = []
    tracker[path] = {
        "hash": content_hash,
        "total_lines": total_lines,
        "read_ranges": _merge_ranges(existing_ranges, start_line, end_line),
    }
    return tracker


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------


def _get_session(db: DBSession, session_id: str) -> Session | None:
    row = db.exec(
        select(Session).where(Session.session_id == session_id)
    ).first()
    return row
