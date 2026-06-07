"""Parse and validate ReAct assistant responses.

The parser validates JSON envelope output for all action types including
CALL_TOOL (which accompanies native tool_calls).  The native ``tool_calls``
field is handled separately by the engine, but the JSON envelope that
rides alongside it is parsed here for its ``message`` and
``step_status_update`` fields.
"""

import json
from typing import Any

from .types import ParsedAction, ParsedReactDecision, StepStatusUpdate

ALLOWED_ACTION_TYPES = {"CALL_TOOL", "PLAN", "REFLECT", "CLARIFY", "ANSWER"}
PARSE_RETRY_LIMIT = 1
PARSE_RETRY_INSTRUCTION = (
    "Your previous response could not be parsed.\n"
    "Output the same decision again using the required format only.\n"
    "Rules:\n"
    "1) The first block must be a valid JSON object.\n"
    "2) step_status_update is only allowed at action.step_status_update and must be a list.\n"
    "3) Do not include markdown fences or any extra commentary."
)
ALLOWED_STEP_STATUSES = {"pending", "running", "done", "error"}


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
    raw_payload = _normalize_step_status_update_location(raw_payload)
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


def _normalize_step_status_update_location(payload: dict[str, Any]) -> dict[str, Any]:
    """Move legacy step-status locations into ``action.step_status_update``.

    The prompt contract asks the model to emit ``action.step_status_update``, but
    models sometimes drift to the old top-level or ``action.output`` locations.
    Treat that as recoverable structure drift instead of failing the recursion.
    """
    normalized_payload = dict(payload)
    action_raw = normalized_payload.get("action")
    if not isinstance(action_raw, dict):
        return normalized_payload

    normalized_action = dict(action_raw)
    action_output = normalized_action.get("output")
    normalized_output = dict(action_output) if isinstance(action_output, dict) else None

    legacy_step_status_update = normalized_payload.pop("step_status_update", None)
    output_step_status_update = None
    if normalized_output is not None:
        output_step_status_update = normalized_output.pop("step_status_update", None)
        normalized_action["output"] = normalized_output

    if "step_status_update" not in normalized_action:
        if legacy_step_status_update is not None:
            normalized_action["step_status_update"] = legacy_step_status_update
        elif output_step_status_update is not None:
            normalized_action["step_status_update"] = output_step_status_update

    normalized_payload["action"] = normalized_action
    return normalized_payload


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

    step_id = _parse_step_id(action_raw.get("step_id"))
    step_status_update = _parse_step_status_updates(
        action_raw.get("step_status_update")
    )

    return ParsedAction(
        action_type=normalized_action_type,
        output=dict(action_output),
        step_id=step_id,
        step_status_update=step_status_update,
    )


def _expect_optional_bool(value: Any, field_name: str) -> bool | None:
    """Return an optional boolean field after strict validation."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raise ValueError(f"{field_name} must be a boolean when provided.")


def _parse_step_id(raw_value: Any) -> str | None:
    """Normalize an optional action step identifier."""
    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise ValueError("action.step_id must be a string when provided.")

    normalized = raw_value.strip()
    return normalized or None


def _parse_step_status_updates(raw_value: Any) -> list[StepStatusUpdate]:
    """Validate explicit plan-step status updates."""
    if raw_value is None:
        return []
    if not isinstance(raw_value, list):
        raise ValueError("action.step_status_update must be a list.")

    updates: list[StepStatusUpdate] = []
    for index, item in enumerate(raw_value):
        if not isinstance(item, dict):
            raise ValueError(f"action.step_status_update[{index}] must be an object.")

        step_id = item.get("step_id")
        if not isinstance(step_id, str) or not step_id.strip():
            raise ValueError(
                f"action.step_status_update[{index}].step_id must be a non-empty string."
            )

        status = item.get("status")
        if (
            not isinstance(status, str)
            or status.strip().lower() not in ALLOWED_STEP_STATUSES
        ):
            raise ValueError(
                f"action.step_status_update[{index}].status must be one of "
                f"{sorted(ALLOWED_STEP_STATUSES)}."
            )

        updates.append(
            StepStatusUpdate(
                step_id=step_id.strip(),
                status=status.strip().lower(),
            )
        )

    return updates


def _expect_optional_string(raw_value: Any, path: str) -> str:
    """Validate an optional string field and normalize absent values to ``""``."""
    if raw_value is None:
        return ""
    if not isinstance(raw_value, str):
        raise ValueError(f"{path} must be a string when provided.")
    return raw_value
