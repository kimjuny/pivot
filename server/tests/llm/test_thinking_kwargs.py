"""Unit tests for build_thinking_kwargs across all four protocols."""

import sys
import unittest
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

build_thinking_kwargs = import_module("app.llm.thinking").build_thinking_kwargs


class ThinkingKwargsTestCase(unittest.TestCase):
    """Verify each protocol emits correct enable/disable wire format."""

    def _llm(self, protocol: str) -> SimpleNamespace:
        return SimpleNamespace(protocol=protocol)

    # --- OpenAI Responses ---
    def test_openai_response_enable_sends_empty_reasoning(self) -> None:
        kwargs = build_thinking_kwargs(
            self._llm("openai_response_llm"), enabled=True
        )
        self.assertEqual(kwargs, {"reasoning": {}})

    def test_openai_response_disable_sends_effort_none(self) -> None:
        """Disabling must explicitly send effort=none; omitting is NOT off."""
        kwargs = build_thinking_kwargs(
            self._llm("openai_response_llm"), enabled=False
        )
        self.assertEqual(kwargs, {"reasoning": {"effort": "none"}})

    # --- Anthropic ---
    def test_anthropic_enable_sends_thinking_block(self) -> None:
        kwargs = build_thinking_kwargs(
            self._llm("anthropic_compatible"), enabled=True
        )
        self.assertEqual(kwargs["thinking"]["type"], "enabled")
        self.assertIn("budget_tokens", kwargs["thinking"])

    def test_anthropic_disable_sends_nothing(self) -> None:
        """Anthropic is off by default, so disable = empty dict."""
        kwargs = build_thinking_kwargs(
            self._llm("anthropic_compatible"), enabled=False
        )
        self.assertEqual(kwargs, {})

    # --- Gemini ---
    def test_gemini_enable_requests_thoughts(self) -> None:
        kwargs = build_thinking_kwargs(
            self._llm("gemini_compatible"), enabled=True
        )
        self.assertEqual(
            kwargs,
            {"generationConfig": {"thinkingConfig": {"includeThoughts": True}}},
        )

    def test_gemini_disable_sends_zero_budget(self) -> None:
        """Disabling sends thinkingBudget=0 (Flash honors it; Pro ignores)."""
        kwargs = build_thinking_kwargs(
            self._llm("gemini_compatible"), enabled=False
        )
        self.assertEqual(
            kwargs,
            {"generationConfig": {"thinkingConfig": {"thinkingBudget": 0}}},
        )

    # --- OpenAI Completion (DeepSeek/Qwen/GLM) ---
    def test_completion_enable_sends_thinking_enabled(self) -> None:
        kwargs = build_thinking_kwargs(
            self._llm("openai_completion_llm"), enabled=True
        )
        self.assertEqual(kwargs, {"thinking": {"type": "enabled"}})

    def test_completion_disable_sends_thinking_disabled(self) -> None:
        kwargs = build_thinking_kwargs(
            self._llm("openai_completion_llm"), enabled=False
        )
        self.assertEqual(kwargs, {"thinking": {"type": "disabled"}})

    # --- Unknown protocol ---
    def test_unknown_protocol_returns_empty(self) -> None:
        kwargs = build_thinking_kwargs(self._llm("unknown_protocol"), enabled=True)
        self.assertEqual(kwargs, {})


if __name__ == "__main__":
    unittest.main()
