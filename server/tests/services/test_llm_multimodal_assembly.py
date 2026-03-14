"""Transport-level tests for multimodal request assembly."""

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


class LlmMultimodalAssemblyTestCase(unittest.TestCase):
    """Verify each protocol keeps image base64 data in the final request body."""

    def setUp(self) -> None:
        """Build a neutral multimodal user turn shared by all protocol tests."""
        self.messages = [
            {"role": "system", "content": "You are helpful."},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            'Attached image: "diagram.png"\n'
                            "MIME type: image/png\n"
                            "Dimensions: 16x12"
                        ),
                    },
                    {
                        "type": "image",
                        "media_type": "image/png",
                        "data": "YWJj",
                    },
                ],
            },
            {"role": "assistant", "content": "I see a diagram."},
        ]

    def test_openai_completion_assembles_data_url_image_blocks(self) -> None:
        """Chat Completions payloads should carry image data URLs in user content."""
        llm = OpenAICompletionLLM(
            endpoint="https://example.com/v1",
            model="gpt-test",
            api_key="secret",
        )
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "id": "resp-1",
            "choices": [
                {"message": {"role": "assistant", "content": "done"}, "index": 0}
            ],
        }

        with patch(
            "app.llm.openai_completion_llm.requests.post", return_value=response
        ) as mocked_post:
            llm.chat(self.messages)

        payload = mocked_post.call_args.kwargs["json"]
        user_content = payload["messages"][1]["content"]
        self.assertEqual(user_content[0]["type"], "text")
        self.assertEqual(user_content[1]["type"], "image_url")
        self.assertEqual(
            user_content[1]["image_url"]["url"],
            "data:image/png;base64,YWJj",
        )

    def test_qwen_cache_normalizes_text_messages_and_marks_recent_blocks(
        self,
    ) -> None:
        """Qwen block cache should keep text history structurally stable.

        Why: rolling cache reuse depends on prior prompt prefixes being serialized
        the same way across iterations, even after a message is no longer the last
        message in the request.
        """
        llm = OpenAICompletionLLM(
            endpoint="https://example.com/v1",
            model="qwen-test",
            api_key="secret",
            cache_policy="qwen-completion-block-cache",
        )
        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Iteration 1"},
            {"role": "assistant", "content": "Thought 1"},
            {"role": "user", "content": "Iteration 2"},
            {"role": "assistant", "content": "Thought 2"},
        ]

        normalized_messages = llm._messages_with_qwen_cache_markers(messages)

        self.assertEqual(normalized_messages[0]["content"][0]["text"], "System prompt")
        self.assertNotIn(
            "cache_control",
            normalized_messages[0]["content"][0],
        )
        for index in range(1, len(normalized_messages)):
            self.assertIsInstance(normalized_messages[index]["content"], list)
            self.assertEqual(
                normalized_messages[index]["content"][-1]["cache_control"],
                {"type": "ephemeral"},
            )

    def test_qwen_stream_includes_usage_and_cache_reporting(self) -> None:
        """Qwen streaming requests should ask for usage so cache hits are observable."""
        llm = OpenAICompletionLLM(
            endpoint="https://example.com/v1",
            model="qwen-test",
            api_key="secret",
            cache_policy="qwen-completion-block-cache",
        )
        stream_response = Mock()
        stream_response.raise_for_status.return_value = None
        stream_response.iter_lines.return_value = [
            (
                b'data: {"id":"resp-1","choices":[{"index":0,"delta":{"role":"assistant","content":"done"}}]}'
            ),
            (
                b'data: {"id":"resp-1","choices":[],"usage":{"prompt_tokens":1200,"completion_tokens":20,"total_tokens":1220,"prompt_tokens_details":{"cached_tokens":900}}}'
            ),
            b"data: [DONE]",
        ]
        stream_response.__enter__ = Mock(return_value=stream_response)
        stream_response.__exit__ = Mock(return_value=None)

        with patch(
            "app.llm.openai_completion_llm.requests.post", return_value=stream_response
        ) as mocked_post:
            chunks = list(
                llm.chat_stream(
                    [{"role": "system", "content": "System prompt"}],
                )
            )

        payload = mocked_post.call_args.kwargs["json"]
        self.assertTrue(payload["stream"])
        self.assertEqual(
            payload["stream_options"],
            {"include_usage": True},
        )
        self.assertEqual(chunks[-1].usage.cached_input_tokens, 900)

    def test_openai_response_assembles_input_image_and_output_text_history(
        self,
    ) -> None:
        """Responses payloads should keep image blocks and tag assistant history correctly."""
        llm = OpenAIResponseLLM(
            endpoint="https://example.com/v1",
            model="gpt-test",
            api_key="secret",
        )
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "id": "resp-1",
            "status": "completed",
            "output_text": "done",
            "output": [],
        }

        with patch(
            "app.llm.openai_response_llm.requests.post", return_value=response
        ) as mocked_post:
            llm.chat(self.messages)

        payload = mocked_post.call_args.kwargs["json"]
        user_content = payload["input"][1]["content"]
        assistant_content = payload["input"][2]["content"]
        self.assertEqual(user_content[0]["type"], "input_text")
        self.assertEqual(user_content[1]["type"], "input_image")
        self.assertEqual(
            user_content[1]["image_url"],
            "data:image/png;base64,YWJj",
        )
        self.assertEqual(assistant_content[0]["type"], "output_text")
        self.assertEqual(assistant_content[0]["text"], "I see a diagram.")

    def test_anthropic_assembles_base64_image_source_blocks(self) -> None:
        """Anthropic payloads should send image blocks with base64 sources."""
        response = SimpleNamespace(
            id="msg-1",
            model="claude-test",
            content=[SimpleNamespace(type="text", text="done")],
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

        llm.chat(self.messages)

        payload = mock_client.messages.create.call_args.kwargs
        user_content = payload["messages"][0]["content"]
        self.assertEqual(payload["system"], "You are helpful.")
        self.assertEqual(user_content[0]["type"], "text")
        self.assertEqual(user_content[1]["type"], "image")
        self.assertEqual(user_content[1]["source"]["type"], "base64")
        self.assertEqual(user_content[1]["source"]["media_type"], "image/png")
        self.assertEqual(user_content[1]["source"]["data"], "YWJj")


if __name__ == "__main__":
    unittest.main()
