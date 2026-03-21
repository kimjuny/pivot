"""Unit tests for the abstract web_search tool."""

from __future__ import annotations

import sys
import unittest
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

from sqlmodel import create_engine

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

tool_module = import_module("app.orchestration.tool.builtin.web_search")
types_module = import_module("app.orchestration.web_search.types")


class WebSearchToolTestCase(unittest.TestCase):
    """Validate noisy LLM inputs are normalized at the tool boundary."""

    def test_web_search_normalizes_noisy_llm_arguments(self) -> None:
        """Trailing newlines and aliases should not cause tool execution failure."""
        captured_request: object | None = None
        fake_result = types_module.WebSearchExecutionResult(
            query="2026 deep learning breakthrough research papers",
            provider={"key": "tavily", "name": "Tavily"},
            results=[],
        )

        def fake_execute_search(*, agent_id: int, request: object):
            nonlocal captured_request
            self.assertEqual(agent_id, 7)
            captured_request = request
            return fake_result

        with (
            patch.object(
                tool_module,
                "get_current_tool_execution_context",
                return_value=SimpleNamespace(agent_id=7),
            ),
            patch.object(
                tool_module, "get_engine", return_value=create_engine("sqlite://")
            ),
            patch.object(
                tool_module.WebSearchService,
                "execute_search",
                side_effect=fake_execute_search,
            ),
        ):
            result = tool_module.web_search(
                query="2026 deep learning breakthrough research papers\n",
                topic="general\n",
                time_range="m\n",
                start_date="2026-01-01\n",
                max_results=15,
            )

        self.assertEqual(result["provider"]["key"], "tavily")
        self.assertIsNotNone(captured_request)
        request = cast(Any, captured_request)
        self.assertEqual(
            request.query, "2026 deep learning breakthrough research papers"
        )
        self.assertEqual(request.topic, "general")
        self.assertEqual(request.time_range, "month")
        self.assertEqual(request.start_date, "2026-01-01")

    def test_web_search_prefers_turn_scoped_provider_over_tool_arguments(self) -> None:
        """A chat-selected provider should override the model-supplied provider."""
        captured_request: object | None = None
        fake_result = types_module.WebSearchExecutionResult(
            query="latest ai regulations",
            provider={"key": "baidu", "name": "Baidu"},
            results=[],
        )

        def fake_execute_search(*, agent_id: int, request: object):
            nonlocal captured_request
            self.assertEqual(agent_id, 7)
            captured_request = request
            return fake_result

        with (
            patch.object(
                tool_module,
                "get_current_tool_execution_context",
                return_value=SimpleNamespace(agent_id=7, web_search_provider="baidu"),
            ),
            patch.object(
                tool_module, "get_engine", return_value=create_engine("sqlite://")
            ),
            patch.object(
                tool_module.WebSearchService,
                "execute_search",
                side_effect=fake_execute_search,
            ),
        ):
            result = tool_module.web_search(
                query="latest ai regulations",
                provider="tavily",
            )

        self.assertEqual(result["provider"]["key"], "baidu")
        self.assertIsNotNone(captured_request)
        request = cast(Any, captured_request)
        self.assertEqual(request.provider, "baidu")

    def test_web_search_surfaces_invalid_turn_scoped_provider_errors(self) -> None:
        """Invalid chat-selected providers should fail clearly instead of falling back."""
        expected_error = (
            "Enabled web search provider 'missing' is not configured for agent 7."
        )

        def fake_execute_search(*, agent_id: int, request: object):
            self.assertEqual(agent_id, 7)
            request_payload = cast(Any, request)
            self.assertEqual(request_payload.provider, "missing")
            raise ValueError(expected_error)

        with (
            patch.object(
                tool_module,
                "get_current_tool_execution_context",
                return_value=SimpleNamespace(agent_id=7, web_search_provider="missing"),
            ),
            patch.object(
                tool_module, "get_engine", return_value=create_engine("sqlite://")
            ),
            patch.object(
                tool_module.WebSearchService,
                "execute_search",
                side_effect=fake_execute_search,
            ),
            self.assertRaisesRegex(ValueError, "not configured"),
        ):
            tool_module.web_search(
                query="latest ai regulations",
                provider="tavily",
            )


if __name__ == "__main__":
    unittest.main()
