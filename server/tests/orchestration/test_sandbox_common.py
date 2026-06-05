"""Unit tests for sandbox tool shared helpers."""

from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

sandbox_common = import_module("app.orchestration.tool.builtin._sandbox_common")


def md5_text(value: str) -> str:
    return hashlib.md5(value.encode("utf-8"), usedforsecurity=False).hexdigest()


class SandboxCommonTestCase(unittest.TestCase):
    """Validate backend-visible workspace safeguards."""

    def test_verify_backend_visible_text_file_accepts_matching_state(self) -> None:
        module = cast("Any", sandbox_common)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "app.py"
            target.write_text("hello\n", encoding="utf-8")
            context = SimpleNamespace(workspace_backend_path=str(root))

            with patch.object(
                module,
                "get_current_tool_execution_context",
                return_value=context,
            ):
                module.verify_backend_visible_text_file(
                    "app.py",
                    expected_hash=md5_text("hello\n"),
                    expected_total_lines=1,
                )

    def test_verify_backend_visible_text_file_rejects_hidden_sandbox_write(
        self,
    ) -> None:
        module = cast("Any", sandbox_common)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "app.py"
            target.write_text("old\n", encoding="utf-8")
            context = SimpleNamespace(workspace_backend_path=str(root))

            with (
                patch.object(
                    module,
                    "get_current_tool_execution_context",
                    return_value=context,
                ),
                self.assertRaisesRegex(RuntimeError, "not visible"),
            ):
                module.verify_backend_visible_text_file(
                    "app.py",
                    expected_hash=md5_text("new\n"),
                    expected_total_lines=1,
                )


if __name__ == "__main__":
    unittest.main()
