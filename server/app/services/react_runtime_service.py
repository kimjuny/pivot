"""Runtime-persistence helpers for ReAct task prompt state."""

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.models.react import ReactTask
from app.models.session import Session
from app.orchestration.react.prompt_template import (
    build_runtime_payload_message,
    build_runtime_task_bootstrap_message,
)
from sqlmodel import Session as DBSession, select

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TaskRuntimeState:
    """Structured in-memory view of persisted task runtime state.

    Attributes:
        messages: Serialized chat history reused across recursion calls.
        compact_result: Canonical compact JSON string, if one is active.
        pending_action_result: Action result injected into the next user payload.
        previous_response_id: Provider-specific previous response chain ID.
    """

    messages: list[dict[str, Any]]
    compact_result: str | None
    pending_action_result: list[dict[str, Any]] | None
    previous_response_id: str | None


class ReactRuntimeService:
    """Encapsulates persistence of task-level runtime prompt state.

    This service exists so the orchestration loop does not need to know how the
    runtime state is serialized on `Session`, while still keeping state
    mutations centralized and easy to reason about.
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
        session = self._get_session_or_raise(task)
        return TaskRuntimeState(
            messages=self._load_messages(session),
            compact_result=self._load_compact_result(session),
            pending_action_result=self._load_pending_action_result(session),
            previous_response_id=self._load_previous_response_id(session),
        )

    def load_session(self, session_id: str) -> TaskRuntimeState:
        """Load runtime state directly from a session identifier.

        Args:
            session_id: Session whose runtime state should be loaded.

        Returns:
            A normalized runtime state snapshot.

        Raises:
            RuntimeError: If the session does not exist.
        """
        session = self._get_session_by_id_or_raise(session_id)
        return TaskRuntimeState(
            messages=self._load_messages(session),
            compact_result=self._load_compact_result(session),
            pending_action_result=self._load_pending_action_result(session),
            previous_response_id=self._load_previous_response_id(session),
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
        session = self._get_session_or_raise(task)
        state = self.load(task)
        if state.messages and state.messages[0].get("role") == "system":
            return state

        state.messages = [{"role": "system", "content": system_prompt}, *state.messages]
        self._persist_state(session, state)
        return state

    def append_task_bootstrap_prompt(
        self,
        task: ReactTask,
        user_prompt: str,
    ) -> TaskRuntimeState:
        """Append the task-opening user prompt and persist it.

        Args:
            task: Task whose runtime state should be updated.
            user_prompt: Rendered dynamic user prompt for the new task.

        Returns:
            The updated runtime state.
        """
        state = self.load(task)
        if task.iteration == 0 and task.runtime_message_start_index <= 0:
            task.runtime_message_start_index = len(state.messages)
        state.messages.append(build_runtime_task_bootstrap_message(user_prompt))
        session = self._get_session_or_raise(task)
        self.db.add(task)
        self._persist_state(session, state)
        return state

    def append_user_payload(
        self,
        task: ReactTask,
        payload: dict[str, Any],
        attachments: list[dict[str, Any]] | None = None,
    ) -> TaskRuntimeState:
        """Append the per-recursion user payload and persist it.

        Args:
            task: Task whose runtime state should be updated.
            payload: Serializable user payload for the next recursion.
            attachments: Neutral multimodal content blocks to append after text.

        Returns:
            The updated runtime state.
        """
        state = self.load(task)
        state.messages.append(
            build_runtime_payload_message(payload, attachments=attachments)
        )
        session = self._get_session_or_raise(task)
        self._persist_state(session, state)
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
        session = self._get_session_or_raise(task)
        self._persist_state(session, state)
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
            session = self._get_session_or_raise(task)
            self._persist_state(session, state)
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
        session = self._get_session_or_raise(task)
        self._persist_state(session, state)
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
        session = self._get_session_or_raise(task)
        self._persist_state(session, state)
        return state

    def clear_task_state(
        self,
        task: ReactTask,
        *,
        preserve_cache_state: bool = True,
        rollback_last_user_message: bool = False,
    ) -> TaskRuntimeState:
        """Clear task-local runtime state while preserving session history.

        Args:
            task: Task whose runtime state should be reset.
            preserve_cache_state: Whether provider cache linkage should survive.
            rollback_last_user_message: Whether to drop a dangling trailing user
                message before clearing task-local state.

        Returns:
            The updated runtime state.
        """
        state = self.load(task)
        if (
            rollback_last_user_message
            and state.messages
            and state.messages[-1].get("role") == "user"
        ):
            state.messages.pop()
        state.pending_action_result = None
        if not preserve_cache_state:
            state.previous_response_id = None
        task.stashed_messages = None
        session = self._get_session_or_raise(task)
        self.db.add(task)
        self._persist_state(session, state)
        return state

    def get_incremental_messages(
        self,
        task: ReactTask,
    ) -> list[dict[str, Any]]:
        """Return messages added after the latest assistant reply.

        Args:
            task: Task whose session runtime state should be examined.

        Returns:
            The trailing message slice that still needs to be sent when the
            provider uses previous-response chaining.
        """
        state = self.load(task)
        last_assistant_index = -1
        for index in range(len(state.messages) - 1, -1, -1):
            if state.messages[index].get("role") == "assistant":
                last_assistant_index = index
                break
        return state.messages[last_assistant_index + 1 :]

    def replace_runtime_messages(
        self,
        task: ReactTask,
        messages: list[dict[str, Any]],
        *,
        compact_result: str | None,
        preserve_pending_action_result: bool = True,
        preserve_cache_state: bool = False,
    ) -> TaskRuntimeState:
        """Replace the persisted runtime window after a compact cycle.

        Args:
            task: Task whose session runtime state should be rebuilt.
            messages: Canonical message list to persist.
            compact_result: Latest compact JSON inserted into the runtime window.
            preserve_pending_action_result: Whether to keep the pending action
                result that feeds the next user payload.
            preserve_cache_state: Whether previous-response chaining should
                remain active after the rebuild.

        Returns:
            The updated runtime state.
        """
        state = self.load(task)
        state.messages = [dict(message) for message in messages]
        state.compact_result = compact_result
        if not preserve_pending_action_result:
            state.pending_action_result = None
        if not preserve_cache_state:
            state.previous_response_id = None
        session = self._get_session_or_raise(task)
        self._persist_state(session, state)
        return state

    def stash_task_messages(
        self,
        task: ReactTask,
        messages: list[dict[str, Any]],
    ) -> None:
        """Persist task-local runtime messages for mid-task compaction."""
        task.stashed_messages = json.dumps(messages, ensure_ascii=False)
        task.updated_at = datetime.now(UTC)
        self.db.add(task)
        self.db.commit()

    def load_stashed_task_messages(self, task: ReactTask) -> list[dict[str, Any]]:
        """Load previously stashed task-local runtime messages."""
        if not task.stashed_messages:
            return []

        try:
            payload = json.loads(task.stashed_messages)
        except json.JSONDecodeError:
            logger.warning(
                "Invalid stashed_messages JSON; dropping it. task_id=%s",
                task.task_id,
            )
            return []
        return self._normalize_messages(payload)

    def clear_stashed_task_messages(self, task: ReactTask) -> None:
        """Remove persisted stashed runtime messages from a task row."""
        task.stashed_messages = None
        task.updated_at = datetime.now(UTC)
        self.db.add(task)
        self.db.commit()

    def build_session_context_payload(self, session_id: str) -> dict[str, Any]:
        """Build compact-aware session context for skill selection."""
        session = self._get_session_by_id_or_raise(session_id)
        compact_result = self._load_compact_result(session)
        runtime_messages = [
            dict(message)
            for message in self._load_messages(session)
            if message.get("role") != "system"
        ]
        payload: dict[str, Any] = {"runtime_messages": runtime_messages}
        if compact_result:
            try:
                payload["compact_result"] = json.loads(compact_result)
            except json.JSONDecodeError:
                payload["compact_result"] = compact_result
        else:
            payload["compact_result"] = None
        return payload

    def build_runtime_debug_payload(self, session_id: str) -> dict[str, Any]:
        """Build a debug-friendly snapshot of one session runtime window.

        Args:
            session_id: Session whose persisted runtime state should be inspected.

        Returns:
            Dictionary containing runtime-message counts, roles, and compact data.
        """
        session = self._get_session_by_id_or_raise(session_id)
        messages = self._load_messages(session)
        compact_result_raw = self._load_compact_result(session)
        compact_result: Any | None = None
        if compact_result_raw:
            try:
                compact_result = json.loads(compact_result_raw)
            except json.JSONDecodeError:
                compact_result = compact_result_raw

        return {
            "session_id": session.session_id,
            "runtime_message_count": len(messages),
            "runtime_message_roles": [
                str(message.get("role", "unknown")) for message in messages
            ],
            "has_compact_result": compact_result_raw is not None,
            "compact_result": compact_result,
            "compact_result_raw": compact_result_raw,
            "updated_at": session.updated_at.replace(tzinfo=UTC).isoformat(),
        }

    def _persist_state(self, session: Session, state: TaskRuntimeState) -> None:
        """Write a normalized runtime state back into ``Session``.

        Args:
            session: Session row to update.
            state: Runtime state to serialize.
        """
        session.react_llm_messages = json.dumps(state.messages, ensure_ascii=False)
        session.react_compact_result = state.compact_result
        session.react_pending_action_result = (
            json.dumps(state.pending_action_result, ensure_ascii=False)
            if state.pending_action_result is not None
            else None
        )
        session.react_llm_cache_state = json.dumps(
            (
                {"previous_response_id": state.previous_response_id}
                if state.previous_response_id
                else {}
            ),
            ensure_ascii=False,
        )
        session.updated_at = datetime.now(UTC)
        self.db.add(session)
        self.db.commit()

    def _load_messages(self, session: Session) -> list[dict[str, Any]]:
        """Load persisted runtime messages from the session row.

        Args:
            session: Session whose serialized messages should be loaded.

        Returns:
            A normalized OpenAI-style message list.
        """
        if not session.react_llm_messages:
            return []

        try:
            raw_messages = json.loads(session.react_llm_messages)
        except json.JSONDecodeError:
            logger.warning(
                "Invalid react_llm_messages JSON detected; resetting session messages. session_id=%s",
                session.session_id,
            )
            return []

        if not isinstance(raw_messages, list):
            logger.warning(
                "Invalid react_llm_messages payload type; expected list. session_id=%s",
                session.session_id,
            )
            return []

        return self._normalize_messages(raw_messages)

    def _load_compact_result(self, session: Session) -> str | None:
        """Load the latest compact JSON string from the session row."""
        raw_value = session.react_compact_result
        if not isinstance(raw_value, str):
            return None
        compact_result = raw_value.strip()
        return compact_result or None

    def _load_pending_action_result(
        self,
        session: Session,
    ) -> list[dict[str, Any]] | None:
        """Load the pending action result from serialized session state.

        Args:
            session: Session whose pending action result should be loaded.

        Returns:
            Parsed action-result payload, or `None` when absent or invalid.
        """
        if not session.react_pending_action_result:
            return None

        try:
            payload = json.loads(session.react_pending_action_result)
        except json.JSONDecodeError:
            logger.warning(
                "Invalid react_pending_action_result JSON; dropping it. session_id=%s",
                session.session_id,
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

    def _load_previous_response_id(self, session: Session) -> str | None:
        """Load the provider cache linkage ID from serialized session state.

        Args:
            session: Session whose runtime cache state should be loaded.

        Returns:
            The normalized previous response ID, or `None`.
        """
        if not session.react_llm_cache_state:
            return None

        try:
            payload = json.loads(session.react_llm_cache_state)
        except json.JSONDecodeError:
            logger.warning(
                "Invalid react_llm_cache_state JSON detected; resetting. session_id=%s",
                session.session_id,
            )
            return None

        if not isinstance(payload, dict):
            return None

        previous_response_id = payload.get("previous_response_id")
        if isinstance(previous_response_id, str) and previous_response_id.strip():
            return previous_response_id.strip()
        return None

    @staticmethod
    def _normalize_messages(raw_messages: Any) -> list[dict[str, Any]]:
        """Normalize serialized messages into the accepted runtime shape."""
        if not isinstance(raw_messages, list):
            return []

        normalized: list[dict[str, Any]] = []
        for item in raw_messages:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = item.get("content")
            if (
                isinstance(role, str)
                and role in {"system", "user", "assistant"}
                and (
                    isinstance(content, str)
                    or (
                        isinstance(content, list)
                        and all(isinstance(block, dict) for block in content)
                    )
                )
            ):
                normalized.append({"role": role, "content": content})
        return normalized

    def _get_session_or_raise(self, task: ReactTask) -> Session:
        """Resolve the owning session row for one task.

        Args:
            task: Task whose session runtime state should be mutated.

        Returns:
            The owning session row.

        Raises:
            RuntimeError: If the task does not have a valid session.
        """
        if not task.session_id:
            raise RuntimeError(
                f"Task {task.task_id} does not have a session_id required for ReAct runtime state."
            )

        return self._get_session_by_id_or_raise(task.session_id)

    def _get_session_by_id_or_raise(self, session_id: str) -> Session:
        """Resolve one session row by its public session identifier.

        Args:
            session_id: Public session UUID string.

        Returns:
            The owning session row.

        Raises:
            RuntimeError: If the session does not exist.
        """
        statement = select(Session).where(Session.session_id == session_id)
        session = self.db.exec(statement).first()
        if session is None:
            raise RuntimeError(f"Session {session_id} not found.")
        return session
