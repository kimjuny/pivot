"""Unit tests for the built-in sandbox edit_file tool."""

from __future__ import annotations

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

edit_file_module = import_module("app.orchestration.tool.builtin.edit_file")


class EditFileToolTestCase(unittest.TestCase):
    """Validate exact-text replacement and file creation behavior."""

    def test_script_replaces_unique_old_string(self) -> None:
        """The edit tool should replace the exact literal block once."""
        module = cast(Any, edit_file_module)
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "example.py"
            original = "before\nneedle\nafter\n"
            file_path.write_text(original, encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    module._EDIT_FILE_SCRIPT,
                    str(file_path),
                    "needle\n",
                    "replacement\n",
                    "1",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            updated = file_path.read_text(encoding="utf-8")

        self.assertIn("Successfully modified file", completed.stdout)
        self.assertEqual(updated, "before\nreplacement\nafter\n")

    def test_script_creates_new_file_when_old_string_is_empty(self) -> None:
        """An empty old_string should create a new file, not edit an existing one."""
        module = cast(Any, edit_file_module)
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "new_file.py"

            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    module._EDIT_FILE_SCRIPT,
                    str(file_path),
                    "",
                    "print('hello')\n",
                    "1",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            created = file_path.read_text(encoding="utf-8")

        self.assertIn("Created new file", completed.stdout)
        self.assertEqual(created, "print('hello')\n")

    def test_script_fails_when_match_count_is_wrong(self) -> None:
        """Ambiguous literal matches should fail instead of editing the wrong spot."""
        module = cast(Any, edit_file_module)
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "example.py"
            file_path.write_text("repeat\nrepeat\n", encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    module._EDIT_FILE_SCRIPT,
                    str(file_path),
                    "repeat\n",
                    "replacement\n",
                    "1",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("expected 1 occurrence(s)", completed.stderr)

    def test_edit_file_rejects_invalid_expected_replacements(self) -> None:
        """The public wrapper should validate obviously bad replacement counts."""
        module = cast(Any, edit_file_module)

        with self.assertRaisesRegex(ValueError, "greater than or equal to 1"):
            module.edit_file(
                path="src/app.py",
                old_string="old",
                new_string="new",
                expected_replacements=0,
            )
