"""Typed ReAct protocol objects used by the orchestration runtime."""

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ToolCallRequest:
    """Validated tool call emitted by the model.

    Attributes:
        id: Tool-call identifier returned by the model.
        name: Tool registry name to execute.
        arguments: Fully resolved argument object for the call.
    """

    id: str
    name: str
    arguments: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Serialize the tool call for persistence and streaming.

        ``arguments`` is serialized to a JSON string because the internal
        unified message format stores it that way (matching the OpenAI
        wire format).  Downstream consumers — ``message_converter`` and
        ``append_assistant_message`` — expect a string.
        """
        return {
            "id": self.id,
            "name": self.name,
            "arguments": json.dumps(self.arguments, ensure_ascii=False),
        }


@dataclass(slots=True)
class ParsedAction:
    """Normalized action payload from the model response.

    Attributes:
        action_type: One of the allowed ReAct action types.
        output: Action-specific output payload.
        tool_calls: Validated tool-call requests when action_type is CALL_TOOL.
    """

    action_type: str
    output: dict[str, Any]
    tool_calls: list[ToolCallRequest] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the normalized action back into protocol shape.

        Returns:
            A plain dictionary representation of the action.
        """
        return {
            "action_type": self.action_type,
            "output": self.output,
        }


@dataclass(slots=True)
class ParsedReactDecision:
    """Fully parsed assistant decision for one recursion.

    Attributes:
        message: User-facing progress note emitted every recursion.
        thinking_next_turn: Hint controlling whether the next recursion should
            use provider thinking mode when the runtime is in Auto mode.
        action: Parsed action definition.
        raw_payload: Canonical dictionary representation of the parsed response.
    """

    message: str
    thinking_next_turn: bool | None
    action: ParsedAction
    raw_payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Return a canonical dictionary for logging and persistence.

        Returns:
            The parsed assistant payload as a dictionary.
        """
        return self.raw_payload
