"""Runtime-persistence helpers for ReAct task prompt state."""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.models.react import ReactTask
from sqlmodel import Session as DBSession

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TaskRuntimeState:
    """Structured in-memory view of persisted task runtime state.

    Attributes:
        messages: Serialized chat history reused across recursion calls.
        pending_action_result: Action result injected into the next user payload.
        previous_response_id: Provider-specific previous response chain ID.
    """

    messages: list[dict[str, str]]
    pending_action_result: list[dict[str, Any]] | None
    previous_response_id: str | None


class ReactRuntimeService:
    """Encapsulates persistence of task-level runtime prompt state.

    This service exists so the orchestration loop does not need to know how the
    runtime state is serialized on `ReactTask`, while still keeping the current
    schema unchanged until a later schema-cleanup phase.
    """

    def __init__(self, db: DBSession) -> None:
        """Initialize the service with a database session.

        Args:
            db: Database session used to persist task runtime state.
        """
        self.db = db

    def load(self, task: ReactTask) -> TaskRuntimeState:
        """Load the current runtime state from the task row.

        Args:
            task: Task whose runtime state should be loaded.

        Returns:
            A normalized runtime state snapshot.
        """
        return TaskRuntimeState(
            messages=self._load_messages(task),
            pending_action_result=self._load_pending_action_result(task),
            previous_response_id=self._load_previous_response_id(task),
        )

    def initialize(
        self,
        task: ReactTask,
        system_prompt: str,
    ) -> TaskRuntimeState:
        """Ensure the runtime state contains the initial system prompt.

        Args:
            task: Task whose runtime state should be initialized.
            system_prompt: Rendered system prompt for the task.

        Returns:
            The initialized runtime state.
        """
        state = self.load(task)
        if state.messages:
            return state

        state.messages = [{"role": "system", "content": system_prompt}]
        self._persist_state(task, state)
        return state

    def append_user_payload(
        self,
        task: ReactTask,
        payload: dict[str, Any],
    ) -> TaskRuntimeState:
        """Append the per-recursion user payload and persist it.

        Args:
            task: Task whose runtime state should be updated.
            payload: Serializable user payload for the next recursion.

        Returns:
            The updated runtime state.
        """
        state = self.load(task)
        state.messages.append(
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False),
            }
        )
        self._persist_state(task, state)
        return state

    def append_assistant_message(
        self,
        task: ReactTask,
        content: str,
    ) -> TaskRuntimeState:
        """Append the assistant reply to persisted runtime messages.

        Args:
            task: Task whose runtime state should be updated.
            content: Raw assistant content to append.

        Returns:
            The updated runtime state.
        """
        state = self.load(task)
        state.messages.append({"role": "assistant", "content": content})
        self._persist_state(task, state)
        return state

    def rollback_last_user_message(self, task: ReactTask) -> TaskRuntimeState:
        """Drop the most recent user payload when a recursion must be retried.

        Args:
            task: Task whose last user payload should be removed.

        Returns:
            The updated runtime state.
        """
        state = self.load(task)
        if state.messages and state.messages[-1].get("role") == "user":
            state.messages.pop()
            self._persist_state(task, state)
        return state

    def set_next_action_result(
        self,
        task: ReactTask,
        action_result: list[dict[str, Any]] | None,
    ) -> TaskRuntimeState:
        """Persist the action result to inject into the next recursion.

        Args:
            task: Task whose pending action result should be updated.
            action_result: Next action result payload, or `None` to clear it.

        Returns:
            The updated runtime state.
        """
        state = self.load(task)
        state.pending_action_result = action_result
        self._persist_state(task, state)
        return state

    def set_previous_response_id(
        self,
        task: ReactTask,
        response_id: str | None,
    ) -> TaskRuntimeState:
        """Persist the transport-specific previous response chain ID.

        Args:
            task: Task whose cache linkage should be updated.
            response_id: New response ID, or `None` to clear it.

        Returns:
            The updated runtime state.
        """
        state = self.load(task)
        state.previous_response_id = response_id.strip() if response_id else None
        self._persist_state(task, state)
        return state

    def clear(self, task: ReactTask) -> None:
        """Clear all ephemeral runtime state for a finished task.

        Args:
            task: Task whose runtime state should be reset.
        """
        state = TaskRuntimeState(
            messages=[],
            pending_action_result=None,
            previous_response_id=None,
        )
        self._persist_state(task, state)

    def _persist_state(self, task: ReactTask, state: TaskRuntimeState) -> None:
        """Write a normalized runtime state back into `ReactTask`.

        Args:
            task: Task row to update.
            state: Runtime state to serialize.
        """
        task.llm_messages = json.dumps(state.messages, ensure_ascii=False)
        task.pending_action_result = (
            json.dumps(state.pending_action_result, ensure_ascii=False)
            if state.pending_action_result is not None
            else None
        )
        task.llm_cache_state = json.dumps(
            (
                {"previous_response_id": state.previous_response_id}
                if state.previous_response_id
                else {}
            ),
            ensure_ascii=False,
        )
        task.updated_at = datetime.now(timezone.utc)
        self.db.add(task)
        self.db.commit()

    def _load_messages(self, task: ReactTask) -> list[dict[str, str]]:
        """Load persisted runtime messages from the task row.

        Args:
            task: Task whose serialized messages should be loaded.

        Returns:
            A normalized OpenAI-style message list.
        """
        if not task.llm_messages:
            return []

        try:
            raw_messages = json.loads(task.llm_messages)
        except json.JSONDecodeError:
            logger.warning(
                "Invalid llm_messages JSON detected; resetting task messages. task_id=%s",
                task.task_id,
            )
            return []

        if not isinstance(raw_messages, list):
            logger.warning(
                "Invalid llm_messages payload type; expected list. task_id=%s",
                task.task_id,
            )
            return []

        normalized: list[dict[str, str]] = []
        for item in raw_messages:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = item.get("content")
            if (
                isinstance(role, str)
                and role in {"system", "user", "assistant"}
                and isinstance(content, str)
            ):
                normalized.append({"role": role, "content": content})
        return normalized

    def _load_pending_action_result(
        self,
        task: ReactTask,
    ) -> list[dict[str, Any]] | None:
        """Load the pending action result from serialized task state.

        Args:
            task: Task whose pending action result should be loaded.

        Returns:
            Parsed action-result payload, or `None` when absent or invalid.
        """
        if not task.pending_action_result:
            return None

        try:
            payload = json.loads(task.pending_action_result)
        except json.JSONDecodeError:
            logger.warning(
                "Invalid pending_action_result JSON; dropping it. task_id=%s",
                task.task_id,
            )
            return None

        if not isinstance(payload, list):
            return None

        normalized_results: list[dict[str, Any]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            normalized_item: dict[str, Any] = {}
            item_id = item.get("id")
            if isinstance(item_id, str) and item_id:
                normalized_item["id"] = item_id
            if "result" in item:
                normalized_item["result"] = item["result"]
            elif "error" in item:
                normalized_item["error"] = item["error"]
            if normalized_item:
                normalized_results.append(normalized_item)
        return normalized_results

    def _load_previous_response_id(self, task: ReactTask) -> str | None:
        """Load the provider cache linkage ID from serialized task state.

        Args:
            task: Task whose runtime cache state should be loaded.

        Returns:
            The normalized previous response ID, or `None`.
        """
        if not task.llm_cache_state:
            return None

        try:
            payload = json.loads(task.llm_cache_state)
        except json.JSONDecodeError:
            logger.warning(
                "Invalid llm_cache_state JSON detected; resetting. task_id=%s",
                task.task_id,
            )
            return None

        if not isinstance(payload, dict):
            return None

        previous_response_id = payload.get("previous_response_id")
        if isinstance(previous_response_id, str) and previous_response_id.strip():
            return previous_response_id.strip()
        return None
