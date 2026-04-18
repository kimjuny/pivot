"""Unit tests for the built-in sandbox list_directories tool."""

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

list_directories_module = import_module("app.orchestration.tool.builtin.list_directories")


class ListDirectoriesToolTestCase(unittest.TestCase):
    """Validate the inline sandbox helper script used by list_directories."""

    def test_script_lists_direct_children_without_syntax_error(self) -> None:
        """The embedded Python script should execute and list children cleanly."""
        module = cast(Any, list_directories_module)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "alpha.txt").write_text("alpha\n", encoding="utf-8")
            (root / "nested").mkdir()

            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    module._LIST_DIRECTORIES_SCRIPT,
                    str(root),
                    "[]",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip().splitlines(), ["alpha.txt", "nested/"])

