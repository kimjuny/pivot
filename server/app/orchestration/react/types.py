"""Typed ReAct protocol objects used by the orchestration runtime."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class StepStatusUpdate:
    """Normalized plan-step status transition declared by the model.

    Attributes:
        step_id: Stable identifier of the plan step to update.
        status: Target status after normalization and validation.
    """

    step_id: str
    status: str

    def to_dict(self) -> dict[str, str]:
        """Serialize the update for persistence and event payloads.

        Returns:
            A plain dictionary representation of the update.
        """
        return {
            "step_id": self.step_id,
            "status": self.status,
        }


@dataclass(slots=True)
class ToolCallRequest:
    """Validated tool call emitted by the model.

    Attributes:
        id: Tool-call identifier returned by the model.
        name: Tool registry name to execute.
        batch: Positive execution batch. Lower batches run first; calls in the
            same batch may run concurrently.
        arguments: Fully resolved argument object for the call.
    """

    id: str
    name: str
    arguments: dict[str, Any]
    batch: int = 1

    def to_dict(self) -> dict[str, Any]:
        """Serialize the tool call for persistence and streaming.

        Returns:
            A plain dictionary representation of the tool call.
        """
        return {
            "id": self.id,
            "name": self.name,
            "batch": self.batch,
            "arguments": self.arguments,
        }


@dataclass(slots=True)
class ParsedAction:
    """Normalized action payload from the model response.

    Attributes:
        action_type: One of the allowed ReAct action types.
        output: Action-specific output payload.
        step_id: Optional active plan step identifier.
        step_status_update: Explicit plan-step status mutations.
        tool_calls: Validated tool-call requests when action_type is CALL_TOOL.
    """

    action_type: str
    output: dict[str, Any]
    step_id: str | None = None
    step_status_update: list[StepStatusUpdate] = field(default_factory=list)
    tool_calls: list[ToolCallRequest] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the normalized action back into protocol shape.

        Returns:
            A plain dictionary representation of the action.
        """
        payload: dict[str, Any] = {
            "action_type": self.action_type,
            "output": self.output,
        }
        if self.step_id is not None:
            payload["step_id"] = self.step_id
        if self.step_status_update:
            payload["step_status_update"] = [
                item.to_dict() for item in self.step_status_update
            ]
        return payload


@dataclass(slots=True)
class ParsedReactDecision:
    """Fully parsed assistant decision for one recursion.

    Attributes:
        observe: Optional assistant observation text, normalized to ``""`` when
            omitted by the model.
        reason: Optional assistant reasoning text, normalized to ``""`` when
            omitted by the model.
        summary: Optional user-facing progress summary.
        thinking_next_turn: Optional hint controlling whether the next recursion
            should use provider thinking mode when the runtime is in Auto mode.
        session_title: Optional session title proposed by the assistant.
        action: Parsed action definition.
        task_summary: Optional summary payload for the completed task.
        raw_payload: Canonical dictionary representation of the parsed response.
    """

    observe: str
    reason: str
    summary: str
    thinking_next_turn: bool | None
    session_title: str
    action: ParsedAction
    task_summary: dict[str, Any]
    raw_payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Return a canonical dictionary for logging and persistence.

        Returns:
            The parsed assistant payload as a dictionary.
        """
        return self.raw_payload
