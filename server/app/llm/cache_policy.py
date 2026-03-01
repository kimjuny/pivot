"""Cache policy registry and validation utilities for LLM protocols."""

from collections.abc import Sequence

DEFAULT_CACHE_POLICY = "none"

PROTOCOL_CACHE_POLICIES: dict[str, tuple[str, ...]] = {
    "openai_completion_llm": (
        "none",
        "qwen-completion-block-cache",
        "kimi-completion-prompt-cache-key",
    ),
    "openai_response_llm": (
        "none",
        "openai-response-prompt-cache-key",
        "doubao-response-previous-id",
    ),
    "anthropic_compatible": (
        "none",
        "anthropic-auto-cache",
        "anthropic-block-cache",
    ),
}


def get_cache_policies_for_protocol(protocol: str) -> Sequence[str]:
    """Return supported cache policies for a protocol.

    Args:
        protocol: LLM protocol name.

    Returns:
        Tuple-like sequence of policy names for this protocol.
    """
    return PROTOCOL_CACHE_POLICIES.get(protocol, (DEFAULT_CACHE_POLICY,))


def validate_cache_policy(protocol: str, cache_policy: str) -> str:
    """Validate and normalize cache policy for a protocol.

    Args:
        protocol: LLM protocol name.
        cache_policy: Requested cache policy.

    Returns:
        The normalized cache policy string.

    Raises:
        ValueError: If the cache policy is not supported by the protocol.
    """
    normalized_policy = (cache_policy or DEFAULT_CACHE_POLICY).strip()
    if not normalized_policy:
        normalized_policy = DEFAULT_CACHE_POLICY

    allowed_policies = get_cache_policies_for_protocol(protocol)
    if normalized_policy not in allowed_policies:
        raise ValueError(
            f"Unsupported cache_policy '{normalized_policy}' for protocol "
            f"'{protocol}'. Allowed: {', '.join(allowed_policies)}"
        )
    return normalized_policy
