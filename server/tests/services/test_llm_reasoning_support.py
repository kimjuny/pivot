"""Unit tests for provider reasoning/thinking extraction."""

import sys
import unittest
from importlib import import_module
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

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


if __name__ == "__main__":
    unittest.main()

