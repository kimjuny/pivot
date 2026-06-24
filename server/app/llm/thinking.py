"""Translate the per-task thinking flag into provider request kwargs.

The runtime exposes a single binary ``thinking_enabled`` toggle per task.
This module is the only place that knows how to turn that flag into the
provider-specific wire format — both the *enable* and the *disable*
direction, because for some providers (OpenAI Responses, Gemini) omitting
the parameter is NOT the same as disabling thinking.

Effort tiers (max / high / medium / low) are intentionally NOT exposed here —
they will be added later as a separate per-LLM configuration surface. The
only effort-like value used here is ``none`` on OpenAI Responses, which is
the protocol-defined way to *turn reasoning off* (not a strength level).
"""

from typing import Any

# Anthropic's Messages API requires ``budget_tokens`` when thinking is enabled
# (there is no provider default). We pin a conservative default here; it will
# become configurable once effort tiers land.
DEFAULT_ANTHROPIC_BUDGET_TOKENS = 10000


def build_thinking_kwargs(llm: Any, *, enabled: bool) -> dict[str, Any]:
    """Return provider-specific kwargs that set thinking on or off.

    Args:
        llm: The LLM instance. Its ``protocol`` attribute (set by each
            provider class in ``__init__``) decides the wire format.
        enabled: ``True`` to turn thinking/reasoning on, ``False`` to turn
            it off. For protocols whose *off* state is "send nothing"
            (Anthropic) the disable branch returns ``{}``.

    Returns:
        Provider request kwargs to merge into the LLM call. Empty dict means
        the provider's own default applies (i.e. nothing needs to be sent).
    """
    protocol = getattr(llm, "protocol", None)

    if protocol == "openai_response_llm":
        # OpenAI Responses: omitting ``reasoning`` lets the model follow its
        # own default (which for o-series / GPT-5 IS to reason), so the
        # disable direction must explicitly send effort=none.
        if enabled:
            return {"reasoning": {}}
        return {"reasoning": {"effort": "none"}}

    if protocol == "anthropic_compatible":
        # Anthropic: thinking is OFF by default, so disabling = send nothing.
        if not enabled:
            return {}
        return {
            "thinking": {
                "type": "enabled",
                "budget_tokens": DEFAULT_ANTHROPIC_BUDGET_TOKENS,
            }
        }

    if protocol == "gemini_compatible":
        # Gemini 2.5 Flash honors thinkingBudget=0 (full disable). Gemini 2.5
        # Pro ignores it and keeps thinking — that is a provider limitation we
        # cannot work around. includeThoughts surfaces the thoughts back so we
        # can replay them; it does not by itself toggle thinking.
        if enabled:
            return {
                "generationConfig": {
                    "thinkingConfig": {"includeThoughts": True}
                }
            }
        return {
            "generationConfig": {"thinkingConfig": {"thinkingBudget": 0}}
        }

    if protocol == "openai_completion_llm":
        # DeepSeek / Qwen / GLM / Kimi etc. toggle thinking via a top-level
        # ``thinking`` object with type enabled/disabled.
        thinking_type = "enabled" if enabled else "disabled"
        return {"thinking": {"type": thinking_type}}

    # Unknown protocol: let the provider's own default apply in both
    # directions — we have no wire format to send.
    return {}
