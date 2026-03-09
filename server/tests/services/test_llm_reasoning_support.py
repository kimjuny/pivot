"""Unit tests for provider reasoning/thinking extraction."""

import sys
import unittest
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

AnthropicLLM = import_module("app.llm.anthropic_llm").AnthropicLLM
OpenAICompletionLLM = import_module("app.llm.openai_completion_llm").OpenAICompletionLLM
OpenAIResponseLLM = import_module("app.llm.openai_response_llm").OpenAIResponseLLM


class LlmReasoningSupportTestCase(unittest.TestCase):
    """Verify each supported protocol exposes provider reasoning text."""

    def test_openai_completion_extracts_reasoning_details(self) -> None:
        """Completion adapters should preserve provider reasoning text."""
        llm = OpenAICompletionLLM(
            endpoint="https://example.com/v1",
            model="gpt-test",
            api_key="secret",
        )

        response = llm._parse_dict_response(
            {
                "id": "resp-1",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": '{"action":{"action_type":"ANSWER","output":{"answer":"done"}}}',
                            "reasoning_details": [
                                {"text": "step one "},
                                {"text": "step two"},
                            ],
                        },
                    }
                ],
            },
            "gpt-test",
        )

        self.assertEqual(
            response.choices[0].message.reasoning_content,
            "step one step two",
        )

    def test_openai_response_extracts_reasoning_summary_blocks(self) -> None:
        """Responses adapters should expose reasoning returned in output items."""
        llm = OpenAIResponseLLM(
            endpoint="https://example.com/v1",
            model="gpt-test",
            api_key="secret",
        )

        response = llm._parse_dict_response(
            {
                "id": "resp-1",
                "status": "completed",
                "output_text": '{"action":{"action_type":"ANSWER","output":{"answer":"done"}}}',
                "output": [
                    {
                        "type": "reasoning",
                        "summary": [
                            {"type": "summary_text", "text": "first "},
                            {"type": "summary_text", "text": "second"},
                        ],
                    }
                ],
            },
            "gpt-test",
        )

        self.assertEqual(
            response.choices[0].message.reasoning_content,
            "first second",
        )

    def test_anthropic_extracts_non_stream_thinking_blocks(self) -> None:
        """Anthropic adapters should preserve non-stream thinking content."""
        response = SimpleNamespace(
            id="msg-1",
            model="claude-test",
            content=[
                SimpleNamespace(type="thinking", thinking="considering options"),
                SimpleNamespace(
                    type="text",
                    text='{"action":{"action_type":"ANSWER","output":{"answer":"done"}}}',
                ),
            ],
            stop_reason="end_turn",
            usage=None,
        )
        mock_client = SimpleNamespace(
            messages=SimpleNamespace(create=Mock(return_value=response))
        )

        with patch("app.llm.anthropic_llm.Anthropic", return_value=mock_client):
            llm = AnthropicLLM(
                endpoint="https://example.com",
                model="claude-test",
                api_key="secret",
            )

        converted = llm.chat([{"role": "user", "content": "hello"}])
        self.assertEqual(
            converted.choices[0].message.reasoning_content,
            "considering options",
        )

    def test_anthropic_extracts_stream_thinking_deltas(self) -> None:
        """Anthropic stream conversion should surface thinking deltas."""
        mock_client = SimpleNamespace(
            messages=SimpleNamespace(create=Mock(return_value=[]))
        )

        with patch("app.llm.anthropic_llm.Anthropic", return_value=mock_client):
            llm = AnthropicLLM(
                endpoint="https://example.com",
                model="claude-test",
                api_key="secret",
            )

        event = SimpleNamespace(
            id="msg-1",
            model="claude-test",
            type="content_block_delta",
            delta=SimpleNamespace(type="thinking_delta", thinking="live thought"),
        )

        converted = llm._convert_anthropic_response(
            event,
            is_stream_chunk=True,
        )
        self.assertEqual(
            converted.choices[0].message.reasoning_content,
            "live thought",
        )


if __name__ == "__main__":
    unittest.main()
