"""HTTP error diagnostics tests for Chat Completions adapters."""

import sys
import unittest
from importlib import import_module
from pathlib import Path
from unittest.mock import Mock, patch

import requests

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

OpenAICompletionLLM = import_module("app.llm.openai_completion_llm").OpenAICompletionLLM


class OpenAICompletionErrorsTestCase(unittest.TestCase):
    """Verify provider HTTP failures surface actionable diagnostics."""

    def test_chat_stream_http_error_includes_json_summary_and_request_id(self) -> None:
        """Streaming errors should expose parsed provider metadata."""
        llm = OpenAICompletionLLM(
            endpoint="https://example.com/v1",
            model="qianfan-test",
            api_key="secret",
        )

        response = Mock()
        response.status_code = 403
        response.headers = {
            "content-type": "application/json",
            "x-bce-request-id": "req-123",
        }
        response.json.return_value = {
            "error_code": 336007,
            "error_msg": "IAM signature check failed",
        }
        response.text = '{"error_code":336007,"error_msg":"IAM signature check failed"}'

        http_error = requests.exceptions.HTTPError(response=response)
        stream_response = Mock()
        stream_response.__enter__ = Mock(return_value=stream_response)
        stream_response.__exit__ = Mock(return_value=None)
        stream_response.raise_for_status.side_effect = http_error

        with (
            patch(
                "app.llm.openai_completion_llm.requests.post",
                return_value=stream_response,
            ),
            self.assertRaises(RuntimeError) as raised,
        ):
            list(llm.chat_stream([{"role": "user", "content": "hello"}]))

        message = str(raised.exception)
        self.assertIn("HTTP 403", message)
        self.assertIn("error_code", message)
        self.assertIn("IAM signature check failed", message)
        self.assertIn("request_id=req-123", message)
        self.assertIn("content_type=application/json", message)


if __name__ == "__main__":
    unittest.main()
