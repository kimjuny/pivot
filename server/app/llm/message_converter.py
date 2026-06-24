"""Convert internal unified messages to provider-specific API formats.

Internal message format:

    role: "system" | "user" | "assistant"
    content: str | list[dict] | None
    tool_calls: list[dict] | None   — assistant only
        Each: {id: str, name: str, arguments: str}  (arguments is a JSON string)
    tool_results: list[dict] | None  — user only
        Each: {tool_call_id: str, name: str, result: str, is_error: bool}

When ``tool_calls`` / ``tool_results`` are absent the converter produces
output identical to the original per-provider inline conversion logic,
so the migration is a drop-in replacement.
"""

from __future__ import annotations

import json
from typing import Any

from .multimodal import (
    to_anthropic_content,
    to_gemini_content,
    to_openai_completion_content,
    to_openai_response_content,
)

# ---------------------------------------------------------------------------
# OpenAI Chat Completion  (role=tool for results)
# ---------------------------------------------------------------------------


def to_openai_completion_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert internal messages to OpenAI Chat Completion format.

    Tool calls stay on the assistant message; tool results become
    separate ``role="tool"`` messages.
    """
    out: list[dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        tool_calls = msg.get("tool_calls")
        tool_results = msg.get("tool_results")

        if role == "system":
            out.append(
                {"role": "system", "content": to_openai_completion_content(content)}
            )

        elif role == "assistant":
            entry: dict[str, Any] = {
                "role": "assistant",
                "content": to_openai_completion_content(content),
            }
            reasoning = msg.get("reasoning_content")
            if isinstance(reasoning, str) and reasoning:
                # DeepSeek / Qwen / Kimi / GLM and other OpenAI-compatible
                # endpoints accept the assistant's prior reasoning_content on
                # history messages to continue the chain-of-thought.
                entry["reasoning_content"] = reasoning
            if tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": tc["arguments"],
                        },
                    }
                    for tc in tool_calls
                ]
            out.append(entry)

        elif role == "user":
            if tool_results:
                for tr in tool_results:
                    out.append(
                        {
                            "role": "tool",
                            "tool_call_id": tr["tool_call_id"],
                            "content": tr["result"],
                        }
                    )
                # Remaining user text (if any) after tool results
                if content:
                    out.append(
                        {
                            "role": "user",
                            "content": to_openai_completion_content(content),
                        }
                    )
            else:
                out.append(
                    {"role": "user", "content": to_openai_completion_content(content)}
                )

    return out


# ---------------------------------------------------------------------------
# OpenAI Response  (function_call / function_call_output items)
# ---------------------------------------------------------------------------


def to_openai_response_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert internal messages to OpenAI Response API ``input`` format.

    The Response API uses a flat array with mixed item types:
    regular role-based messages, ``function_call``, and
    ``function_call_output`` items.
    """
    out: list[dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        tool_calls = msg.get("tool_calls")
        tool_results = msg.get("tool_results")

        if role == "system":
            if isinstance(content, str) and content:
                out.append({"role": "system", "content": content})

        elif role == "assistant":
            reasoning = msg.get("reasoning_content")
            if isinstance(reasoning, str) and reasoning:
                # Responses API carries chain-of-thought as standalone
                # ``reasoning`` items in the input array, preceding the
                # assistant's visible output and tool calls.
                out.append(
                    {
                        "type": "reasoning",
                        "content": [
                            {"type": "reasoning_text", "text": reasoning}
                        ],
                    }
                )

            converted = to_openai_response_content(content, "assistant")
            if isinstance(converted, str) and converted:
                out.append(
                    {
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": converted}],
                    }
                )
            elif isinstance(converted, list) and converted:
                out.append({"role": "assistant", "content": converted})

            if tool_calls:
                for tc in tool_calls:
                    out.append(
                        {
                            "type": "function_call",
                            "call_id": tc["id"],
                            "name": tc["name"],
                            "arguments": tc["arguments"],
                        }
                    )

        elif role == "user":
            if tool_results:
                for tr in tool_results:
                    out.append(
                        {
                            "type": "function_call_output",
                            "call_id": tr["tool_call_id"],
                            "output": tr["result"],
                        }
                    )

            converted = to_openai_response_content(content, "user")
            if isinstance(converted, str) and converted:
                out.append(
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": converted}],
                    }
                )
            elif isinstance(converted, list) and converted:
                out.append({"role": "user", "content": converted})

    return out


# ---------------------------------------------------------------------------
# Anthropic  (tool_use / tool_result content blocks)
# ---------------------------------------------------------------------------


def to_anthropic_messages(
    messages: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    """Convert internal messages to Anthropic Messages API format.

    Returns ``(system_message, formatted_messages)``.

    Anthropic requires ``tool_result`` content blocks to *precede* text
    blocks within the same user message.
    """
    system_message = ""
    formatted: list[dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        tool_calls = msg.get("tool_calls")
        tool_results = msg.get("tool_results")

        if role == "system":
            if isinstance(content, str):
                system_message = content

        elif role == "assistant":
            reasoning = msg.get("reasoning_content")
            has_reasoning = isinstance(reasoning, str) and bool(reasoning)
            if tool_calls or has_reasoning:
                # Must use block format when tool_calls or thinking present.
                # Anthropic requires the thinking block to precede text and
                # tool_use blocks so the chain-of-thought continues correctly.
                blocks: list[dict[str, Any]] = []
                if has_reasoning:
                    blocks.append({"type": "thinking", "thinking": reasoning})
                converted = to_anthropic_content(content)
                if isinstance(converted, str) and converted:
                    blocks.append({"type": "text", "text": converted})
                elif isinstance(converted, list):
                    blocks.extend(converted)
                for tc in tool_calls or []:
                    inp = json.loads(tc["arguments"]) if tc.get("arguments") else {}
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc["id"],
                            "name": tc["name"],
                            "input": inp,
                        }
                    )
                formatted.append({"role": "assistant", "content": blocks})
            else:
                formatted.append(
                    {"role": "assistant", "content": to_anthropic_content(content)}
                )

        elif role == "user":
            if tool_results:
                blocks: list[dict[str, Any]] = []
                # tool_result blocks MUST come before text blocks
                for tr in tool_results:
                    result_block: dict[str, Any] = {
                        "type": "tool_result",
                        "tool_use_id": tr["tool_call_id"],
                        "content": tr["result"],
                    }
                    if tr.get("is_error"):
                        result_block["is_error"] = True
                    blocks.append(result_block)
                converted = to_anthropic_content(content)
                if isinstance(converted, str) and converted:
                    blocks.append({"type": "text", "text": converted})
                elif isinstance(converted, list):
                    blocks.extend(converted)
                formatted.append({"role": "user", "content": blocks})
            else:
                formatted.append(
                    {"role": "user", "content": to_anthropic_content(content)}
                )

    return system_message, formatted


# ---------------------------------------------------------------------------
# Gemini  (functionCall / functionResponse parts)
# ---------------------------------------------------------------------------


def to_gemini_messages(
    messages: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Convert internal messages to Gemini ``contents`` format.

    Returns ``(system_instruction, contents)``.

    Gemini uses ``model`` role (not ``assistant``) and
    ``functionCall`` / ``functionResponse`` parts for tool data.
    ``args`` is a parsed dict (not a JSON string).
    """
    system_parts: list[dict[str, Any]] = []
    contents: list[dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        tool_calls = msg.get("tool_calls")
        tool_results = msg.get("tool_results")

        if role == "system":
            if isinstance(content, str) and content:
                system_parts.append({"text": content})

        elif role in ("user", "assistant"):
            gemini_role = "model" if role == "assistant" else "user"
            converted = to_gemini_content(content)

            parts: list[dict[str, Any]] = []
            if role == "assistant":
                reasoning = msg.get("reasoning_content")
                if isinstance(reasoning, str) and reasoning:
                    # Gemini surfaces prior reasoning as a ``thought`` part so
                    # the model continues its chain-of-thought across turns.
                    parts.append({"text": reasoning, "thought": True})

            if isinstance(converted, str):
                parts.append({"text": converted})
            elif isinstance(converted, list):
                parts.extend(converted)

            if tool_calls:
                for tc in tool_calls:
                    args = json.loads(tc["arguments"]) if tc.get("arguments") else {}
                    parts.append({"functionCall": {"name": tc["name"], "args": args}})

            if tool_results:
                for tr in tool_results:
                    parts.append(
                        {
                            "functionResponse": {
                                "name": tr["name"],
                                "response": {"content": tr["result"]},
                            }
                        }
                    )

            if parts:
                contents.append({"role": gemini_role, "parts": parts})

    system_instruction = {"parts": system_parts} if system_parts else None
    return system_instruction, contents
