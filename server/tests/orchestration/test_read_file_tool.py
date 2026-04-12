"""Unit tests for the built-in sandbox read_file tool."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from importlib import import_module
from pathlib import Path
from typing import Any, cast

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

read_file_module = import_module("app.orchestration.tool.builtin.read_file")


class ReadFileToolTestCase(unittest.TestCase):
    """Validate exact-content chunk reading for edit workflows."""

    def test_script_returns_exact_chunk_without_line_numbers(self) -> None:
        """The returned content should match the file text exactly."""
        module = cast(Any, read_file_module)
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
        self.assertNotIn("2:", payload["content"])

    def test_script_truncates_requested_range_by_max_lines(self) -> None:
        """Chunk metadata should tell the caller when more lines remain."""
        module = cast(Any, read_file_module)
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

    def test_read_file_rejects_large_max_lines(self) -> None:
        """Huge chunks should fail fast to keep reads focused."""
        module = cast(Any, read_file_module)

        with self.assertRaisesRegex(ValueError, "less than or equal to 800"):
            module.read_file(path="src/app.py", max_lines=801)
