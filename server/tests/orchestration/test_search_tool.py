"""Unit tests for the built-in sandbox search tool."""

from __future__ import annotations

import json
import sys
import unittest
from importlib import import_module
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

search_module = import_module("app.orchestration.tool.builtin.search")


class SearchToolTestCase(unittest.TestCase):
    """Validate the compact read-target contract of the search tool."""

    def test_search_translates_arguments_for_sandbox_execution(self) -> None:
        """The tool should pass the new candidate-oriented limits to sandbox."""
        captured_cmd: list[str] = []

        def fake_exec(cmd: list[str]) -> str:
            captured_cmd.extend(cmd)
            return json.dumps(
                {
                    "query": "UserService",
                    "path": "src",
                    "regex": False,
                    "case_sensitive": False,
                    "max_candidates": 8,
                    "max_hits_per_file": 3,
                    "total_matching_files": 1,
                    "returned_candidate_count": 1,
                    "truncated": False,
                    "candidates": [
                        {
                            "path": "src/user_service.py",
                            "match_count": 4,
                            "first_match_line": 12,
                            "last_match_line": 88,
                            "anchors_truncated": True,
                            "anchors": [
                                {
                                    "line_number": 12,
                                    "preview": "class UserService:",
                                }
                            ],
                        }
                    ],
                }
            )

        module = cast(Any, search_module)
        with (
            patch.object(module, "workspace_path", return_value="/workspace/src"),
            patch.object(module, "exec_in_sandbox", side_effect=fake_exec),
        ):
            result = module.search(
                query="UserService",
                path="src",
                regex=False,
                case_sensitive=False,
                max_candidates=8,
                max_hits_per_file=3,
            )

        self.assertEqual(result["query"], "UserService")
        self.assertEqual(result["returned_candidate_count"], 1)
        self.assertEqual(result["candidates"][0]["path"], "src/user_service.py")
        self.assertEqual(captured_cmd[0:3], ["python3", "-c", module._SEARCH_SCRIPT])
        self.assertEqual(
            captured_cmd[3:],
            ["/workspace/src", "UserService", "0", "0", "8", "3"],
        )

    def test_search_rejects_invalid_candidate_limit(self) -> None:
        """Large candidate lists should be rejected to keep the tool concise."""
        module = cast(Any, search_module)

        with self.assertRaisesRegex(ValueError, "less than or equal to 20"):
            module.search(query="needle", max_candidates=21)

    def test_search_rejects_invalid_hits_per_file_limit(self) -> None:
        """Too many anchors per file should fail fast before sandbox execution."""
        module = cast(Any, search_module)

        with self.assertRaisesRegex(ValueError, "less than or equal to 5"):
            module.search(query="needle", max_hits_per_file=6)

    def test_search_rejects_blank_query(self) -> None:
        """Blank queries should fail fast to avoid meaningless scans."""
        module = cast(Any, search_module)

        with self.assertRaisesRegex(ValueError, "must not be blank"):
            module.search(query="   ")
