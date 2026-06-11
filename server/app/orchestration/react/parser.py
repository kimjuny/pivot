"""Parse and validate ReAct assistant responses.

The parser validates the JSON envelope output for the three remaining
action types: CALL_TOOL, CLARIFY, and ANSWER.
"""

import json
from typing import Any

from .types import ParsedAction, ParsedReactDecision

ALLOWED_ACTION_TYPES = {"CALL_TOOL", "CLARIFY", "ANSWER"}
PARSE_RETRY_LIMIT = 1
PARSE_RETRY_INSTRUCTION = (
    "Your previous response could not be parsed.\n"
    "Output the same decision again using the required format only.\n"
    "Rules:\n"
    "1) The first block must be a valid JSON object.\n"
    "2) Do not include markdown fences or any extra commentary."
)


def safe_load_json(json_str: str) -> dict[str, Any]:
    """Parse a JSON object while tolerating accidental markdown fences.

    Args:
        json_str: Raw JSON string produced by the assistant.

    Returns:
        The parsed JSON object.

    Raises:
        ValueError: If the content is not a valid JSON object.
    """
    normalized = json_str.strip()
    if normalized.startswith("```json"):
        normalized = normalized[7:]
    elif normalized.startswith("```"):
        normalized = normalized[3:]

    if normalized.endswith("```"):
        normalized = normalized[:-3]

    normalized = normalized.strip()

    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Failed to parse JSON {exc.msg} at position {exc.pos}: {normalized}"
        ) from exc

    if not isinstance(parsed, dict):
        raise ValueError("Assistant response must be a top-level JSON object.")
    return parsed


def parse_react_output(content: str) -> ParsedReactDecision:
    """Parse and validate one text-only assistant decision payload.

    Args:
        content: Raw assistant response text (JSON envelope only).

    Returns:
        A typed, validated decision object.

    Raises:
        ValueError: If the response violates the ReAct protocol contract.
    """
    raw_payload = safe_load_json(content)
    action = _parse_action(raw_payload)

    message = _expect_optional_string(raw_payload.get("message"), "message")
    thinking_next_turn = _expect_optional_bool(
        raw_payload.get("thinking_next_turn"),
        "thinking_next_turn",
    )

    resolved_payload = dict(raw_payload)
    resolved_payload["action"] = action.to_dict()
    return ParsedReactDecision(
        message=message,
        thinking_next_turn=thinking_next_turn,
        action=action,
        raw_payload=resolved_payload,
    )


def _parse_action(payload: dict[str, Any]) -> ParsedAction:
    """Validate and normalize the action section.

    Args:
        payload: Parsed top-level assistant payload.

    Returns:
        A typed action object.

    Raises:
        ValueError: If the action section is missing or invalid.
    """
    action_raw = payload.get("action")
    if not isinstance(action_raw, dict):
        raise ValueError("Missing or invalid action object.")

    action_type = action_raw.get("action_type")
    if not isinstance(action_type, str) or not action_type.strip():
        raise ValueError("Missing action.action_type.")
    normalized_action_type = action_type.strip()
    if normalized_action_type not in ALLOWED_ACTION_TYPES:
        raise ValueError(
            "Unsupported action_type: "
            f"{normalized_action_type}. Allowed values: {sorted(ALLOWED_ACTION_TYPES)}"
        )

    action_output = action_raw.get("output")
    if not isinstance(action_output, dict):
        raise ValueError("action.output must be an object.")

    return ParsedAction(
        action_type=normalized_action_type,
        output=dict(action_output),
    )


def _expect_optional_bool(value: Any, field_name: str) -> bool | None:
    """Return an optional boolean field after strict validation."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raise ValueError(f"{field_name} must be a boolean when provided.")


def _expect_optional_string(raw_value: Any, path: str) -> str:
    """Validate an optional string field and normalize absent values to ``""``."""
    if raw_value is None:
        return ""
    if not isinstance(raw_value, str):
        raise ValueError(f"{path} must be a string when provided.")
    return raw_value
