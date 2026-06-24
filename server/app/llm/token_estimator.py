"""Lightweight token estimation utilities for high-frequency streaming metrics."""

import json
from typing import Any


def _is_cjk(code_point: int) -> bool:
    """Whether a Unicode code point belongs to common CJK ranges."""
    return (
        0x4E00 <= code_point <= 0x9FFF  # CJK Unified Ideographs
        or 0x3400 <= code_point <= 0x4DBF  # CJK Unified Ideographs Extension A
        or 0x3040 <= code_point <= 0x30FF  # Hiragana + Katakana
        or 0xAC00 <= code_point <= 0xD7AF  # Hangul Syllables
    )


def estimate_text_tokens(text: str) -> float:
    """Estimate token count from raw text.

    Why this exists:
    - Streaming providers often do not return usage for every chunk.
    - We only need a stable rough estimate for real-time speed feedback.
    - This function is called frequently, so it avoids heavy tokenizers.

    Returns a float so that small streaming fragments (e.g. a single char)
    accumulate to a non-zero total rather than each rounding down to 0.
    Callers that need an int should round the accumulated sum.

    Args:
        text: Raw text fragment.

    Returns:
        Estimated token count (non-negative float).
    """
    if not text:
        return 0.0

    ascii_visible_chars = 0
    cjk_chars = 0
    other_unicode_chars = 0
    whitespace_chars = 0

    for char in text:
        if char.isspace():
            whitespace_chars += 1
            continue

        code_point = ord(char)
        if _is_cjk(code_point):
            cjk_chars += 1
        elif code_point < 128:
            ascii_visible_chars += 1
        else:
            other_unicode_chars += 1

    estimated = (
        (ascii_visible_chars / 3.8)
        + (cjk_chars * 1.25)
        + (other_unicode_chars * 0.9)
        + (whitespace_chars * 0.05)
    )
    return max(estimated, 0.0)


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate prompt tokens from OpenAI-style chat messages.

    Counts ``role``, ``content`` (string or block list), plus the structured
    fields providers send alongside a message but the previous heuristic
    ignored: ``tool_calls`` (assistant), ``tool_results`` / ``tool_call_id``
    (tool-role messages), and ``reasoning_content`` (assistant reasoning).
    Those fields are real prompt occupants, so omitting them left the
    context-usage estimate systematically low.

    Args:
        messages: Chat messages containing ``role`` and ``content``.

    Returns:
        Estimated total prompt tokens.
    """
    total = 0

    for message in messages:
        role = message.get("role", "")
        content = message.get("content", "")

        if isinstance(role, str):
            total += estimate_text_tokens(role)

        if isinstance(content, str):
            total += estimate_text_tokens(content)
        elif isinstance(content, list):
            # Some providers accept block-based content arrays.
            for block in content:
                if not isinstance(block, dict):
                    continue
                block_text = block.get("text")
                if isinstance(block_text, str):
                    total += estimate_text_tokens(block_text)

        # Structured message occupants: assistant tool_calls, tool-role
        # tool_results / tool_call_id, and assistant reasoning_content. These
        # are billed by the provider but were previously invisible to the
        # estimate. Serialize to JSON and reuse the text heuristic.
        for field in ("tool_calls", "tool_results", "tool_call_id", "reasoning_content"):
            value = message.get(field)
            if value is None:
                continue
            if isinstance(value, str):
                total += estimate_text_tokens(value)
            else:
                total += estimate_text_tokens(json.dumps(value, ensure_ascii=False))

        # Add a tiny fixed overhead per message for role/format wrappers.
        total += 3

    return int(round(total))


def estimate_tools_tokens(tools: list[dict[str, Any]]) -> int:
    """Estimate tokens consumed by native tool/function definitions.

    Tools are passed to the provider via the ``tools=[...]`` parameter,
    separate from the messages list, but they still occupy prompt context.
    Serialize the full definition list (name, description, JSON-Schema
    parameters) and reuse the text heuristic.

    Args:
        tools: Tool definitions in OpenAI ``tools`` format.

    Returns:
        Estimated tokens occupied by the tool definitions.
    """
    if not tools:
        return 0
    return int(round(estimate_text_tokens(json.dumps(tools, ensure_ascii=False))))
