"""Thinking policy translation tests for protocol-specific request payloads."""

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
thinking_policy = import_module("app.llm.thinking_policy")


class ThinkingPolicyTestCase(unittest.TestCase):
    """Verify thinking configuration maps cleanly onto provider payloads."""

    def test_auto_mode_defaults_to_fast_without_agent_hint(self) -> None:
        """Auto mode should stay fast until the agent explicitly asks for thinking."""
        kwargs = thinking_policy.build_runtime_thinking_kwargs(
            protocol="openai_response_llm",
            thinking_policy="openai-response-reasoning-effort",
            thinking_effort="high",
            thinking_mode="auto",
            iteration_index=0,
            next_turn_thinking=None,
            previous_iteration_failed=False,
        )

        self.assertEqual(kwargs, {"reasoning": {"effort": "none"}})

    def test_auto_mode_uses_agent_requested_thinking(self) -> None:
        """Auto mode should honor the prior recursion's explicit deep-think request."""
        kwargs = thinking_policy.build_runtime_thinking_kwargs(
            protocol="openai_response_llm",
            thinking_policy="openai-response-reasoning-effort",
            thinking_effort="high",
            thinking_mode="auto",
            iteration_index=1,
            next_turn_thinking=True,
            previous_iteration_failed=False,
        )

        self.assertEqual(kwargs, {"reasoning": {"effort": "high"}})

    def test_auto_mode_falls_back_to_fast_after_clean_iteration(self) -> None:
        """Auto mode should stay cheap when the prior recursion declined thinking."""
        kwargs = thinking_policy.build_runtime_thinking_kwargs(
            protocol="openai_response_llm",
            thinking_policy="openai-response-reasoning-effort",
            thinking_effort="high",
            thinking_mode="auto",
            iteration_index=1,
            next_turn_thinking=False,
            previous_iteration_failed=False,
        )

        self.assertEqual(kwargs, {"reasoning": {"effort": "none"}})

    def test_auto_mode_reenables_thinking_after_previous_failure(self) -> None:
        """Auto mode should give the agent extra room to recover from failures."""
        kwargs = thinking_policy.build_runtime_thinking_kwargs(
            protocol="openai_response_llm",
            thinking_policy="openai-response-reasoning-effort",
            thinking_effort="high",
            thinking_mode="auto",
            iteration_index=2,
            next_turn_thinking=False,
            previous_iteration_failed=True,
        )

        self.assertEqual(kwargs, {"reasoning": {"effort": "high"}})

    def test_qwen_fast_override_disables_thinking(self) -> None:
        """Fast mode should explicitly disable Qwen thinking."""
        kwargs = thinking_policy.build_runtime_thinking_kwargs(
            protocol="openai_completion_llm",
            thinking_policy="qwen-enable-thinking",
            thinking_mode="fast",
        )
        self.assertEqual(kwargs, {"enable_thinking": False})

    def test_openai_response_thinking_uses_reasoning_effort(self) -> None:
        """Thinking mode should preserve the configured Responses reasoning effort."""
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
        kwargs = thinking_policy.build_runtime_thinking_kwargs(
            protocol="openai_response_llm",
            thinking_policy="openai-response-reasoning-effort",
            thinking_effort="high",
            thinking_mode="thinking",
        )

        with patch(
            "app.llm.openai_response_llm.requests.post", return_value=response
        ) as mocked_post:
            llm.chat([{"role": "user", "content": "hello"}], **kwargs)

        payload = mocked_post.call_args.kwargs["json"]
        self.assertEqual(payload["reasoning"], {"effort": "high"})

    def test_claude_adaptive_thinking_sets_output_effort(self) -> None:
        """Claude adaptive thinking should emit both thinking and output_config."""
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
        kwargs = thinking_policy.build_runtime_thinking_kwargs(
            protocol="anthropic_compatible",
            thinking_policy="claude-thinking-adaptive",
            thinking_effort="medium",
            thinking_mode="thinking",
        )

        with patch("app.llm.anthropic_llm.Anthropic", return_value=mock_client):
            llm = AnthropicLLM(
                endpoint="https://example.com",
                model="claude-test",
                api_key="secret",
            )

        llm.chat([{"role": "user", "content": "hello"}], **kwargs)

        payload = mock_client.messages.create.call_args.kwargs
        self.assertEqual(payload["thinking"], {"type": "adaptive"})
        self.assertEqual(payload["output_config"], {"effort": "medium"})

    def test_legacy_minimax_thinking_policy_downgrades_to_auto(self) -> None:
        """Stored MiniMax Anthropic thinking overrides should no-op safely."""
        policy, effort, budget = thinking_policy.validate_thinking_policy(
            "anthropic_compatible",
            "minimax-anthropic-thinking-enabled",
        )

        self.assertEqual(policy, "auto")
        self.assertIsNone(effort)
        self.assertIsNone(budget)
        self.assertEqual(
            thinking_policy.build_runtime_thinking_kwargs(
                protocol="anthropic_compatible",
                thinking_policy="minimax-anthropic-thinking-enabled",
                thinking_mode="thinking",
            ),
            {},
        )


if __name__ == "__main__":
    unittest.main()
