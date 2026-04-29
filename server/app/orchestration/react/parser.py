"""Parse and validate strict ReAct assistant responses."""

import json
import re
from typing import Any

from .types import ParsedAction, ParsedReactDecision, StepStatusUpdate, ToolCallRequest

ALLOWED_ACTION_TYPES = {"CALL_TOOL", "RE_PLAN", "REFLECT", "CLARIFY", "ANSWER"}
PARSE_RETRY_LIMIT = 1
PARSE_RETRY_INSTRUCTION = (
    "Your previous response could not be parsed.\n"
    "Output the same decision again using the required format only.\n"
    "Rules:\n"
    "1) The first block must be a valid JSON object.\n"
    '2) For CALL_TOOL, every argument value must be {"$payload_ref":"<name>"}.\n'
    "3) Append payload blocks after the JSON when action_type is CALL_TOOL.\n"
    "4) step_status_update is only allowed at action.step_status_update and must be a list.\n"
    "5) Do not include markdown fences or any extra commentary."
)
PAYLOAD_SENTINEL_SUFFIX = "6F2D9C1A"
PAYLOAD_NAME_PATTERN = r"[A-Za-z_][A-Za-z0-9_]{0,63}"
PAYLOAD_BEGIN_RE = re.compile(
    rf"(?m)^<<<PIVOT_PAYLOAD:({PAYLOAD_NAME_PATTERN}):BEGIN_{PAYLOAD_SENTINEL_SUFFIX}>>>$"
)
PAYLOAD_REF_KEY = "$payload_ref"
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


def split_json_and_payload_sections(content: str) -> tuple[str, str | None]:
    """Split the assistant response into JSON and payload sections.

    Args:
        content: Raw assistant response text.

    Returns:
        A tuple of ``(json_section, payload_section)`` where payload_section may be
        ``None`` when no payload blocks are present.

    Raises:
        ValueError: If payload blocks appear without a preceding JSON section.
    """
    normalized = content.strip()
    begin_match = PAYLOAD_BEGIN_RE.search(normalized)
    if begin_match is None:
        return normalized, None

    json_section = normalized[: begin_match.start()].strip()
    json_lines = json_section.splitlines()
    if json_lines and json_lines[-1].strip().lower() == "```text":
        json_section = "\n".join(json_lines[:-1]).strip()

    if not json_section:
        raise ValueError("Missing JSON section before payload blocks.")
    return json_section, _strip_payload_section_markdown_fence(
        normalized[begin_match.start() :]
    )


def _strip_payload_section_markdown_fence(payload_section: str) -> str:
    """Tolerate an accidental closing fence after payload blocks.

    The prompt forbids markdown fences, but models sometimes wrap the payload
    tail in ```text. ``split_json_and_payload_sections`` removes the opening
    fence before the first payload marker; this helper removes only the matching
    final fence line so payload content remains untouched.
    """
    lines = payload_section.strip().splitlines()
    if lines and lines[-1].strip() == "```":
        return "\n".join(lines[:-1]).strip()
    return payload_section


def parse_payload_blocks(payload_section: str) -> dict[str, str]:
    """Parse named payload blocks appended after the JSON control section.

    Args:
        payload_section: Raw text starting at the first payload marker.

    Returns:
        Mapping from payload name to the raw payload body.

    Raises:
        ValueError: If payload markers are malformed or inconsistent.
    """
    payloads: dict[str, str] = {}
    text = payload_section.strip()
    cursor = 0

    while cursor < len(text):
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        if cursor >= len(text):
            break

        begin_match = PAYLOAD_BEGIN_RE.match(text, cursor)
        if begin_match is None:
            snippet = text[cursor : cursor + 120]
            raise ValueError(f"Invalid payload block marker near: {snippet}")

        payload_name = begin_match.group(1)
        if payload_name in payloads:
            raise ValueError(f"Duplicate payload name: {payload_name}")

        content_start = begin_match.end()
        if content_start < len(text) and text[content_start] == "\n":
            content_start += 1

        end_re = re.compile(
            rf"(?m)^<<<PIVOT_PAYLOAD:{re.escape(payload_name)}:END_{PAYLOAD_SENTINEL_SUFFIX}>>>$"
        )
        end_match = end_re.search(text, content_start)
        if end_match is None:
            raise ValueError(f"Missing END marker for payload: {payload_name}")

        content_end = end_match.start()
        if content_end > content_start and text[content_end - 1] == "\n":
            content_end -= 1
            if content_end > content_start and text[content_end - 1] == "\r":
                content_end -= 1

        payloads[payload_name] = text[content_start:content_end]
        cursor = end_match.end()

    return payloads


def collect_complete_payload_blocks(content: str) -> dict[str, str]:
    """Collect payload blocks that are fully closed in a partial response.

    Unlike :func:`parse_payload_blocks`, this helper intentionally ignores the
    final incomplete block so streaming callers can start work as soon as one
    tool payload is ready.
    """
    _json_section, payload_section = split_json_and_payload_sections(content)
    if payload_section is None:
        return {}

    payloads: dict[str, str] = {}
    text = payload_section.strip()
    cursor = 0

    while cursor < len(text):
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        if cursor >= len(text):
            break

        begin_match = PAYLOAD_BEGIN_RE.match(text, cursor)
        if begin_match is None:
            break

        payload_name = begin_match.group(1)
        if payload_name in payloads:
            raise ValueError(f"Duplicate payload name: {payload_name}")

        content_start = begin_match.end()
        if content_start < len(text) and text[content_start] == "\n":
            content_start += 1

        end_re = re.compile(
            rf"(?m)^<<<PIVOT_PAYLOAD:{re.escape(payload_name)}:END_{PAYLOAD_SENTINEL_SUFFIX}>>>$"
        )
        end_match = end_re.search(text, content_start)
        if end_match is None:
            break

        content_end = end_match.start()
        if content_end > content_start and text[content_end - 1] == "\n":
            content_end -= 1
            if content_end > content_start and text[content_end - 1] == "\r":
                content_end -= 1

        payloads[payload_name] = text[content_start:content_end]
        cursor = end_match.end()

    return payloads


def collect_tool_call_payload_refs(tool_call: ToolCallRequest) -> set[str]:
    """Return all payload names referenced by one tool call."""
    refs: set[str] = set()
    for arg_name, raw_arg_value in tool_call.arguments.items():
        refs.add(
            _extract_payload_ref_name(
                raw_arg_value,
                path=f"tool_call[{tool_call.id}].arguments.{arg_name}",
            )
        )
    return refs


def resolve_tool_call_payloads(
    tool_call: ToolCallRequest,
    payloads: dict[str, str],
    *,
    tool_manager: Any | None = None,
) -> ToolCallRequest:
    """Resolve one preview tool call once all referenced payload blocks are ready."""
    resolved_arguments: dict[str, Any] = {}
    for arg_name, raw_arg_value in tool_call.arguments.items():
        ref_name = _extract_payload_ref_name(
            raw_arg_value,
            path=f"tool_call[{tool_call.id}].arguments.{arg_name}",
        )
        if ref_name not in payloads:
            raise ValueError(
                f"Payload reference '{ref_name}' in tool_call[{tool_call.id}]."
                f"arguments.{arg_name} is not defined."
            )
        expected_type = _lookup_tool_argument_type(
            tool_manager=tool_manager,
            tool_name=tool_call.name,
            arg_name=arg_name,
        )
        resolved_arguments[arg_name] = _decode_payload_value(
            payloads[ref_name],
            expected_type=expected_type,
        )

    return ToolCallRequest(
        id=tool_call.id,
        name=tool_call.name,
        arguments=resolved_arguments,
        batch=tool_call.batch,
    )


def parse_react_output(
    content: str,
    *,
    tool_manager: Any | None = None,
) -> ParsedReactDecision:
    """Parse and validate one strict assistant decision payload.

    Args:
        content: Raw assistant response text.
        tool_manager: Optional tool registry used to decode payload blocks with
            awareness of the target tool parameter types.

    Returns:
        A typed, validated decision object.

    Raises:
        ValueError: If the response violates the ReAct protocol contract.
    """
    json_section, payload_section = split_json_and_payload_sections(content)
    raw_payload = safe_load_json(json_section)
    payloads = (
        parse_payload_blocks(payload_section) if payload_section is not None else {}
    )
    resolved_payload = _resolve_tool_payload_references(
        raw_payload,
        payloads,
        tool_manager=tool_manager,
    )
    resolved_payload = _normalize_step_status_update_location(resolved_payload)
    action = _parse_action(resolved_payload)

    observe = _expect_optional_string(resolved_payload.get("observe"), "observe")
    reason = _expect_optional_string(resolved_payload.get("reason"), "reason")
    summary = _expect_optional_string(
        resolved_payload.get("summary"),
        "summary",
    )
    thinking_next_turn = _expect_optional_bool(
        resolved_payload.get("thinking_next_turn"),
        "thinking_next_turn",
    )
    session_title = _expect_optional_string(
        resolved_payload.get("session_title"),
        "session_title",
    )

    task_summary = _expect_optional_dict(
        resolved_payload.get("task_summary"),
        "task_summary",
    )

    resolved_payload["action"] = action.to_dict()
    return ParsedReactDecision(
        observe=observe,
        reason=reason,
        summary=summary,
        thinking_next_turn=thinking_next_turn,
        session_title=session_title,
        action=action,
        task_summary=task_summary,
        raw_payload=resolved_payload,
    )


def parse_react_control_section(content: str) -> ParsedReactDecision:
    """Parse only the leading JSON control section of a ReAct response.

    This is intentionally lighter than :func:`parse_react_output`: it validates
    the JSON decision envelope before payload blocks are complete, but leaves
    CALL_TOOL arguments as their ``{"$payload_ref": ...}`` placeholders. The
    returned decision is suitable for early UI streaming only; final execution
    must still use ``parse_react_output`` so payload references are resolved.
    """
    json_section, _payload_section = split_json_and_payload_sections(content)
    raw_payload = safe_load_json(json_section)
    raw_payload = _normalize_step_status_update_location(raw_payload)
    action = _parse_action(raw_payload)

    observe = _expect_optional_string(raw_payload.get("observe"), "observe")
    reason = _expect_optional_string(raw_payload.get("reason"), "reason")
    summary = _expect_optional_string(raw_payload.get("summary"), "summary")
    thinking_next_turn = _expect_optional_bool(
        raw_payload.get("thinking_next_turn"),
        "thinking_next_turn",
    )
    session_title = _expect_optional_string(
        raw_payload.get("session_title"),
        "session_title",
    )
    task_summary = _expect_optional_dict(
        raw_payload.get("task_summary"),
        "task_summary",
    )

    preview_payload = dict(raw_payload)
    preview_payload["action"] = action.to_dict()
    return ParsedReactDecision(
        observe=observe,
        reason=reason,
        summary=summary,
        thinking_next_turn=thinking_next_turn,
        session_title=session_title,
        action=action,
        task_summary=task_summary,
        raw_payload=preview_payload,
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
    tool_calls = _parse_tool_calls(normalized_action_type, action_output)

    action_output_payload = dict(action_output)
    if tool_calls:
        action_output_payload["tool_calls"] = [
            tool_call.to_dict() for tool_call in tool_calls
        ]

    return ParsedAction(
        action_type=normalized_action_type,
        output=action_output_payload,
        step_id=step_id,
        step_status_update=step_status_update,
        tool_calls=tool_calls,
    )


def _expect_optional_bool(value: Any, field_name: str) -> bool | None:
    """Return an optional boolean field after strict validation.

    Args:
        value: Raw parsed value.
        field_name: Human-readable field name for error messages.

    Returns:
        ``None`` when the field is absent, otherwise the validated boolean.

    Raises:
        ValueError: If the value exists but is not a boolean.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raise ValueError(f"{field_name} must be a boolean when provided.")


def _parse_step_id(raw_value: Any) -> str | None:
    """Normalize an optional action step identifier.

    Args:
        raw_value: Raw value from ``action.step_id``.

    Returns:
        A stripped step identifier or ``None``.

    Raises:
        ValueError: If the value is neither absent nor a non-empty string.
    """
    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise ValueError("action.step_id must be a string when provided.")

    normalized = raw_value.strip()
    return normalized or None


def _parse_step_status_updates(raw_value: Any) -> list[StepStatusUpdate]:
    """Validate explicit plan-step status updates.

    Args:
        raw_value: Raw value from ``action.step_status_update``.

    Returns:
        A list of validated status updates.

    Raises:
        ValueError: If the payload shape is invalid.
    """
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


def _parse_tool_calls(
    action_type: str,
    action_output: dict[str, Any],
) -> list[ToolCallRequest]:
    """Validate tool calls when the action type requires them.

    Args:
        action_type: Normalized action type.
        action_output: Raw action output payload.

    Returns:
        A list of validated tool-call requests.

    Raises:
        ValueError: If CALL_TOOL payload is missing or malformed.
    """
    if action_type != "CALL_TOOL":
        return []

    tool_calls = action_output.get("tool_calls")
    if not isinstance(tool_calls, list) or not tool_calls:
        raise ValueError(
            "CALL_TOOL requires action.output.tool_calls to be a non-empty list."
        )

    seen_tool_call_ids: set[str] = set()
    normalized_tool_calls: list[ToolCallRequest] = []
    for index, item in enumerate(tool_calls):
        if not isinstance(item, dict):
            raise ValueError(f"action.output.tool_calls[{index}] must be an object.")

        tool_call_id = item.get("id")
        if not isinstance(tool_call_id, str) or not tool_call_id.strip():
            raise ValueError(
                f"action.output.tool_calls[{index}].id must be a non-empty string."
            )
        normalized_tool_call_id = tool_call_id.strip()
        if normalized_tool_call_id in seen_tool_call_ids:
            raise ValueError(f"Duplicate tool_call id: {normalized_tool_call_id}.")
        seen_tool_call_ids.add(normalized_tool_call_id)

        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(
                f"action.output.tool_calls[{index}].name must be a non-empty string."
            )

        arguments = item.get("arguments")
        if not isinstance(arguments, dict):
            raise ValueError(
                f"action.output.tool_calls[{index}].arguments must be an object."
            )

        batch = item.get("batch", 1)
        if isinstance(batch, bool) or not isinstance(batch, int) or batch < 1:
            raise ValueError(
                f"action.output.tool_calls[{index}].batch must be a positive integer."
            )

        normalized_tool_calls.append(
            ToolCallRequest(
                id=normalized_tool_call_id,
                name=name.strip(),
                arguments=arguments,
                batch=batch,
            )
        )

    return normalized_tool_calls


def _expect_optional_string(raw_value: Any, path: str) -> str:
    """Validate an optional string field and normalize absent values to ``""``.

    Args:
        raw_value: Raw field value.
        path: Human-readable field path for errors.

    Returns:
        A normalized string value.

    Raises:
        ValueError: If the value is not ``None`` or ``str``.
    """
    if raw_value is None:
        return ""
    if not isinstance(raw_value, str):
        raise ValueError(f"{path} must be a string when provided.")
    return raw_value


def _expect_optional_dict(raw_value: Any, path: str) -> dict[str, Any]:
    """Validate an optional dictionary field.

    Args:
        raw_value: Raw field value.
        path: Human-readable field path for errors.

    Returns:
        A dictionary value or an empty dictionary when absent.

    Raises:
        ValueError: If the value is not ``None`` or ``dict``.
    """
    if raw_value is None:
        return {}
    if not isinstance(raw_value, dict):
        raise ValueError(f"{path} must be an object when provided.")
    return raw_value


def _extract_payload_ref_name(value: Any, path: str) -> str:
    """Extract the referenced payload name from one tool argument value.

    Args:
        value: Raw tool argument value.
        path: Human-readable path for error messages.

    Returns:
        The referenced payload name.

    Raises:
        ValueError: If the value is not a valid payload reference object.
    """
    if not isinstance(value, dict):
        raise ValueError(
            f"Invalid argument at {path}: every CALL_TOOL argument must be a "
            f"payload reference object with {PAYLOAD_REF_KEY}."
        )
    if len(value) != 1 or PAYLOAD_REF_KEY not in value:
        raise ValueError(
            f"Invalid payload reference object at {path}: {PAYLOAD_REF_KEY} must be the only key."
        )

    raw_ref_name = value.get(PAYLOAD_REF_KEY)
    if not isinstance(raw_ref_name, str):
        raise ValueError(
            f"Invalid payload reference at {path}: {PAYLOAD_REF_KEY} must be a string."
        )
    if not re.fullmatch(PAYLOAD_NAME_PATTERN, raw_ref_name):
        raise ValueError(f"Invalid payload name '{raw_ref_name}' at {path}.")
    return raw_ref_name


def _lookup_tool_argument_type(
    *,
    tool_manager: Any | None,
    tool_name: str,
    arg_name: str,
) -> str | None:
    """Return one declared JSON Schema type for a tool argument when available."""
    if tool_manager is None:
        return None

    get_tool = getattr(tool_manager, "get_tool", None)
    if not callable(get_tool):
        return None

    tool_metadata = get_tool(tool_name)
    if tool_metadata is None:
        return None

    parameters = getattr(tool_metadata, "parameters", None)
    if not isinstance(parameters, dict):
        return None

    properties = parameters.get("properties")
    if not isinstance(properties, dict):
        return None

    argument_schema = properties.get(arg_name)
    if not isinstance(argument_schema, dict):
        return None

    schema_type = argument_schema.get("type")
    return schema_type if isinstance(schema_type, str) else None


def _decode_payload_value(
    payload_text: str,
    *,
    expected_type: str | None = None,
) -> Any:
    """Decode a payload block into a tool argument value.

    Args:
        payload_text: Raw payload body between begin and end markers.
        expected_type: Optional JSON Schema type declared by the target tool
            parameter.

    Returns:
        Parsed JSON when possible; otherwise the original payload text.
    """
    if expected_type == "string":
        candidate = payload_text.strip()
        if not candidate:
            return payload_text
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            return payload_text
        return parsed if isinstance(parsed, str) else payload_text

    candidate = payload_text.strip()
    if not candidate:
        return payload_text
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return payload_text


def _resolve_tool_payload_references(
    react_output: dict[str, Any],
    payloads: dict[str, str],
    *,
    tool_manager: Any | None = None,
) -> dict[str, Any]:
    """Resolve named payload blocks referenced by CALL_TOOL arguments.

    Args:
        react_output: Parsed top-level assistant payload.
        payloads: Payload block mapping extracted from the response tail.
        tool_manager: Optional tool registry used to decode payload blocks with
            awareness of the target tool parameter types.

    Returns:
        The payload with resolved tool arguments.

    Raises:
        ValueError: If payload references are inconsistent with the JSON section.
    """
    action = react_output.get("action")
    action_type = action.get("action_type", "") if isinstance(action, dict) else ""
    action_output = action.get("output", {}) if isinstance(action, dict) else {}

    if payloads and action_type != "CALL_TOOL":
        raise ValueError("Payload blocks are only allowed when action_type=CALL_TOOL.")

    if action_type != "CALL_TOOL":
        return react_output

    if not payloads:
        raise ValueError("CALL_TOOL requires payload blocks after the JSON section.")
    if not isinstance(action_output, dict):
        raise ValueError("CALL_TOOL action.output must be an object.")

    tool_calls = action_output.get("tool_calls")
    if not isinstance(tool_calls, list):
        raise ValueError("CALL_TOOL action.output.tool_calls must be a list.")

    used_payloads: set[str] = set()
    for index, tool_call in enumerate(tool_calls):
        if not isinstance(tool_call, dict):
            raise ValueError(
                f"CALL_TOOL action.output.tool_calls[{index}] must be an object."
            )
        tool_name = tool_call.get("name")

        raw_arguments = tool_call.get("arguments")
        if not isinstance(raw_arguments, dict):
            raise ValueError(
                f"CALL_TOOL action.output.tool_calls[{index}].arguments must be an object."
            )

        resolved_arguments: dict[str, Any] = {}
        for arg_name, raw_arg_value in raw_arguments.items():
            ref_name = _extract_payload_ref_name(
                raw_arg_value,
                path=f"action.output.tool_calls[{index}].arguments.{arg_name}",
            )
            if ref_name not in payloads:
                raise ValueError(
                    f"Payload reference '{ref_name}' in tool_calls[{index}].arguments."
                    f"{arg_name} is not defined."
                )

            used_payloads.add(ref_name)
            expected_type = (
                _lookup_tool_argument_type(
                    tool_manager=tool_manager,
                    tool_name=tool_name,
                    arg_name=arg_name,
                )
                if isinstance(tool_name, str)
                else None
            )
            resolved_arguments[arg_name] = _decode_payload_value(
                payloads[ref_name],
                expected_type=expected_type,
            )

        tool_call["arguments"] = resolved_arguments

    unused_payloads = sorted(set(payloads) - used_payloads)
    if unused_payloads:
        raise ValueError(
            "Unused payload blocks detected: " + ", ".join(unused_payloads)
        )

    return react_output
