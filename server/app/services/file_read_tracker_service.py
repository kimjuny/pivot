"""Session-scoped file read tracker service."""

from __future__ import annotations

import json
from typing import Any

from app.models.session import Session as SessionModel
from sqlmodel import Session as DBSession, select


class FileReadTrackerService:
    """Manage file content hashes and read ranges for one ReAct session."""

    def __init__(self, db: DBSession) -> None:
        self.db = db

    def get_tracker(self, session_id: str) -> dict[str, Any] | None:
        """Return the parsed tracker for a session, if present and valid."""
        session = self._get_session(session_id, lock=False)
        if session is None or not session.react_file_read_tracker:
            return None
        return self._loads(session.react_file_read_tracker)

    def check_and_record_read(
        self,
        *,
        session_id: str,
        path: str,
        content_hash: str,
        total_lines: int,
        start_line: int,
        end_line: int,
    ) -> bool:
        """Record a file read unless the range is already covered.

        Returns:
            True when the caller can safely return a dedup summary.
        """
        session = self._get_session(session_id, lock=True)
        if session is None:
            return False

        tracker = self._loads(session.react_file_read_tracker) or {}
        if check_dedup(tracker, path, content_hash, start_line, end_line):
            return True

        record_read(tracker, path, content_hash, total_lines, start_line, end_line)
        session.react_file_read_tracker = self._dumps(tracker)
        self.db.add(session)
        self.db.commit()
        return False

    def record_read(
        self,
        *,
        session_id: str,
        path: str,
        content_hash: str,
        total_lines: int,
        start_line: int,
        end_line: int,
    ) -> None:
        """Record a known file read range."""
        session = self._get_session(session_id, lock=True)
        if session is None:
            return
        tracker = self._loads(session.react_file_read_tracker) or {}
        record_read(tracker, path, content_hash, total_lines, start_line, end_line)
        session.react_file_read_tracker = self._dumps(tracker)
        self.db.add(session)
        self.db.commit()

    def invalidate_file(
        self,
        *,
        session_id: str,
        path: str,
    ) -> None:
        """Remove one file from the tracker after content edits."""
        session = self._get_session(session_id, lock=True)
        if session is None:
            return
        tracker = self._loads(session.react_file_read_tracker) or {}
        if path not in tracker:
            return
        tracker.pop(path, None)
        session.react_file_read_tracker = self._dumps(tracker)
        self.db.add(session)
        self.db.commit()

    def clear_tracker(self, session_id: str, *, commit: bool = True) -> None:
        """Clear the tracker for a session."""
        session = self._get_session(session_id, lock=True)
        if session is None:
            return
        session.react_file_read_tracker = "{}"
        self.db.add(session)
        if commit:
            self.db.commit()

    def _get_session(self, session_id: str, *, lock: bool) -> SessionModel | None:
        statement = select(SessionModel).where(SessionModel.session_id == session_id)
        if lock:
            statement = statement.with_for_update()
        return self.db.exec(statement).first()

    @staticmethod
    def _loads(raw: str | None) -> dict[str, Any] | None:
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _dumps(tracker: dict[str, Any]) -> str:
        return json.dumps(tracker, ensure_ascii=False)


def check_dedup(
    tracker: dict[str, Any] | None,
    path: str,
    content_hash: str,
    start_line: int,
    end_line: int,
) -> bool:
    """Return whether the requested unchanged range is already tracked."""
    if not tracker:
        return False
    entry = tracker.get(path)
    if not isinstance(entry, dict):
        return False
    if entry.get("hash") != content_hash:
        return False
    if end_line < start_line:
        return int(entry.get("total_lines", -1)) == 0
    return _is_range_covered(entry.get("read_ranges", []), start_line, end_line)


def record_read(
    tracker: dict[str, Any],
    path: str,
    content_hash: str,
    total_lines: int,
    start_line: int,
    end_line: int,
) -> dict[str, Any]:
    """Record a read range in the tracker and return the same dict."""
    entry = tracker.get(path)
    if isinstance(entry, dict) and entry.get("hash") == content_hash:
        existing_ranges = entry.get("read_ranges", [])
    else:
        existing_ranges = []
    tracker[path] = {
        "hash": content_hash,
        "total_lines": total_lines,
        "read_ranges": _merge_ranges(existing_ranges, start_line, end_line),
    }
    return tracker


def _merge_ranges(
    ranges: Any,
    new_start: int,
    new_end: int,
) -> list[list[int]]:
    """Merge one closed interval into sorted, non-overlapping read ranges."""
    valid_ranges = [
        coerced_range
        for item in ranges
        if (coerced_range := _coerce_range(item)) is not None
    ]
    if new_end < new_start:
        return valid_ranges

    merged = [*valid_ranges, [new_start, new_end]]
    merged.sort(key=lambda item: item[0])
    result: list[list[int]] = [merged[0]]
    for start, end in merged[1:]:
        previous_start, previous_end = result[-1]
        if start <= previous_end + 1:
            result[-1] = [previous_start, max(previous_end, end)]
        else:
            result.append([start, end])
    return result


def _is_range_covered(
    ranges: Any,
    start: int,
    end: int,
) -> bool:
    """Return whether a closed interval is covered by tracked ranges."""
    if not isinstance(ranges, list):
        return False
    return any(
        coerced_range[0] <= start and coerced_range[1] >= end
        for item in ranges
        if (coerced_range := _coerce_range(item)) is not None
    )


def _coerce_range(item: Any) -> list[int] | None:
    """Return a valid integer range or None for malformed persisted data."""
    if not isinstance(item, list | tuple) or len(item) != 2:
        return None
    try:
        start = int(item[0])
        end = int(item[1])
    except (TypeError, ValueError):
        return None
    if end < start:
        return None
    return [start, end]
