"""Unit tests for the built-in sandbox write_file tool."""

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

write_file_module = import_module("app.orchestration.tool.builtin.write_file")


def md5_text(value: str) -> str:
    return hashlib.md5(value.encode("utf-8"), usedforsecurity=False).hexdigest()


class WriteFileToolTestCase(unittest.TestCase):
    """Validate create and guarded overwrite behavior."""

    def test_script_creates_missing_file_without_prior_read(self) -> None:
        module = cast("Any", write_file_module)
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "example.py"

            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    module._WRITE_FILE_SCRIPT,
                    str(file_path),
                    "created\n",
                    "",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            updated = file_path.read_text(encoding="utf-8")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["type"], "create")
        self.assertEqual(payload["diff"], "")
        self.assertEqual(updated, "created\n")

    def test_script_rejects_overwrite_without_prior_read(self) -> None:
        module = cast("Any", write_file_module)
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "example.py"
            file_path.write_text("original\n", encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    module._WRITE_FILE_SCRIPT,
                    str(file_path),
                    "updated\n",
                    "",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            updated = file_path.read_text(encoding="utf-8")

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("Read the full file", completed.stderr)
        self.assertEqual(updated, "original\n")

    def test_script_overwrites_when_hash_matches(self) -> None:
        module = cast("Any", write_file_module)
        original = "original\n"
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "example.py"
            file_path.write_text(original, encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    module._WRITE_FILE_SCRIPT,
                    str(file_path),
                    "updated\n",
                    md5_text(original),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            updated = file_path.read_text(encoding="utf-8")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["type"], "update")
        self.assertIn("-original", payload["diff"])
        self.assertIn("+updated", payload["diff"])
        self.assertEqual(updated, "updated\n")
