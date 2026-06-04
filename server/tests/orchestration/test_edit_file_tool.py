"""Unit tests for the built-in sandbox edit_file tool."""

from __future__ import annotations

import hashlib
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

edit_file_module = import_module("app.orchestration.tool.builtin.edit_file")


def md5_text(value: str) -> str:
    return hashlib.md5(value.encode("utf-8"), usedforsecurity=False).hexdigest()


class EditFileToolTestCase(unittest.TestCase):
    """Validate exact string replacement behavior."""

    def test_script_replaces_unique_string_and_returns_diff(self) -> None:
        module = cast("Any", edit_file_module)
        original = "alpha\nold value\ngamma\n"
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "example.py"
            file_path.write_text(original, encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    module._EDIT_FILE_SCRIPT,
                    str(file_path),
                    "old value",
                    "new value",
                    "false",
                    md5_text(original),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            updated = file_path.read_text(encoding="utf-8")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(updated, "alpha\nnew value\ngamma\n")
        self.assertEqual(payload["replacement_count"], 1)
        self.assertEqual(payload["added_lines"], 1)
        self.assertEqual(payload["removed_lines"], 1)
        self.assertIn("-old value", payload["diff"])
        self.assertIn("+new value", payload["diff"])

    def test_script_rejects_multiple_matches_without_replace_all(self) -> None:
        module = cast("Any", edit_file_module)
        original = "target\nmiddle\ntarget\n"
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "example.py"
            file_path.write_text(original, encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    module._EDIT_FILE_SCRIPT,
                    str(file_path),
                    "target",
                    "updated",
                    "false",
                    md5_text(original),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            updated = file_path.read_text(encoding="utf-8")

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("Found 2 matches", completed.stderr)
        self.assertEqual(updated, original)

    def test_script_replace_all_updates_every_match(self) -> None:
        module = cast("Any", edit_file_module)
        original = "target\nmiddle\ntarget\n"
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "example.py"
            file_path.write_text(original, encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    module._EDIT_FILE_SCRIPT,
                    str(file_path),
                    "target",
                    "updated",
                    "true",
                    md5_text(original),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            updated = file_path.read_text(encoding="utf-8")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["replacement_count"], 2)
        self.assertEqual(updated, "updated\nmiddle\nupdated\n")

    def test_script_rejects_changed_file_hash(self) -> None:
        module = cast("Any", edit_file_module)
        original = "old\n"
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "example.py"
            file_path.write_text("changed\n", encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    module._EDIT_FILE_SCRIPT,
                    str(file_path),
                    "changed",
                    "updated",
                    "false",
                    md5_text(original),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            updated = file_path.read_text(encoding="utf-8")

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("File has changed since it was read", completed.stderr)
        self.assertEqual(updated, "changed\n")

    def test_script_creates_missing_file_when_old_string_is_empty(self) -> None:
        module = cast("Any", edit_file_module)
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "example.py"

            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    module._EDIT_FILE_SCRIPT,
                    str(file_path),
                    "",
                    "created\n",
                    "false",
                    "",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            updated = file_path.read_text(encoding="utf-8")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["replacement_count"], 1)
        self.assertEqual(updated, "created\n")

    def test_edit_file_rejects_unread_existing_file(self) -> None:
        module = cast("Any", edit_file_module)

        with self.assertRaisesRegex(RuntimeError, "requires read_file"):
            module.edit_file(
                path="src/app.py",
                old_string="old",
                new_string="new",
            )
