"""OpenRouter attribution header injection tests."""

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
build_openrouter_attribution_headers = import_module(
    "app.llm.openrouter_attribution"
).build_openrouter_attribution_headers


class OpenRouterAttributionTestCase(unittest.TestCase):
    """Verify OpenRouter app attribution is injected only when configured."""

    def test_helper_returns_headers_for_openrouter_endpoint(self) -> None:
        """Configured OpenRouter endpoints should receive all attribution headers."""
        settings = SimpleNamespace(
            OPENROUTER_APP_URL="https://pivot.fun",
            OPENROUTER_APP_TITLE="Pivot",
            OPENROUTER_APP_CATEGORIES="programming-app,cloud-agent",
            PROJECT_NAME="Pivot Server",
        )

        with patch(
            "app.llm.openrouter_attribution.get_settings",
            return_value=settings,
        ):
            headers = build_openrouter_attribution_headers(
                "https://openrouter.ai/api/v1"
            )

        self.assertEqual(
            headers,
            {
                "HTTP-Referer": "https://pivot.fun",
                "X-OpenRouter-Title": "Pivot",
                "X-OpenRouter-Categories": "programming-app,cloud-agent",
            },
        )

    def test_helper_skips_non_openrouter_endpoint(self) -> None:
        """Non-OpenRouter providers should never receive attribution headers."""
        settings = SimpleNamespace(
            OPENROUTER_APP_URL="https://pivot.fun",
            OPENROUTER_APP_TITLE="Pivot",
            OPENROUTER_APP_CATEGORIES="programming-app",
            PROJECT_NAME="Pivot Server",
        )

        with patch(
            "app.llm.openrouter_attribution.get_settings",
            return_value=settings,
        ):
            headers = build_openrouter_attribution_headers("https://api.openai.com/v1")

        self.assertEqual(headers, {})

    def test_openai_completion_chat_includes_openrouter_headers(self) -> None:
        """Chat Completions requests should expose configured app attribution."""
        llm = OpenAICompletionLLM(
            endpoint="https://openrouter.ai/api/v1",
            model="openai/gpt-4o-mini",
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
        settings = SimpleNamespace(
            OPENROUTER_APP_URL="https://pivot.fun",
            OPENROUTER_APP_TITLE="Pivot",
            OPENROUTER_APP_CATEGORIES="programming-app,cloud-agent",
            PROJECT_NAME="Pivot Server",
        )

        with (
            patch(
                "app.llm.openrouter_attribution.get_settings",
                return_value=settings,
            ),
            patch(
                "app.llm.openai_completion_llm.requests.post",
                return_value=response,
            ) as mocked_post,
        ):
            llm.chat([{"role": "user", "content": "hello"}])

        headers = mocked_post.call_args.kwargs["headers"]
        self.assertEqual(headers["HTTP-Referer"], "https://pivot.fun")
        self.assertEqual(headers["X-OpenRouter-Title"], "Pivot")
        self.assertEqual(
            headers["X-OpenRouter-Categories"],
            "programming-app,cloud-agent",
        )

    def test_openai_response_chat_skips_headers_for_other_providers(self) -> None:
        """Responses requests should leave non-OpenRouter providers untouched."""
        llm = OpenAIResponseLLM(
            endpoint="https://api.openai.com/v1",
            model="gpt-4.1-mini",
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
        settings = SimpleNamespace(
            OPENROUTER_APP_URL="https://pivot.fun",
            OPENROUTER_APP_TITLE="Pivot",
            OPENROUTER_APP_CATEGORIES="programming-app",
            PROJECT_NAME="Pivot Server",
        )

        with (
            patch(
                "app.llm.openrouter_attribution.get_settings",
                return_value=settings,
            ),
            patch(
                "app.llm.openai_response_llm.requests.post",
                return_value=response,
            ) as mocked_post,
        ):
            llm.chat([{"role": "user", "content": "hello"}])

        headers = mocked_post.call_args.kwargs["headers"]
        self.assertNotIn("HTTP-Referer", headers)
        self.assertNotIn("X-OpenRouter-Title", headers)
        self.assertNotIn("X-OpenRouter-Categories", headers)

    def test_anthropic_headers_include_openrouter_attribution(self) -> None:
        """Anthropic-compatible requests should also include OpenRouter headers."""
        llm = AnthropicLLM(
            endpoint="https://openrouter.ai/api",
            model="anthropic/claude-3.7-sonnet",
            api_key="secret",
        )
        settings = SimpleNamespace(
            OPENROUTER_APP_URL="https://pivot.fun",
            OPENROUTER_APP_TITLE="Pivot",
            OPENROUTER_APP_CATEGORIES="programming-app,cloud-agent",
            PROJECT_NAME="Pivot Server",
        )

        with patch(
            "app.llm.openrouter_attribution.get_settings",
            return_value=settings,
        ):
            headers = llm._build_headers()

        self.assertEqual(headers["HTTP-Referer"], "https://pivot.fun")
        self.assertEqual(headers["X-OpenRouter-Title"], "Pivot")
        self.assertEqual(
            headers["X-OpenRouter-Categories"],
            "programming-app,cloud-agent",
        )


if __name__ == "__main__":
    unittest.main()
