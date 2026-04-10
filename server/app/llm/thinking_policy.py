"""Thinking policy registry and runtime override helpers for LLM protocols."""

from collections.abc import Sequence
from typing import Any, Literal

DEFAULT_THINKING_POLICY = "auto"
DEFAULT_CLAUDE_EXTENDED_BUDGET_TOKENS = 10000
DEFAULT_CLAUDE_ADAPTIVE_EFFORT = "high"
DEFAULT_OPENAI_RESPONSE_REASONING_EFFORT = "medium"

ThinkingMode = Literal["auto", "fast", "thinking"]

PROTOCOL_THINKING_POLICIES: dict[str, tuple[str, ...]] = {
    "openai_completion_llm": (
        "auto",
        "qwen-enable-thinking",
        "qwen-disable-thinking",
        "doubao-completion-thinking-enabled",
        "doubao-completion-thinking-disabled",
        "glm-completion-thinking-enabled",
        "glm-completion-thinking-disabled",
        "mimo-completion-thinking-enabled",
        "mimo-completion-thinking-disabled",
        "kimi-completion-thinking-enabled",
        "kimi-completion-thinking-disabled",
    ),
    "openai_response_llm": (
        "auto",
        "doubao-response-thinking-enabled",
        "doubao-response-thinking-disabled",
        "openai-response-reasoning-effort",
    ),
    "anthropic_compatible": (
        "auto",
        "claude-thinking-enabled",
        "claude-thinking-adaptive",
        "mimo-anthropic-thinking-enabled",
        "mimo-anthropic-thinking-disabled",
    ),
}

DISABLED_THINKING_POLICIES = {
    "qwen-disable-thinking",
    "doubao-completion-thinking-disabled",
    "glm-completion-thinking-disabled",
    "mimo-completion-thinking-disabled",
    "kimi-completion-thinking-disabled",
    "doubao-response-thinking-disabled",
    "mimo-anthropic-thinking-disabled",
}

LEGACY_THINKING_POLICY_ALIASES = {
    # MiniMax's Anthropic-compatible endpoint currently ignores the ``thinking``
    # field, so stored MiniMax thinking overrides are downgraded to ``auto``.
    "minimax-anthropic-thinking-enabled": DEFAULT_THINKING_POLICY,
    "minimax-anthropic-thinking-disabled": DEFAULT_THINKING_POLICY,
}

CLAUDE_ADAPTIVE_EFFORTS = {"low", "medium", "high", "max"}
OPENAI_RESPONSE_REASONING_EFFORTS = {"none", "low", "medium", "high", "xhigh"}


def get_thinking_policies_for_protocol(protocol: str) -> Sequence[str]:
    """Return supported thinking policies for a protocol.

    Args:
        protocol: LLM protocol name.

    Returns:
        Tuple-like sequence of thinking policy names for this protocol.
    """
    return PROTOCOL_THINKING_POLICIES.get(protocol, (DEFAULT_THINKING_POLICY,))


def validate_thinking_policy(
    protocol: str,
    thinking_policy: str,
    thinking_effort: str | None = None,
    thinking_budget_tokens: int | None = None,
) -> tuple[str, str | None, int | None]:
    """Validate and normalize thinking configuration for one protocol.

    Args:
        protocol: LLM protocol name.
        thinking_policy: Requested thinking policy.
        thinking_effort: Optional effort tier for policies that require one.
        thinking_budget_tokens: Optional token budget for extended thinking.

    Returns:
        Normalized tuple of ``(thinking_policy, thinking_effort, thinking_budget_tokens)``.

    Raises:
        ValueError: If the policy or companion fields are invalid.
    """
    normalized_policy = (thinking_policy or DEFAULT_THINKING_POLICY).strip()
    if not normalized_policy:
        normalized_policy = DEFAULT_THINKING_POLICY
    normalized_policy = LEGACY_THINKING_POLICY_ALIASES.get(
        normalized_policy,
        normalized_policy,
    )

    allowed_policies = get_thinking_policies_for_protocol(protocol)
    if normalized_policy not in allowed_policies:
        raise ValueError(
            f"Unsupported thinking_policy '{normalized_policy}' for protocol "
            f"'{protocol}'. Allowed: {', '.join(allowed_policies)}"
        )

    normalized_effort = (thinking_effort or "").strip().lower() or None
    normalized_budget = thinking_budget_tokens

    if normalized_policy == "claude-thinking-enabled":
        if normalized_budget is None:
            normalized_budget = DEFAULT_CLAUDE_EXTENDED_BUDGET_TOKENS
        if normalized_budget <= 0:
            raise ValueError("thinking_budget_tokens must be greater than 0")
        return normalized_policy, None, normalized_budget

    if normalized_policy == "claude-thinking-adaptive":
        if normalized_effort is None:
            normalized_effort = DEFAULT_CLAUDE_ADAPTIVE_EFFORT
        if normalized_effort not in CLAUDE_ADAPTIVE_EFFORTS:
            raise ValueError(
                "thinking_effort must be one of "
                f"{', '.join(sorted(CLAUDE_ADAPTIVE_EFFORTS))}"
            )
        return normalized_policy, normalized_effort, None

    if normalized_policy == "openai-response-reasoning-effort":
        if normalized_effort is None:
            normalized_effort = DEFAULT_OPENAI_RESPONSE_REASONING_EFFORT
        if normalized_effort not in OPENAI_RESPONSE_REASONING_EFFORTS:
            raise ValueError(
                "thinking_effort must be one of "
                f"{', '.join(sorted(OPENAI_RESPONSE_REASONING_EFFORTS))}"
            )
        return normalized_policy, normalized_effort, None

    return normalized_policy, None, None


def policy_supports_thinking_mode(
    thinking_policy: str,
    thinking_effort: str | None = None,
) -> bool:
    """Whether a policy can expose a user-facing Thinking mode toggle.

    Args:
        thinking_policy: Stored thinking policy.
        thinking_effort: Optional effort tier for effort-based policies.

    Returns:
        ``True`` when the policy represents a non-fast tier.
    """
    if thinking_policy == DEFAULT_THINKING_POLICY:
        return False
    if thinking_policy in DISABLED_THINKING_POLICIES:
        return False
    return not (
        thinking_policy == "openai-response-reasoning-effort"
        and (thinking_effort or "").strip().lower() == "none"
    )


def get_default_thinking_mode(
    thinking_policy: str,
    thinking_effort: str | None = None,
) -> ThinkingMode:
    """Return the safest default runtime mode for one stored policy.

    Args:
        thinking_policy: Stored thinking policy.
        thinking_effort: Optional effort tier.

    Returns:
        ``auto`` when a thinking tier exists, otherwise ``fast``.
    """
    if policy_supports_thinking_mode(thinking_policy, thinking_effort):
        return "auto"
    return "fast"


def resolve_runtime_thinking_mode(
    *,
    thinking_policy: str,
    thinking_effort: str | None = None,
    thinking_mode: ThinkingMode | None = None,
    iteration_index: int | None = None,
    next_turn_thinking: bool | None = None,
    previous_iteration_failed: bool = False,
) -> Literal["fast", "thinking"]:
    """Resolve the effective runtime mode for one recursion.

    Args:
        thinking_policy: Stored thinking policy.
        thinking_effort: Optional effort tier.
        thinking_mode: User-selected runtime mode.
        iteration_index: Zero-based iteration index of the current recursion.
        next_turn_thinking: Agent-authored Auto-mode hint persisted from the
            previous recursion for the current recursion to honor.
        previous_iteration_failed: Whether the immediately preceding recursion
            failed and should unlock deeper reasoning for recovery.

    Returns:
        The concrete runtime mode to apply for this recursion.
    """
    if not policy_supports_thinking_mode(thinking_policy, thinking_effort):
        return "fast"

    effective_mode = thinking_mode or get_default_thinking_mode(
        thinking_policy,
        thinking_effort,
    )
    if effective_mode == "thinking":
        return "thinking"
    if effective_mode == "fast":
        return "fast"

    if previous_iteration_failed:
        return "thinking"
    if next_turn_thinking is True:
        return "thinking"
    return "fast"


def build_runtime_thinking_kwargs(
    *,
    protocol: str,
    thinking_policy: str,
    thinking_effort: str | None = None,
    thinking_budget_tokens: int | None = None,
    thinking_mode: ThinkingMode | None = None,
    iteration_index: int | None = None,
    next_turn_thinking: bool | None = None,
    previous_iteration_failed: bool = False,
) -> dict[str, Any]:
    """Translate stored thinking config plus runtime mode into request kwargs.

    Args:
        protocol: LLM protocol name.
        thinking_policy: Stored thinking policy.
        thinking_effort: Optional effort tier.
        thinking_budget_tokens: Optional budget for extended thinking.
        thinking_mode: User-selected runtime mode.
        iteration_index: Zero-based iteration index of the current recursion.
        next_turn_thinking: Agent-authored Auto-mode hint from the immediately
            preceding recursion, if available.
        previous_iteration_failed: Whether the immediately preceding recursion
            failed and should enable recovery-oriented thinking in Auto mode.

    Returns:
        Provider request kwargs to merge into one LLM call.
    """
    (
        normalized_policy,
        normalized_effort,
        normalized_budget,
    ) = validate_thinking_policy(
        protocol=protocol,
        thinking_policy=thinking_policy,
        thinking_effort=thinking_effort,
        thinking_budget_tokens=thinking_budget_tokens,
    )
    if normalized_policy == DEFAULT_THINKING_POLICY:
        return {}

    effective_mode = resolve_runtime_thinking_mode(
        thinking_policy=normalized_policy,
        thinking_effort=normalized_effort,
        thinking_mode=thinking_mode,
        iteration_index=iteration_index,
        next_turn_thinking=next_turn_thinking,
        previous_iteration_failed=previous_iteration_failed,
    )
    if effective_mode == "thinking":
        return _build_thinking_kwargs(
            normalized_policy,
            normalized_effort,
            normalized_budget,
        )
    return _build_fast_kwargs(normalized_policy)


def _build_thinking_kwargs(
    thinking_policy: str,
    thinking_effort: str | None,
    thinking_budget_tokens: int | None,
) -> dict[str, Any]:
    """Build request kwargs for the configured thinking tier."""
    if thinking_policy == "qwen-enable-thinking":
        return {"enable_thinking": True}
    if thinking_policy in {
        "doubao-completion-thinking-enabled",
        "glm-completion-thinking-enabled",
        "mimo-completion-thinking-enabled",
        "kimi-completion-thinking-enabled",
        "doubao-response-thinking-enabled",
        "mimo-anthropic-thinking-enabled",
    }:
        return {"thinking": {"type": "enabled"}}
    if thinking_policy == "openai-response-reasoning-effort":
        return {"reasoning": {"effort": thinking_effort}}
    if thinking_policy == "claude-thinking-enabled":
        return {
            "thinking": {
                "type": "enabled",
                "budget_tokens": thinking_budget_tokens,
            }
        }
    if thinking_policy == "claude-thinking-adaptive":
        return {
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": thinking_effort},
        }
    return _build_fast_kwargs(thinking_policy)


def _build_fast_kwargs(thinking_policy: str) -> dict[str, Any]:
    """Build request kwargs for fast mode."""
    if thinking_policy in {"qwen-enable-thinking", "qwen-disable-thinking"}:
        return {"enable_thinking": False}
    if thinking_policy == "openai-response-reasoning-effort":
        return {"reasoning": {"effort": "none"}}
    if thinking_policy in {
        "doubao-completion-thinking-enabled",
        "doubao-completion-thinking-disabled",
        "glm-completion-thinking-enabled",
        "glm-completion-thinking-disabled",
        "mimo-completion-thinking-enabled",
        "mimo-completion-thinking-disabled",
        "kimi-completion-thinking-enabled",
        "kimi-completion-thinking-disabled",
        "doubao-response-thinking-enabled",
        "doubao-response-thinking-disabled",
        "mimo-anthropic-thinking-enabled",
        "mimo-anthropic-thinking-disabled",
    }:
        return {"thinking": {"type": "disabled"}}
    return {}
