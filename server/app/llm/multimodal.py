"""Helpers for converting neutral multimodal blocks into provider payloads."""

from __future__ import annotations

from typing import Any, TypeGuard


def is_multimodal_content(
    content: Any,
) -> TypeGuard[list[dict[str, Any]]]:
    """Return whether ``content`` is the neutral multimodal block format."""
    if not isinstance(content, list):
        return False

    for block in content:
        if not isinstance(block, dict):
            return False
        block_type = block.get("type")
        if block_type == "text" and isinstance(block.get("text"), str):
            continue
        if (
            block_type == "image"
            and isinstance(block.get("media_type"), str)
            and isinstance(block.get("data"), str)
        ):
            continue
        return False
    return True


def to_openai_completion_content(
    content: str | list[dict[str, Any]],
) -> str | list[dict[str, Any]]:
    """Convert neutral blocks to OpenAI chat-completions content."""
    if isinstance(content, str):
        return content
    if not is_multimodal_content(content):
        return ""

    result: list[dict[str, Any]] = []
    for block in content:
        block_type = block["type"]
        if block_type == "text":
            result.append({"type": "text", "text": block["text"]})
            continue

        result.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": (f"data:{block['media_type']};base64,{block['data']}")
                },
            }
        )
    return result


def to_openai_response_content(
    content: str | list[dict[str, Any]],
    role: str,
) -> str | list[dict[str, Any]]:
    """Convert neutral blocks to OpenAI Responses API content blocks."""
    if isinstance(content, str):
        return content
    if not is_multimodal_content(content):
        return ""

    result: list[dict[str, Any]] = []
    for block in content:
        block_type = block["type"]
        if block_type == "text":
            result.append(
                {
                    "type": "input_text" if role == "user" else "output_text",
                    "text": block["text"],
                }
            )
            continue

        result.append(
            {
                "type": "input_image",
                "image_url": f"data:{block['media_type']};base64,{block['data']}",
            }
        )
    return result


def to_anthropic_content(
    content: str | list[dict[str, Any]],
) -> str | list[dict[str, Any]]:
    """Convert neutral blocks to Anthropic messages content."""
    if isinstance(content, str):
        return content
    if not is_multimodal_content(content):
        return ""

    result: list[dict[str, Any]] = []
    for block in content:
        block_type = block["type"]
        if block_type == "text":
            result.append({"type": "text", "text": block["text"]})
            continue

        result.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": block["media_type"],
                    "data": block["data"],
                },
            }
        )
    return result
