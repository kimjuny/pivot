"""Unit tests for session file-read tracker service."""

from __future__ import annotations

import sys
import unittest
from importlib import import_module
from pathlib import Path

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

import_module("app.models")
SessionModel = import_module("app.models.session").Session
FileReadTrackerService = import_module(
    "app.services.file_read_tracker_service"
).FileReadTrackerService


class FileReadTrackerServiceTestCase(unittest.TestCase):
    """Validate tracker range, invalidation, and empty-file semantics."""

    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        session = SessionModel(
            session_id="session-1",
            agent_id=1,
            user_id=1,
            status="active",
            chat_history='{"version": 1, "messages": []}',
            react_llm_messages="[]",
            react_llm_cache_state="{}",
        )
        self.db.add(session)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()

    def test_repeated_same_range_keeps_recorded_range(self) -> None:
        service = FileReadTrackerService(self.db)

        service.record_read(
            session_id="session-1",
            path="app.py",
            content_hash="hash-a",
            total_lines=10,
            start_line=1,
            end_line=5,
        )
        service.record_read(
            session_id="session-1",
            path="app.py",
            content_hash="hash-a",
            total_lines=10,
            start_line=1,
            end_line=5,
        )

        tracker = service.get_tracker("session-1") or {}
        self.assertEqual(tracker["app.py"]["read_ranges"], [[1, 5]])

    def test_overlapping_range_with_new_lines_records_full_merged_range(self) -> None:
        service = FileReadTrackerService(self.db)
        service.record_read(
            session_id="session-1",
            path="app.py",
            content_hash="hash-a",
            total_lines=10,
            start_line=1,
            end_line=5,
        )

        service.record_read(
            session_id="session-1",
            path="app.py",
            content_hash="hash-a",
            total_lines=10,
            start_line=4,
            end_line=8,
        )

        tracker = service.get_tracker("session-1") or {}
        self.assertEqual(tracker["app.py"]["read_ranges"], [[1, 8]])

    def test_hash_change_resets_previous_ranges(self) -> None:
        service = FileReadTrackerService(self.db)
        service.record_read(
            session_id="session-1",
            path="app.py",
            content_hash="hash-a",
            total_lines=10,
            start_line=1,
            end_line=5,
        )

        service.record_read(
            session_id="session-1",
            path="app.py",
            content_hash="hash-b",
            total_lines=12,
            start_line=6,
            end_line=8,
        )

        tracker = service.get_tracker("session-1") or {}
        self.assertEqual(tracker["app.py"]["hash"], "hash-b")
        self.assertEqual(tracker["app.py"]["read_ranges"], [[6, 8]])

    def test_empty_file_can_be_recorded_by_hash(self) -> None:
        service = FileReadTrackerService(self.db)

        service.record_read(
            session_id="session-1",
            path="empty.txt",
            content_hash="empty-hash",
            total_lines=0,
            start_line=1,
            end_line=0,
        )
        service.record_read(
            session_id="session-1",
            path="empty.txt",
            content_hash="empty-hash",
            total_lines=0,
            start_line=1,
            end_line=0,
        )

        self.assertEqual(
            service.require_full_read_hash(session_id="session-1", path="empty.txt"),
            "empty-hash",
        )

    def test_invalidate_file_removes_tracker_entry(self) -> None:
        service = FileReadTrackerService(self.db)
        service.record_read(
            session_id="session-1",
            path="app.py",
            content_hash="hash-a",
            total_lines=10,
            start_line=1,
            end_line=5,
        )

        service.invalidate_file(session_id="session-1", path="app.py")

        self.assertEqual(service.get_tracker("session-1"), {})

    def test_clear_tracker_empties_session_tracker(self) -> None:
        service = FileReadTrackerService(self.db)
        service.record_read(
            session_id="session-1",
            path="app.py",
            content_hash="hash-a",
            total_lines=10,
            start_line=1,
            end_line=5,
        )

        service.clear_tracker("session-1")

        self.assertEqual(service.get_tracker("session-1"), {})

    def test_require_full_read_hash_returns_hash_for_complete_range(self) -> None:
        service = FileReadTrackerService(self.db)
        service.record_read(
            session_id="session-1",
            path="app.py",
            content_hash="hash-a",
            total_lines=3,
            start_line=1,
            end_line=3,
        )

        self.assertEqual(
            service.require_full_read_hash(session_id="session-1", path="app.py"),
            "hash-a",
        )

    def test_require_full_read_hash_rejects_partial_range(self) -> None:
        service = FileReadTrackerService(self.db)
        service.record_read(
            session_id="session-1",
            path="app.py",
            content_hash="hash-a",
            total_lines=3,
            start_line=1,
            end_line=2,
        )

        with self.assertRaisesRegex(RuntimeError, "Read the full file"):
            service.require_full_read_hash(session_id="session-1", path="app.py")

    def test_record_full_file_state_records_empty_file(self) -> None:
        service = FileReadTrackerService(self.db)

        service.record_full_file_state(
            session_id="session-1",
            path="empty.txt",
            content_hash="empty-hash",
            total_lines=0,
        )

        self.assertEqual(
            service.require_full_read_hash(session_id="session-1", path="empty.txt"),
            "empty-hash",
        )
