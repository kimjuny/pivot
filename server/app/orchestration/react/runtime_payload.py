"""Shared runtime payload helpers for ReAct prompt construction."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from app.models.react import ReactTask

    from .context import ReactContext

from .plan_files import (
    format_plan_full,
    plan_exists,
    read_steps,
)


def build_recursion_user_payload(
    task: ReactTask,
    context: ReactContext,
    pending_action_result: list[dict[str, Any]] | None,
    *,
    attachments: list[dict[str, Any]] | None = None,
    after_compaction: bool = False,
    user_intent_override: str | None = None,
    include_action_result: bool = True,
    workspace_path: str | Path | None = None,
    previous_steps_json: str | None = None,
    system_feedback: str | None = None,
) -> dict[str, Any]:
    """Build the next recursion payload appended as a user message.

    After the native tool calling migration, tool results are fed back via
    the ``tool_results`` key on the user message (handled by the message
    converter), so ``action_result`` is only included when explicitly
    requested (e.g. for non-tool CALL_TOOL legacy compatibility during
    the transition period).
    """
    steps_value: str | list[dict[str, Any]] = ""
    plan_file_path: str | None = None
    if workspace_path and plan_exists(workspace_path, task.task_id):
        steps = read_steps(workspace_path, task.task_id)
        plan_file_path = f".pivot/plans/{task.task_id}"
        steps_value = format_plan_full(steps)

        # Compress to "no changes" when steps are identical to previous iteration.
        if (
            previous_steps_json is not None
            and isinstance(steps_value, list)
            and previous_steps_json
        ):
            current_json = json.dumps(steps_value, ensure_ascii=False)
            if current_json == previous_steps_json:
                steps_value = "no changes"

    payload: dict[str, Any] = {
        "iteration": task.iteration + 1,
        "current_steps": steps_value,
    }
    if plan_file_path:
        payload["plan_file"] = plan_file_path
    if task.iteration == 0:
        payload["user_intent"] = task.user_intent
    elif user_intent_override is not None:
        payload["user_intent"] = user_intent_override
    if include_action_result and pending_action_result is not None:
        payload["action_result"] = pending_action_result
    if attachments:
        payload["attachments"] = attachments
    if system_feedback:
        payload["system_feedback"] = system_feedback
    return payload
