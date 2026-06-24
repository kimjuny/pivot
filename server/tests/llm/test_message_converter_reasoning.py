"""Unit tests for reasoning_content replay across all provider converters."""

import sys
import unittest
from importlib import import_module
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

message_converter = import_module("app.llm.message_converter")


class OpenAICompletionReasoningTestCase(unittest.TestCase):
    """OpenAI Completion (DeepSeek/Qwen/Kimi/GLM) reasoning replay."""

    def test_reasoning_replayed_on_assistant_history(self) -> None:
        messages = [
            {
                "role": "assistant",
                "content": "answer text",
                "reasoning_content": "my chain of thought",
            }
        ]
        out = message_converter.to_openai_completion_messages(messages)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["role"], "assistant")
        self.assertEqual(out[0]["content"], "answer text")
        self.assertEqual(out[0]["reasoning_content"], "my chain of thought")

    def test_empty_reasoning_not_replayed(self) -> None:
        messages = [
            {"role": "assistant", "content": "answer text"},
        ]
        out = message_converter.to_openai_completion_messages(messages)
        self.assertNotIn("reasoning_content", out[0])

    def test_blank_string_reasoning_not_replayed(self) -> None:
        messages = [
            {"role": "assistant", "content": "answer text", "reasoning_content": ""},
        ]
        out = message_converter.to_openai_completion_messages(messages)
        self.assertNotIn("reasoning_content", out[0])


class OpenAIResponseReasoningTestCase(unittest.TestCase):
    """OpenAI Responses API reasoning replay."""

    def test_reasoning_emitted_as_standalone_item(self) -> None:
        messages = [
            {
                "role": "assistant",
                "content": "answer text",
                "reasoning_content": "my reasoning",
            }
        ]
        out = message_converter.to_openai_response_messages(messages)
        # reasoning item comes first, then the assistant message
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["type"], "reasoning")
        self.assertEqual(
            out[0]["content"],
            [{"type": "reasoning_text", "text": "my reasoning"}],
        )
        self.assertEqual(out[1]["role"], "assistant")

    def test_no_reasoning_item_when_absent(self) -> None:
        messages = [{"role": "assistant", "content": "answer text"}]
        out = message_converter.to_openai_response_messages(messages)
        self.assertEqual(len(out), 1)
        self.assertNotIn("type", out[0])


class AnthropicReasoningTestCase(unittest.TestCase):
    """Anthropic Messages API reasoning replay."""

    def test_thinking_block_precedes_text(self) -> None:
        messages = [
            {
                "role": "assistant",
                "content": "answer text",
                "reasoning_content": "my thinking",
            }
        ]
        _system, formatted = message_converter.to_anthropic_messages(messages)
        self.assertEqual(len(formatted), 1)
        blocks = formatted[0]["content"]
        self.assertEqual(blocks[0], {"type": "thinking", "thinking": "my thinking"})
        self.assertEqual(blocks[1], {"type": "text", "text": "answer text"})

    def test_thinking_block_precedes_tool_use(self) -> None:
        messages = [
            {
                "role": "assistant",
                "content": "",
                "reasoning_content": "deciding to call a tool",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "name": "search",
                        "arguments": '{"q": "test"}',
                    }
                ],
            }
        ]
        _system, formatted = message_converter.to_anthropic_messages(messages)
        blocks = formatted[0]["content"]
        # thinking first, then tool_use
        self.assertEqual(blocks[0]["type"], "thinking")
        self.assertEqual(blocks[1]["type"], "tool_use")

    def test_plain_string_content_when_no_reasoning_or_tools(self) -> None:
        messages = [{"role": "assistant", "content": "answer text"}]
        _system, formatted = message_converter.to_anthropic_messages(messages)
        self.assertEqual(formatted[0]["content"], "answer text")


class GeminiReasoningTestCase(unittest.TestCase):
    """Gemini reasoning replay."""

    def test_thought_part_precedes_text(self) -> None:
        messages = [
            {
                "role": "assistant",
                "content": "answer text",
                "reasoning_content": "my reasoning",
            }
        ]
        _system, contents = message_converter.to_gemini_messages(messages)
        self.assertEqual(len(contents), 1)
        parts = contents[0]["parts"]
        self.assertEqual(parts[0], {"text": "my reasoning", "thought": True})
        self.assertEqual(parts[1], {"text": "answer text"})

    def test_no_thought_part_when_reasoning_absent(self) -> None:
        messages = [{"role": "assistant", "content": "answer text"}]
        _system, contents = message_converter.to_gemini_messages(messages)
        parts = contents[0]["parts"]
        self.assertEqual(parts, [{"text": "answer text"}])

    def test_user_message_never_gets_thought_part(self) -> None:
        messages = [
            {
                "role": "user",
                "content": "hello",
                "reasoning_content": "should be ignored",
            }
        ]
        _system, contents = message_converter.to_gemini_messages(messages)
        parts = contents[0]["parts"]
        self.assertEqual(parts, [{"text": "hello"}])


if __name__ == "__main__":
    unittest.main()
