"""Unit tests for the built-in sandbox read_file tool."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

import_module("app.models")
SessionModel = import_module("app.models.session").Session
read_file_module = import_module("app.orchestration.tool.builtin.read_file")


class ReadFileToolTestCase(unittest.TestCase):
    """Validate exact-content chunk reading for edit workflows."""

    def test_script_returns_numbered_chunk(self) -> None:
        """The returned content should include line numbers for diff hunks."""
        module = cast("Any", read_file_module)
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "example.py"
            file_path.write_text("alpha\n  beta\ngamma\n", encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    module._READ_FILE_SCRIPT,
                    str(file_path),
                    "2",
                    "10",
                    "false",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["start_line"], 2)
        self.assertEqual(payload["end_line"], 3)
        self.assertEqual(payload["content"], "  beta\ngamma\n")

    def test_script_can_return_numbered_chunk(self) -> None:
        """Line numbers are opt-in for navigation-focused reads."""
        module = cast("Any", read_file_module)
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "example.py"
            file_path.write_text("alpha\n  beta\ngamma\n", encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    module._READ_FILE_SCRIPT,
                    str(file_path),
                    "2",
                    "10",
                    "true",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["content"], "2 |   beta\n3 | gamma\n")

    def test_script_truncates_requested_range_by_max_lines(self) -> None:
        """Chunk metadata should tell the caller when more lines remain."""
        module = cast("Any", read_file_module)
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "example.py"
            file_path.write_text("a\nb\nc\nd\n", encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    module._READ_FILE_SCRIPT,
                    str(file_path),
                    "2",
                    "2",
                    "false",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["content"], "b\nc\n")
        self.assertTrue(payload["truncated"])
        self.assertEqual(payload["next_start_line"], 4)

    def test_script_reports_missing_file_without_traceback(self) -> None:
        """Missing files should produce a short tool-facing error."""
        module = cast("Any", read_file_module)
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_path = Path(temp_dir) / "missing.py"

            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    module._READ_FILE_SCRIPT,
                    str(missing_path),
                    "1",
                    "10",
                    "false",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 1)
        self.assertIn("File not found:", completed.stderr)
        self.assertNotIn("Traceback", completed.stderr)

    def test_read_file_shortens_missing_file_sandbox_errors(self) -> None:
        """Sandbox missing-file failures should not expose Python tracebacks."""
        module = cast("Any", read_file_module)
        original_exec_in_sandbox = module.exec_in_sandbox

        def fail_missing_file(_cmd: list[str]) -> str:
            raise RuntimeError(
                "Sandbox command failed (exit=1): File not found: AGENTS.md"
            )

        module.exec_in_sandbox = fail_missing_file
        try:
            with self.assertRaisesRegex(FileNotFoundError, "File not found: AGENTS.md"):
                module.read_file(path="AGENTS.md")
        finally:
            module.exec_in_sandbox = original_exec_in_sandbox

    def test_read_file_rejects_large_max_lines(self) -> None:
        """Huge chunks should fail fast to keep reads focused."""
        module = cast("Any", read_file_module)

        with self.assertRaisesRegex(ValueError, "less than or equal to 2000"):
            module.read_file(path="src/app.py", max_lines=2001)

    def test_read_file_returns_content_for_repeated_same_range(self) -> None:
        """Repeated text reads should still return content after tracking."""
        module = cast("Any", read_file_module)
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(engine)
        with Session(engine) as db:
            db.add(
                SessionModel(
                    session_id="session-1",
                    agent_id=1,
                    user_id=1,
                    status="active",
                    chat_history='{"version": 1, "messages": []}',
                    react_llm_messages="[]",
                    react_llm_cache_state="{}",
                )
            )
            db.commit()

        context = SimpleNamespace(
            session_id="session-1",
            db_session_factory=lambda: Session(engine),
        )
        payload = {
            "path": "src/app.py",
            "total_lines": 3,
            "start_line": 1,
            "end_line": 3,
            "returned_line_count": 3,
            "has_more_before": False,
            "has_more_after": False,
            "truncated": False,
            "next_start_line": None,
            "previous_start_line": None,
            "content": "1 | a\n2 | b\n3 | c\n",
            "content_hash": "hash-a",
        }
        original_context = module.get_current_tool_execution_context
        original_read = module._read_text_in_sandbox
        module.get_current_tool_execution_context = lambda: context
        module._read_text_in_sandbox = lambda *_args: dict(payload)
        try:
            first = module.read_file(path="src/app.py")
            second = module.read_file(path="src/app.py")
        finally:
            module.get_current_tool_execution_context = original_context
            module._read_text_in_sandbox = original_read

        self.assertEqual(first["content"], payload["content"])
        self.assertEqual(second["content"], payload["content"])
        self.assertEqual(second["returned_line_count"], payload["returned_line_count"])

    def test_read_file_overlapping_range_returns_content(self) -> None:
        """Partially overlapping reads should return content when new lines exist."""
        module = cast("Any", read_file_module)
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(engine)
        with Session(engine) as db:
            db.add(
                SessionModel(
                    session_id="session-2",
                    agent_id=1,
                    user_id=1,
                    status="active",
                    chat_history='{"version": 1, "messages": []}',
                    react_llm_messages="[]",
                    react_llm_cache_state="{}",
                )
            )
            db.commit()

        context = SimpleNamespace(
            session_id="session-2",
            db_session_factory=lambda: Session(engine),
        )
        responses = [
            {
                "path": "src/app.py",
                "total_lines": 8,
                "start_line": 1,
                "end_line": 5,
                "returned_line_count": 5,
                "has_more_before": False,
                "has_more_after": True,
                "truncated": True,
                "next_start_line": 6,
                "previous_start_line": None,
                "content": "first chunk",
                "content_hash": "hash-a",
            },
            {
                "path": "src/app.py",
                "total_lines": 8,
                "start_line": 4,
                "end_line": 8,
                "returned_line_count": 5,
                "has_more_before": True,
                "has_more_after": False,
                "truncated": False,
                "next_start_line": None,
                "previous_start_line": 1,
                "content": "second chunk",
                "content_hash": "hash-a",
            },
        ]
        original_context = module.get_current_tool_execution_context
        original_read = module._read_text_in_sandbox
        module.get_current_tool_execution_context = lambda: context
        module._read_text_in_sandbox = lambda *_args: responses.pop(0)
        try:
            module.read_file(path="src/app.py", start_line=1, max_lines=5)
            second = module.read_file(path="src/app.py", start_line=4, max_lines=5)
        finally:
            module.get_current_tool_execution_context = original_context
            module._read_text_in_sandbox = original_read

        self.assertEqual(second["content"], "second chunk")
