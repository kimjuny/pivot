"""Persistence helpers for ReAct recursion and task state."""

from __future__ import annotations

import copy
import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.models.react import (
    ReactPlanStep,
    ReactRecursion,
    ReactRecursionState,
    ReactTask,
)
from app.services.session_service import SessionService
from sqlmodel import Session as DBSession, col, delete, select

if TYPE_CHECKING:
    from app.orchestration.react.context import ReactContext

logger = logging.getLogger(__name__)


class ReactStateService:
    """Encapsulates persistence for recursion records and task lifecycle.

    This service centralizes all database mutations related to ReAct execution
    state so the orchestration loop can focus on control flow instead of SQLModel
    bookkeeping.
    """

    def __init__(self, db: DBSession) -> None:
        """Initialize the service with a database session.

        Args:
            db: Database session used to persist ReAct state changes.
        """
        self.db = db

    def load_context(self, task: ReactTask) -> ReactContext:
        """Load the current task context from persisted state.

        Args:
            task: Task whose execution context should be loaded.

        Returns:
            The reconstructed ReAct context.
        """
        from app.orchestration.react.context import ReactContext

        return ReactContext.from_task(task, self.db)

    def start_recursion(self, task: ReactTask, trace_id: str) -> ReactRecursion:
        """Create and persist a new recursion row.

        Args:
            task: Task that owns the recursion.
            trace_id: Server-generated recursion trace ID.

        Returns:
            The persisted recursion row.
        """
        recursion = ReactRecursion(
            trace_id=trace_id,
            task_id=task.task_id,
            react_task_id=task.id or 0,
            iteration_index=task.iteration,
            status="running",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.db.add(recursion)
        self.db.commit()
        self.db.refresh(recursion)
        return recursion

    def finalize_success(
        self,
        task: ReactTask,
        recursion: ReactRecursion,
        context: ReactContext,
        observe: str,
        thinking: str | None,
        reason: str,
        action_type: str,
        action_output: dict[str, Any],
        action_step_id: str | None,
        step_status_updates: list[dict[str, str]],
        summary: str,
        tool_results: list[dict[str, Any]],
        token_counter: dict[str, int],
        pending_user_action: dict[str, Any] | None = None,
    ) -> dict[str, int] | None:
        """Persist a successful recursion and update derived task state.

        Args:
            task: Owning task.
            recursion: Recursion row created for this cycle.
            context: Mutable in-memory context snapshot for this cycle.
            observe: Assistant observe content.
            thinking: Raw provider reasoning content, if available.
            reason: Assistant reason content.
            action_type: Final normalized action type.
            action_output: Mutable action output payload. Tool results may be
                merged into it for snapshot/event consistency.
            action_step_id: Optional plan step associated with this recursion.
            step_status_updates: Validated step status updates.
            summary: Optional user-facing progress summary text.
            tool_results: Executed tool results for this recursion.
            token_counter: Aggregated token usage for the recursion.
            pending_user_action: Optional system-owned waiting action created by
                a tool result and persisted on the task row.

        Returns:
            Persisted token usage payload, or `None` if empty.
        """
        raw_action_output = copy.deepcopy(action_output)

        recursion.observe = observe
        recursion.thinking = thinking
        recursion.reason = reason
        recursion.action_type = action_type
        recursion.action_output = json.dumps(raw_action_output, ensure_ascii=False)
        recursion.plan_step_id = self._resolve_plan_step_id(
            task=task,
            action_type=action_type,
            action_step_id=action_step_id,
            trace_id=recursion.trace_id,
        )

        if summary:
            recursion.summary = summary

        if tool_results:
            recursion.tool_call_results = json.dumps(tool_results, ensure_ascii=False)

        tokens_data = self._apply_token_usage(task, recursion, token_counter)
        recursion.status = "done"
        recursion.updated_at = datetime.now(UTC)
        self.db.add(recursion)

        self._merge_tool_results_into_action_output(action_output, tool_results)
        self._sync_context_before_snapshot(
            task=task,
            context=context,
            recursion=recursion,
            action_type=action_type,
            action_output=action_output,
            step_status_updates=step_status_updates,
            summary=summary,
        )
        self._save_snapshot(task, recursion, context)

        if action_type == "CLARIFY":
            self._set_task_status(task, "waiting_input", commit=False)
        elif pending_user_action is not None:
            task.pending_user_action_json = json.dumps(
                pending_user_action,
                ensure_ascii=False,
            )
            self._set_task_status(task, "waiting_input", commit=False)

        self.db.commit()
        return tokens_data

    def finalize_error(
        self,
        task: ReactTask,
        recursion: ReactRecursion,
        error_log: str,
        token_counter: dict[str, int] | None = None,
    ) -> dict[str, int] | None:
        """Persist a failed recursion.

        Args:
            task: Owning task.
            recursion: Recursion row created for this cycle.
            error_log: Error message to persist on the recursion.
            token_counter: Optional token usage to aggregate before failure.

        Returns:
            Persisted token usage payload, or `None` if empty.
        """
        tokens_data = self._apply_token_usage(
            task,
            recursion,
            token_counter or {},
        )
        recursion.status = "error"
        recursion.error_log = error_log
        recursion.updated_at = datetime.now(UTC)
        self.db.add(recursion)
        self.db.commit()
        return tokens_data

    def mark_running(self, task: ReactTask) -> None:
        """Persist the task as running.

        Args:
            task: Task to mark as running.
        """
        self._set_task_status(task, "running")

    def mark_cancelled(self, task: ReactTask) -> None:
        """Persist the task as cancelled.

        Args:
            task: Task to mark as cancelled.
        """
        self._set_task_status(task, "cancelled")

    def mark_completed(self, task: ReactTask) -> None:
        """Persist the task as completed.

        Args:
            task: Task to mark as completed.
        """
        self._set_task_status(task, "completed")

    def mark_failed(self, task: ReactTask) -> None:
        """Persist the task as failed.

        Args:
            task: Task to mark as failed.
        """
        self._set_task_status(task, "failed")

    def advance_iteration(self, task: ReactTask) -> None:
        """Increment and persist the task iteration counter.

        Args:
            task: Task whose iteration should advance by one.
        """
        task.iteration += 1
        task.updated_at = datetime.now(UTC)
        self.db.add(task)
        self.db.commit()

    def record_task_usage(self, task: ReactTask, token_counter: dict[str, int]) -> None:
        """Accumulate non-recursion token usage directly onto the task row.

        Why: context compaction is a real LLM call that affects the session
        window, but it should not appear as a synthetic recursion in the user UI.

        Args:
            task: Task receiving aggregate token increments.
            token_counter: Usage payload returned by the compact LLM call.
        """
        total_tokens = int(token_counter.get("total_tokens", 0) or 0)
        if total_tokens <= 0:
            return

        task.total_prompt_tokens += int(token_counter.get("prompt_tokens", 0) or 0)
        task.total_completion_tokens += int(
            token_counter.get("completion_tokens", 0) or 0
        )
        task.total_tokens += total_tokens
        task.total_cached_input_tokens += int(
            token_counter.get("cached_input_tokens", 0) or 0
        )
        task.updated_at = datetime.now(UTC)
        self.db.add(task)
        self.db.commit()

    def _apply_token_usage(
        self,
        task: ReactTask,
        recursion: ReactRecursion,
        token_counter: dict[str, int],
    ) -> dict[str, int] | None:
        """Persist aggregated token usage onto task and recursion rows.

        Args:
            task: Task receiving aggregate token increments.
            recursion: Recursion row receiving per-recursion totals.
            token_counter: Aggregated usage across parse attempts.

        Returns:
            A serialized token payload, or `None` if usage is empty.
        """
        total_tokens = int(token_counter.get("total_tokens", 0) or 0)
        if total_tokens <= 0:
            return None

        prompt_tokens = int(token_counter.get("prompt_tokens", 0) or 0)
        completion_tokens = int(token_counter.get("completion_tokens", 0) or 0)
        cached_input_tokens = int(token_counter.get("cached_input_tokens", 0) or 0)

        recursion.prompt_tokens = prompt_tokens
        recursion.completion_tokens = completion_tokens
        recursion.total_tokens = total_tokens
        recursion.cached_input_tokens = cached_input_tokens

        task.total_prompt_tokens += prompt_tokens
        task.total_completion_tokens += completion_tokens
        task.total_tokens += total_tokens
        task.total_cached_input_tokens += cached_input_tokens

        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cached_input_tokens": cached_input_tokens,
        }

    def _resolve_plan_step_id(
        self,
        task: ReactTask,
        action_type: str,
        action_step_id: str | None,
        trace_id: str,
    ) -> str | None:
        """Validate the declared plan step association for a recursion.

        Args:
            task: Owning task.
            action_type: Action type produced by the recursion.
            action_step_id: Declared plan step ID from the model.
            trace_id: Recursion trace ID for logging.

        Returns:
            The validated step ID, or `None`.
        """
        existing_plan_steps = self.db.exec(
            select(ReactPlanStep).where(ReactPlanStep.task_id == task.task_id)
        ).all()
        plan_is_active = len(existing_plan_steps) > 0

        if plan_is_active and not action_step_id:
            logger.error(
                "Action returned without step_id while a plan is active. "
                "The recursion result will NOT be attributed to any plan step. "
                "trace_id=%s, task_id=%s, action_type=%s, iteration=%s",
                trace_id,
                task.task_id,
                action_type,
                task.iteration,
            )
            return None

        if action_step_id:
            known_step_ids = {step.step_id for step in existing_plan_steps}
            if action_step_id not in known_step_ids:
                logger.error(
                    "LLM returned unknown step_id='%s' (known: %s). "
                    "Saving as-is for debugging; it will not match any plan step. "
                    "trace_id=%s, task_id=%s",
                    action_step_id,
                    sorted(known_step_ids),
                    trace_id,
                    task.task_id,
                )

        return action_step_id

    def _merge_tool_results_into_action_output(
        self,
        action_output: dict[str, Any],
        tool_results: list[dict[str, Any]],
    ) -> None:
        """Merge tool execution results into action output for snapshots/events.

        Args:
            action_output: Mutable action output payload.
            tool_results: Tool execution results to inject.
        """
        if not tool_results:
            return

        result_by_id = {
            result["tool_call_id"]: result
            for result in tool_results
            if "tool_call_id" in result
        }
        for tool_call in action_output.get("tool_calls", []):
            matched = result_by_id.get(tool_call.get("id", ""))
            if matched is not None:
                tool_call["result"] = matched.get("result", "")
                tool_call["success"] = matched.get("success", False)

    def _sync_context_before_snapshot(
        self,
        task: ReactTask,
        context: ReactContext,
        recursion: ReactRecursion,
        action_type: str,
        action_output: dict[str, Any],
        step_status_updates: list[dict[str, str]],
        summary: str,
    ) -> None:
        """Apply recursion side effects to the in-memory context before snapshot.

        Args:
            task: Owning task.
            context: Mutable context snapshot.
            recursion: Current recursion row.
            action_type: Final action type.
            action_output: Enriched action output payload.
            step_status_updates: Validated step status updates.
            summary: Optional user-facing progress summary text.
        """

        if action_type == "RE_PLAN":
            self._replace_plan(task, context, action_output.get("plan", []))

        self._apply_step_status_updates(
            task, context, recursion.trace_id, step_status_updates
        )
        self._link_recursion_to_context(
            context=context,
            task=task,
            recursion=recursion,
            action_type=action_type,
            action_output=action_output,
            step_status_updates=step_status_updates,
            summary=summary,
        )

    def _replace_plan(
        self,
        task: ReactTask,
        context: ReactContext,
        plan_data: Any,
    ) -> None:
        """Replace persisted plan steps and sync the in-memory plan snapshot.

        Args:
            task: Owning task.
            context: Mutable context snapshot.
            plan_data: Raw plan payload from the model.
        """
        delete_stmt = delete(ReactPlanStep).where(
            col(ReactPlanStep.task_id) == task.task_id
        )
        self.db.exec(delete_stmt)  # type: ignore[arg-type]

        new_plan_context: list[dict[str, Any]] = []
        if not isinstance(plan_data, list):
            context.context["plan"] = new_plan_context
            return

        for step_data in plan_data:
            if not isinstance(step_data, dict):
                continue
            general_goal = step_data.get("general_goal", "")
            specific_description = step_data.get("specific_description", "")
            completion_criteria = step_data.get("completion_criteria", "")
            step = ReactPlanStep(
                task_id=task.task_id,
                react_task_id=task.id or 0,
                step_id=step_data.get("step_id", ""),
                general_goal=general_goal,
                specific_description=specific_description,
                completion_criteria=completion_criteria,
                status=step_data.get("status", "pending"),
            )
            self.db.add(step)
            new_plan_context.append(
                {
                    "step_id": step.step_id,
                    "general_goal": general_goal,
                    "specific_description": specific_description,
                    "completion_criteria": completion_criteria,
                    "status": step.status,
                    "recursion_history": [],
                }
            )

        context.context["plan"] = new_plan_context

    def _apply_step_status_updates(
        self,
        task: ReactTask,
        context: ReactContext,
        trace_id: str,
        step_status_updates: list[dict[str, str]],
    ) -> None:
        """Persist plan-step status updates and mirror them into context.

        Args:
            task: Owning task.
            context: Mutable context snapshot.
            trace_id: Current recursion trace ID for logging.
            step_status_updates: Validated step status updates.
        """
        plan_step_rows = self.db.exec(
            select(ReactPlanStep).where(ReactPlanStep.task_id == task.task_id)
        ).all()
        plan_step_by_normalized_id = {
            step.step_id.strip(): step
            for step in plan_step_rows
            if isinstance(step.step_id, str)
        }

        for update in step_status_updates:
            step_id_to_update = update["step_id"]
            status_to_update = update["status"]
            plan_step = plan_step_by_normalized_id.get(step_id_to_update.strip())
            if plan_step is None:
                logger.warning(
                    "Ignoring step_status_update for unknown step_id. "
                    "trace_id=%s, task_id=%s, step_id=%s, status=%s, known_step_ids=%s",
                    trace_id,
                    task.task_id,
                    step_id_to_update,
                    status_to_update,
                    sorted(plan_step_by_normalized_id.keys()),
                )
                continue

            plan_step.status = status_to_update
            plan_step.updated_at = datetime.now(UTC)
            self.db.add(plan_step)

            for plan_step_ctx in context.context.get("plan", []):
                plan_step_ctx_id = plan_step_ctx.get("step_id")
                if (
                    isinstance(plan_step_ctx_id, str)
                    and plan_step_ctx_id.strip() == step_id_to_update.strip()
                ):
                    plan_step_ctx["status"] = status_to_update
                    break

    def _link_recursion_to_context(
        self,
        context: ReactContext,
        task: ReactTask,
        recursion: ReactRecursion,
        action_type: str,
        action_output: dict[str, Any],
        step_status_updates: list[dict[str, str]],
        summary: str,
    ) -> None:
        """Attach the current recursion to the correct branch in the context.

        Args:
            context: Mutable context snapshot.
            task: Owning task.
            recursion: Current recursion row.
            action_type: Final action type.
            action_output: Enriched action output payload.
            step_status_updates: Validated step status updates.
            summary: Optional user-facing progress summary text.
        """
        current_rec_dict = {
            "iteration": task.iteration,
            "trace_id": recursion.trace_id,
            "observe": recursion.observe or "",
            "reason": recursion.reason or "",
            "summary": summary,
            "action": {
                "action_type": action_type,
                "output": action_output,
                "step_status_update": step_status_updates,
            },
        }

        added_to_plan = False
        if recursion.plan_step_id:
            for plan_step in context.context.get("plan", []):
                if plan_step.get("step_id") == recursion.plan_step_id:
                    plan_step["recursion_history"].append(current_rec_dict)
                    added_to_plan = True
                    break

        if not added_to_plan:
            context.recursion_history.append(current_rec_dict)

    def _save_snapshot(
        self,
        task: ReactTask,
        recursion: ReactRecursion,
        context: ReactContext,
    ) -> None:
        """Persist the current context snapshot for the recursion.

        Args:
            task: Owning task.
            recursion: Current recursion row.
            context: Current in-memory context snapshot.
        """
        current_state_json = json.dumps(context.to_dict(), ensure_ascii=False)
        recursion_state = ReactRecursionState(
            trace_id=recursion.trace_id,
            task_id=task.task_id,
            iteration_index=task.iteration,
            current_state=current_state_json,
            created_at=datetime.now(UTC),
        )
        self.db.add(recursion_state)

    def _set_task_status(
        self,
        task: ReactTask,
        status: str,
        *,
        commit: bool = True,
    ) -> None:
        """Persist a task status transition.

        Args:
            task: Task whose status should change.
            status: New task status value.
            commit: Whether to commit immediately.
        """
        task.status = status
        if status != "waiting_input":
            task.pending_user_action_json = None
        task.updated_at = datetime.now(UTC)
        self.db.add(task)
        SessionService(self.db).sync_runtime_status(task.session_id, commit=False)
        if commit:
            self.db.commit()
