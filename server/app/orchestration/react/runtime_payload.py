"""Shared runtime payload helpers for ReAct prompt construction."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.config import get_settings

if TYPE_CHECKING:
    from app.models.react import ReactTask

    from .context import ReactContext


def build_current_plan_payload(context: ReactContext) -> list[dict[str, Any]]:
    """Convert the current plan context into the structured prompt payload."""
    current_plan: list[dict[str, Any]] = []
    history_limit = max(get_settings().REACT_CURRENT_PLAN_HISTORY_LIMIT, 0)
    for step in context.context.get("plan", []):
        if not isinstance(step, dict):
            continue
        step_id = step.get("step_id")
        if not isinstance(step_id, str):
            continue
        recursion_history: list[dict[str, Any]] = []
        raw_history = step.get("recursion_history", [])
        if isinstance(raw_history, list):
            history_slice = raw_history[-history_limit:] if history_limit > 0 else []
            for history_entry in history_slice:
                if not isinstance(history_entry, dict):
                    continue
                recursion_history.append(
                    {
                        "iteration": history_entry.get("iteration"),
                        "message": history_entry.get("message", ""),
                    }
                )
        current_plan.append(
            {
                "step_id": step_id,
                "general_goal": step.get("general_goal", ""),
                "specific_description": step.get("specific_description", ""),
                "completion_criteria": step.get("completion_criteria", ""),
                "status": step.get("status", "pending"),
                "recursion_history": recursion_history,
            }
        )
    return current_plan


def build_plan_status_line(context: ReactContext) -> str:
    """Build a one-line plan summary used before compaction."""
    steps: list[dict[str, Any]] = [
        s
        for s in context.context.get("plan", [])
        if isinstance(s, dict) and isinstance(s.get("step_id"), str)
    ]
    if not steps:
        return ""

    done_ids: list[str] = []
    in_progress_ids: list[str] = []
    pending_ids: list[str] = []
    for step in steps:
        step_id = str(step.get("step_id", ""))
        status = step.get("status", "pending")
        if status == "done":
            done_ids.append(step_id)
        elif status == "in_progress":
            in_progress_ids.append(step_id)
        else:
            pending_ids.append(step_id)

    parts: list[str] = []
    if done_ids:
        parts.append(f"Steps {','.join(done_ids)} done")
    if in_progress_ids:
        parts.append(f"Step {','.join(in_progress_ids)} in_progress")
    if pending_ids:
        parts.append(f"Steps {','.join(pending_ids)} pending")
    return ", ".join(parts) if parts else ""


def build_recursion_user_payload(
    task: ReactTask,
    context: ReactContext,
    pending_action_result: list[dict[str, Any]] | None,
    *,
    attachments: list[dict[str, Any]] | None = None,
    after_compaction: bool = False,
    user_intent_override: str | None = None,
) -> dict[str, Any]:
    """Build the next recursion payload appended as a user message."""
    if after_compaction:
        plan_value: str | list[dict[str, Any]] = build_current_plan_payload(context)
    else:
        plan_value = build_plan_status_line(context)

    payload: dict[str, Any] = {
        "iteration": task.iteration + 1,
        "current_plan": plan_value,
    }
    if task.iteration == 0:
        payload["user_intent"] = task.user_intent
    elif user_intent_override is not None:
        payload["user_intent"] = user_intent_override
    if pending_action_result is not None:
        payload["action_result"] = pending_action_result
    if attachments:
        payload["attachments"] = attachments
    return payload
