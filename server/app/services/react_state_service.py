"""Persistence helpers for ReAct recursion and task state."""

from __future__ import annotations

import copy
import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.models.react import (
    ReactRecursion,
    ReactRecursionState,
    ReactTask,
)
from app.services.session_service import SessionService
from sqlmodel import Session as DBSession

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

    def start_recursion(
        self,
        task: ReactTask,
        trace_id: str,
        input_message: dict[str, Any],
    ) -> ReactRecursion:
        """Create and persist a new recursion row.

        Args:
            task: Task that owns the recursion.
            trace_id: Server-generated recursion trace ID.
            input_message: Exact per-recursion user message sent to the LLM.

        Returns:
            The persisted recursion row.
        """
        recursion = ReactRecursion(
            trace_id=trace_id,
            task_id=task.task_id,
            react_task_id=task.id or 0,
            iteration_index=task.iteration,
            input_message_json=json.dumps(input_message, ensure_ascii=False),
            status="running",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.db.add(recursion)
        self.db.commit()
        self.db.refresh(recursion)
        return recursion

    def record_llm_decision(
        self,
        task: ReactTask,
        recursion: ReactRecursion,
        thinking: str | None,
        action_type: str,
        action_output: dict[str, Any],
        message: str,
        token_counter: dict[str, int],
    ) -> dict[str, int] | None:
        """Persist the parsed LLM decision before side effects run.

        Args:
            task: Owning task.
            recursion: Recursion row created for this cycle.
            thinking: Raw provider reasoning content, if available.
            action_type: Final normalized action type.
            action_output: Parsed action output payload before tool results.
            message: User-facing progress note.
            token_counter: Aggregated token usage for the recursion.

        Returns:
            Persisted token usage payload, or `None` if empty.
        """
        raw_action_output = copy.deepcopy(action_output)

        recursion.thinking = thinking
        recursion.action_type = action_type
        recursion.action_output = json.dumps(raw_action_output, ensure_ascii=False)

        if message:
            recursion.message = message

        tokens_data = self._apply_token_usage(task, recursion, token_counter)
        recursion.updated_at = datetime.now(UTC)
        self.db.add(recursion)
        self.db.add(task)
        self.db.commit()
        return tokens_data

    def finalize_success(
        self,
        task: ReactTask,
        recursion: ReactRecursion,
        context: ReactContext,
        action_type: str,
        action_output: dict[str, Any],
        message: str,
        tool_results: list[dict[str, Any]],
        pending_user_action: dict[str, Any] | None = None,
    ) -> None:
        """Persist final side effects for a successful recursion.

        Args:
            task: Owning task.
            recursion: Recursion row created for this cycle.
            context: Mutable in-memory context snapshot for this cycle.
            action_type: Final normalized action type.
            action_output: Mutable action output payload. Tool results may be
                merged into it for snapshot/event consistency.
            message: User-facing progress note.
            tool_results: Executed tool results for this recursion.
            pending_user_action: Optional system-owned waiting action created by
                a tool result and persisted on the task row.
        """

        if tool_results:
            recursion.tool_call_results = json.dumps(tool_results, ensure_ascii=False)

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
            message=message,
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

    def finalize_partial_tool_error(
        self,
        task: ReactTask,
        recursion: ReactRecursion,
        context: ReactContext,
        thinking: str | None,
        action_output: dict[str, Any],
        message: str,
        tool_results: list[dict[str, Any]],
        error_log: str,
        pending_user_action: dict[str, Any] | None = None,
        token_counter: dict[str, int] | None = None,
    ) -> dict[str, int] | None:
        """Persist a failed CALL_TOOL recursion after tools already ran.

        Once a tool starts, the recursion has crossed the side-effect boundary.
        We therefore keep the assistant decision preview, tool results, and parse
        failure as durable facts for the next recursion to recover from.
        """
        raw_action_output = copy.deepcopy(action_output)

        recursion.thinking = thinking
        recursion.action_type = "CALL_TOOL"
        recursion.action_output = json.dumps(raw_action_output, ensure_ascii=False)
        if message:
            recursion.message = message
        if tool_results:
            recursion.tool_call_results = json.dumps(tool_results, ensure_ascii=False)

        tokens_data = self._apply_token_usage(task, recursion, token_counter or {})
        recursion.status = "error"
        recursion.error_log = error_log
        recursion.updated_at = datetime.now(UTC)
        self.db.add(recursion)

        self._merge_tool_results_into_action_output(action_output, tool_results)
        self._sync_context_before_snapshot(
            task=task,
            context=context,
            recursion=recursion,
            action_type="CALL_TOOL",
            action_output=action_output,
            message=message,
        )
        self._save_snapshot(task, recursion, context)
        if pending_user_action is not None:
            task.pending_user_action_json = json.dumps(
                pending_user_action,
                ensure_ascii=False,
            )
            self._set_task_status(task, "waiting_input", commit=False)
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
        message: str,
    ) -> None:
        """Append current recursion summary to the context history.

        Args:
            task: Owning task.
            context: Mutable context snapshot.
            recursion: Current recursion row.
            action_type: Final action type.
            action_output: Enriched action output payload.
            message: User-facing progress note.
        """
        current_rec_dict = {
            "iteration": task.iteration,
            "trace_id": recursion.trace_id,
            "message": message,
            "action": {
                "action_type": action_type,
                "output": action_output,
            },
        }
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
