"""Unit tests for the built-in sandbox edit_file tool."""

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

edit_file_module = import_module("app.orchestration.tool.builtin.edit_file")


class EditFileToolTestCase(unittest.TestCase):
    """Validate single-file unified diff application behavior."""

    def test_script_applies_multiple_hunks_atomically(self) -> None:
        """The edit tool should apply multiple hunks in one file."""
        module = cast(Any, edit_file_module)
        diff = """--- a/example.py
+++ b/example.py
@@ -1,3 +1,3 @@
 before
-old one
+new one
 middle
@@ -5,3 +5,4 @@
 tail
-old two
+new two
+extra
 done
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "example.py"
            original = "before\nold one\nmiddle\nspacer\ntail\nold two\ndone\n"
            file_path.write_text(original, encoding="utf-8")

            completed = subprocess.run(
                [sys.executable, "-c", module._EDIT_FILE_SCRIPT, str(file_path), diff],
                check=False,
                capture_output=True,
                text=True,
            )

            updated = file_path.read_text(encoding="utf-8")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["hunk_count"], 2)
        self.assertEqual(payload["added_lines"], 3)
        self.assertEqual(payload["removed_lines"], 2)
        self.assertEqual(payload["warnings"], [])
        self.assertEqual(
            updated,
            "before\nnew one\nmiddle\nspacer\ntail\nnew two\nextra\ndone\n",
        )

    def test_script_fails_without_writing_when_later_hunk_misses(self) -> None:
        """A later failed hunk should roll back the whole edit_file call."""
        module = cast(Any, edit_file_module)
        diff = """--- a/example.py
+++ b/example.py
@@ -1,2 +1,2 @@
 alpha
-beta
+BETA
@@ -3,2 +3,2 @@
 gamma
-missing
+MISSING
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "example.py"
            original = "alpha\nbeta\ngamma\ndelta\n"
            file_path.write_text(original, encoding="utf-8")

            completed = subprocess.run(
                [sys.executable, "-c", module._EDIT_FILE_SCRIPT, str(file_path), diff],
                check=False,
                capture_output=True,
                text=True,
            )

            updated = file_path.read_text(encoding="utf-8")

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("Patch failed at hunk 2", completed.stderr)
        self.assertIn("old_start is the strict location anchor", completed.stderr)
        self.assertIn("Expected old/context lines", completed.stderr)
        self.assertIn("Actual file lines there", completed.stderr)
        self.assertEqual(updated, original)

    def test_script_accepts_hunks_without_file_headers(self) -> None:
        """The path argument should be the only required target file signal."""
        module = cast(Any, edit_file_module)
        diff = """@@ -1,1 +1,1 @@
-old
+new
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "example.py"
            original = "old\n"
            file_path.write_text(original, encoding="utf-8")

            completed = subprocess.run(
                [sys.executable, "-c", module._EDIT_FILE_SCRIPT, str(file_path), diff],
                check=False,
                capture_output=True,
                text=True,
            )

            updated = file_path.read_text(encoding="utf-8")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["warnings"], [])
        self.assertEqual(updated, "new\n")

    def test_script_tolerates_count_mismatch_with_warning(self) -> None:
        """Hunk counts are advisory; body matching remains the safety check."""
        module = cast(Any, edit_file_module)
        diff = """@@ -1,7 +1,7 @@
 alpha
-old
+new
 gamma
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "example.py"
            file_path.write_text("alpha\nold\ngamma\n", encoding="utf-8")

            completed = subprocess.run(
                [sys.executable, "-c", module._EDIT_FILE_SCRIPT, str(file_path), diff],
                check=False,
                capture_output=True,
                text=True,
            )

            updated = file_path.read_text(encoding="utf-8")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertIn("old_count=7", payload["warnings"][0])
        self.assertIn("new_count=7", payload["warnings"][1])
        self.assertEqual(updated, "alpha\nnew\ngamma\n")

    def test_script_rejects_file_headers_after_first_hunk(self) -> None:
        """A multi-file-looking diff should not be accepted silently."""
        module = cast(Any, edit_file_module)
        diff = """@@ -1,1 +1,1 @@
-old
+new
--- a/other.py
+++ b/other.py
@@ -1,1 +1,1 @@
-other
+changed
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "example.py"
            original = "old\n"
            file_path.write_text(original, encoding="utf-8")

            completed = subprocess.run(
                [sys.executable, "-c", module._EDIT_FILE_SCRIPT, str(file_path), diff],
                check=False,
                capture_output=True,
                text=True,
            )

            updated = file_path.read_text(encoding="utf-8")

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "file headers are only allowed before the first hunk", completed.stderr
        )
        self.assertEqual(updated, original)

    def test_script_rejects_full_git_diff_metadata(self) -> None:
        """The tool should keep the agent-facing format small and explicit."""
        module = cast(Any, edit_file_module)
        diff = """diff --git a/example.py b/example.py
index 1234567..89abcde 100644
--- a/example.py
+++ b/example.py
@@ -1,1 +1,1 @@
-old
+new
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "example.py"
            file_path.write_text("old\n", encoding="utf-8")

            completed = subprocess.run(
                [sys.executable, "-c", module._EDIT_FILE_SCRIPT, str(file_path), diff],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("simplified unified diff", completed.stderr)

    def test_edit_file_rejects_empty_diff(self) -> None:
        """The public wrapper should validate obviously empty patches."""
        module = cast(Any, edit_file_module)

        with self.assertRaisesRegex(ValueError, "non-empty unified diff"):
            module.edit_file(path="src/app.py", diff="")
