"""Session Memory Service for managing session-level memory.

This service handles all CRUD operations for session memory,
including applying deltas from LLM responses and managing
the persistent session state.
"""

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.models.react import (
    ReactPlanStep,
    ReactRecursionState,
    ReactTask,
    ReactTaskEvent,
)
from app.models.session import Session, SessionMemory
from app.schemas.file import FileAssetListItem
from app.services.file_service import FileService
from sqlmodel import Session as DBSession, col, select

logger = logging.getLogger(__name__)

SESSION_IDLE_TIMEOUT = timedelta(minutes=15)
SESSION_METADATA_UNSET = object()


class SessionMemoryService:
    """Service class for session memory operations.

    Handles creation, retrieval, updates, and delta application
    for session memory across the ReAct agent system.
    """

    def __init__(self, db: DBSession) -> None:
        """Initialize the service with a database session.

        Args:
            db: Database session for persistence operations.
        """
        self.db = db

    def create_session(
        self,
        agent_id: int,
        user: str,
    ) -> Session:
        """Create a new session with empty memory.

        Args:
            agent_id: ID of the agent for this session.
            user: Username of the session owner.

        Returns:
            Created Session instance.
        """
        session_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        # Create session
        session = Session(
            session_id=session_id,
            agent_id=agent_id,
            user=user,
            status="active",
            title=None,
            is_pinned=False,
            chat_history=json.dumps({"version": 1, "messages": []}),
            react_llm_messages="[]",
            react_pending_action_result=None,
            react_llm_cache_state="{}",
            created_at=now,
            updated_at=now,
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)

        # Create associated session memory
        memory = SessionMemory(
            session_id=session_id,
            session_db_id=session.id or 0,
            memory_items="[]",
            conversations="[]",
            created_at=now,
            updated_at=now,
        )
        self.db.add(memory)
        self.db.commit()

        return session

    def get_session(self, session_id: str) -> Session | None:
        """Get a session by session_id.

        Args:
            session_id: UUID of the session.

        Returns:
            Session instance or None if not found.
        """
        stmt = select(Session).where(Session.session_id == session_id)
        return self.db.exec(stmt).first()

    def has_session_exceeded_idle_timeout(
        self,
        session: Session,
        *,
        now: datetime | None = None,
    ) -> bool:
        """Return whether a session has been idle beyond the reuse threshold.

        Args:
            session: Session row whose last activity should be evaluated.
            now: Optional comparison timestamp for deterministic tests.

        Returns:
            ``True`` when the session should no longer be reused.
        """
        reference_now = now or datetime.now(UTC)
        updated_at = (
            session.updated_at
            if session.updated_at.tzinfo is not None
            else session.updated_at.replace(tzinfo=UTC)
        )
        return reference_now - updated_at > SESSION_IDLE_TIMEOUT

    def get_session_memory(self, session_id: str) -> SessionMemory | None:
        """Get session memory by session_id.

        Args:
            session_id: UUID of the session.

        Returns:
            SessionMemory instance or None if not found.
        """
        stmt = select(SessionMemory).where(SessionMemory.session_id == session_id)
        return self.db.exec(stmt).first()

    def get_sessions_by_user(
        self,
        user: str,
        agent_id: int | None = None,
        limit: int = 50,
    ) -> list[Session]:
        """Get all sessions for a user, optionally filtered by agent.

        Args:
            user: Username to filter by.
            agent_id: Optional agent ID to filter by.
            limit: Maximum number of sessions to return.

        Returns:
            List of Session instances.
        """
        stmt = select(Session).where(Session.user == user)
        if agent_id is not None:
            stmt = stmt.where(Session.agent_id == agent_id)
        stmt = stmt.order_by(
            col(Session.is_pinned).desc(),
            col(Session.updated_at).desc(),
        ).limit(limit)
        return list(self.db.exec(stmt).all())

    def update_session_metadata(
        self,
        session_id: str,
        *,
        title: str | None | object = SESSION_METADATA_UNSET,
        is_pinned: bool | object = SESSION_METADATA_UNSET,
    ) -> Session | None:
        """Update user-managed sidebar metadata for one session.

        Args:
            session_id: UUID of the session.
            title: Optional explicit title. ``None`` clears the custom title.
            is_pinned: Optional pin state toggle.

        Returns:
            Updated session row, or ``None`` when the session does not exist.
        """
        session = self.get_session(session_id)
        if session is None:
            return None

        has_changes = False
        if title is not SESSION_METADATA_UNSET:
            next_title = title.strip() if isinstance(title, str) else None
            if session.title != (next_title or None):
                session.title = next_title or None
                has_changes = True

        if (
            is_pinned is not SESSION_METADATA_UNSET
            and session.is_pinned != is_pinned
        ):
            session.is_pinned = bool(is_pinned)
            has_changes = True

        if has_changes:
            self.db.add(session)
            self.db.commit()
            self.db.refresh(session)

        return session

    def get_full_session_memory_dict(self, session_id: str) -> dict[str, Any]:
        """Get the complete session memory as a dictionary.

        This returns the full session_memory structure as described
        in context_template.md section 8.2.

        Args:
            session_id: UUID of the session.

        Returns:
            Dictionary containing the complete session memory structure.
        """
        session = self.get_session(session_id)
        memory = self.get_session_memory(session_id)

        if not session or not memory:
            return {}

        # Parse stored data
        try:
            memory_items = json.loads(memory.memory_items)
        except json.JSONDecodeError:
            memory_items = []

        try:
            conversations = json.loads(memory.conversations)
        except json.JSONDecodeError:
            conversations = []

        # Parse subject and object from session
        try:
            subject = json.loads(session.subject) if session.subject else None
        except json.JSONDecodeError:
            subject = None

        try:
            object_data = json.loads(session.object) if session.object else None
        except json.JSONDecodeError:
            object_data = None

        return {
            "session_id": session.session_id,
            "subject": subject,
            "object": object_data,
            "status": session.status,
            "artifacts_metadata": {},  # Reserved for future use
            "conversations": conversations,
            "session_memory": memory_items,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
        }

    def process_answer_updates(
        self,
        session_id: str,
        task: ReactTask,
        session_memory_delta: dict[str, Any] | None = None,
        session_subject: dict[str, Any] | None = None,
        session_goal: dict[str, Any] | None = None,
        agent_answer: str | None = None,
        task_summary: dict[str, Any] | None = None,
    ) -> bool:
        """Process all session updates from an ANSWER action in a single transaction.

        This consolidates memory delta, subject/object updates, conversation logging,
        and chat history appending into one database operation.

        Args:
            session_id: UUID of the session.
            task: The completed ReactTask.
            session_memory_delta: Dictionary with add/update/delete memory operations.
            session_subject: Optional updated subject.
            session_goal: Optional updated goal.
            agent_answer: The final agent response content.
            task_summary: Summary dictionary of the task execution.

        Returns:
            True if successful, False otherwise.
        """
        session = self.get_session(session_id)
        memory = self.get_session_memory(session_id)

        if not session or not memory:
            logger.warning(f"Session or memory not found for session_id: {session_id}")
            return False

        now = datetime.now(UTC)
        memory_updated = False
        session_updated = False

        # 1. Process Memory Deltas
        if session_memory_delta:
            try:
                memory_items = json.loads(memory.memory_items)
            except json.JSONDecodeError:
                memory_items = []

            max_id = 0
            for item in memory_items:
                if "id" in item and isinstance(item["id"], int):
                    max_id = max(max_id, item["id"])

            for add_item in session_memory_delta.get("add", []):
                max_id += 1
                memory_items.append(self._build_memory_item(add_item, max_id))

            for update_item in session_memory_delta.get("update", []):
                item_id = update_item.get("id")
                if item_id is not None:
                    for i, existing in enumerate(memory_items):
                        if existing.get("id") == item_id:
                            memory_items[i] = self._build_memory_item(
                                update_item, item_id
                            )
                            break

            delete_ids = {
                d.get("id")
                for d in session_memory_delta.get("delete", [])
                if d.get("id")
            }
            if delete_ids:
                memory_items = [
                    item for item in memory_items if item.get("id") not in delete_ids
                ]

            memory.memory_items = json.dumps(memory_items, ensure_ascii=False)
            memory_updated = True

        # 2. Process Conversation Record
        try:
            conversations = json.loads(memory.conversations)
        except json.JSONDecodeError:
            conversations = []

        task_index = len(conversations) + 1
        conversations.append(
            {
                "task_index": task_index,
                "task_id": task.task_id,
                "user_input": task.user_message,
                "final_answer": agent_answer or "",
                "status": task.status,
                "summary": task_summary,
            }
        )
        memory.conversations = json.dumps(conversations, ensure_ascii=False)
        memory_updated = True

        if memory_updated:
            memory.updated_at = now

        # 3. Process Session Subject & Object
        if session_subject:
            session.subject = json.dumps(session_subject, ensure_ascii=False)
            session_updated = True

        if session_goal:
            session.object = json.dumps(session_goal, ensure_ascii=False)
            session_updated = True

        # 4. Process Chat History
        if agent_answer:
            try:
                history = json.loads(
                    session.chat_history or '{"version": 1, "messages": []}'
                )
            except json.JSONDecodeError:
                history = {"version": 1, "messages": []}

            if "messages" not in history:
                history["messages"] = []

            history["messages"].append(
                {
                    "type": "assistant",
                    "content": agent_answer,
                    "timestamp": now.isoformat(),
                }
            )
            session.chat_history = json.dumps(history, ensure_ascii=False)
            session_updated = True

        if session_updated:
            session.updated_at = now

        # Fast single commit for everything
        if memory_updated or session_updated:
            self.db.commit()

        return True

    def apply_memory_delta(
        self,
        session_id: str,
        delta: dict[str, Any],
    ) -> bool:
        """Apply session memory delta from LLM ANSWER action.

        This method handles the session_memory_delta structure from
        context_template.md section 4.6, including add, update, delete
        operations on memory items.

        Args:
            session_id: UUID of the session.
            delta: Dictionary containing add, update, delete operations.

        Returns:
            True if successful, False otherwise.
        """
        memory = self.get_session_memory(session_id)
        if not memory:
            logger.warning(f"Session memory not found for session_id: {session_id}")
            return False

        try:
            memory_items = json.loads(memory.memory_items)
        except json.JSONDecodeError:
            memory_items = []

        # Get current max ID for new items
        max_id = 0
        for item in memory_items:
            if "id" in item and isinstance(item["id"], int):
                max_id = max(max_id, item["id"])

        # Process additions
        for add_item in delta.get("add", []):
            max_id += 1
            new_item = self._build_memory_item(add_item, max_id)
            memory_items.append(new_item)

        # Process updates
        for update_item in delta.get("update", []):
            item_id = update_item.get("id")
            if item_id is None:
                continue

            for i, existing in enumerate(memory_items):
                if existing.get("id") == item_id:
                    updated = self._build_memory_item(update_item, item_id)
                    memory_items[i] = updated
                    break

        # Process deletions
        delete_ids = {d.get("id") for d in delta.get("delete", []) if d.get("id")}
        memory_items = [
            item for item in memory_items if item.get("id") not in delete_ids
        ]

        # Save updated memory
        memory.memory_items = json.dumps(memory_items, ensure_ascii=False)
        memory.updated_at = datetime.now(UTC)
        self.db.commit()

        return True

    def _build_memory_item(
        self,
        data: dict[str, Any],
        item_id: int,
    ) -> dict[str, Any]:
        """Build a memory item dictionary from delta data.

        Args:
            data: Raw data from delta.
            item_id: ID to assign to the item.

        Returns:
            Properly formatted memory item dictionary.
        """
        item: dict[str, Any] = {
            "id": item_id,
            "type": data.get("type", "background"),
            "content": data.get("content", ""),
            "confidence": data.get("confidence", 0.5),
        }

        # Add type-specific fields
        if data.get("type") == "decision":
            item["source"] = data.get("source", "agent")
            item["decision"] = data.get("decision", "")
            item["rationale"] = data.get("rationale", "")
            item["scope"] = data.get("scope", "session")
            item["reversible"] = data.get("reversible", True)

        return item

    def update_subject(
        self,
        session_id: str,
        subject: dict[str, Any],
    ) -> bool:
        """Update session subject.

        Args:
            session_id: UUID of the session.
            subject: Dictionary with content, source, confidence.

        Returns:
            True if successful, False otherwise.
        """
        session = self.get_session(session_id)
        if not session:
            return False

        session.subject = json.dumps(subject, ensure_ascii=False)
        session.updated_at = datetime.now(UTC)
        self.db.commit()
        return True

    def update_goal(
        self,
        session_id: str,
        goal_data: dict[str, Any],
    ) -> bool:
        """Update session goal (purpose).

        Args:
            session_id: UUID of the session.
            goal_data: Dictionary with content, source, confidence.

        Returns:
            True if successful, False otherwise.
        """
        session = self.get_session(session_id)
        if not session:
            return False

        session.object = json.dumps(goal_data, ensure_ascii=False)
        session.updated_at = datetime.now(UTC)
        self.db.commit()
        return True

    def add_conversation(
        self,
        session_id: str,
        task: ReactTask,
        agent_answer: str | None = None,
        task_summary: dict[str, Any] | None = None,
    ) -> bool:
        """Add a conversation entry to the session.

        This is called when a task completes to record the conversation
        summary in the session memory.

        Args:
            session_id: UUID of the session.
            task: The completed ReactTask.
            agent_answer: Final answer from the agent.
            task_summary: Summary dictionary with content, key_findings, final_decisions.

        Returns:
            True if successful, False otherwise.
        """
        memory = self.get_session_memory(session_id)
        if not memory:
            return False

        try:
            conversations = json.loads(memory.conversations)
        except json.JSONDecodeError:
            conversations = []

        # Determine task_index (1-based)
        task_index = len(conversations) + 1

        conversation: dict[str, Any] = {
            "task_index": task_index,
            "task_id": task.task_id,
            "user_input": task.user_message,
            "final_answer": agent_answer or "",
            "status": task.status,
            "summary": task_summary,
        }

        conversations.append(conversation)

        memory.conversations = json.dumps(conversations, ensure_ascii=False)
        memory.updated_at = datetime.now(UTC)
        self.db.commit()
        return True

    def update_chat_history(
        self,
        session_id: str,
        message_type: str,
        content: str,
        files: list[FileAssetListItem] | None = None,
    ) -> bool:
        """Update chat history with a new message.

        Args:
            session_id: UUID of the session.
            message_type: Type of message ('user', 'assistant', 'recursion').
            content: Message content.

        Returns:
            True if successful, False otherwise.
        """
        session = self.get_session(session_id)
        if not session:
            return False

        try:
            history = json.loads(
                session.chat_history or '{"version": 1, "messages": []}'
            )
        except json.JSONDecodeError:
            history = {"version": 1, "messages": []}

        if "messages" not in history:
            history["messages"] = []

        history["messages"].append(
            {
                "type": message_type,
                "content": content,
                "timestamp": datetime.now(UTC).isoformat(),
                "files": [item.dict() for item in files or []],
            }
        )

        session.chat_history = json.dumps(history, ensure_ascii=False)
        session.updated_at = datetime.now(UTC)
        self.db.commit()
        return True

    def get_chat_history(self, session_id: str) -> list[dict[str, Any]]:
        """Get chat history for a session.

        Args:
            session_id: UUID of the session.

        Returns:
            List of chat messages.
        """
        session = self.get_session(session_id)
        if not session or not session.chat_history:
            return []

        try:
            history = json.loads(session.chat_history)
            return history.get("messages", [])
        except json.JSONDecodeError:
            return []

    def update_session_status(
        self,
        session_id: str,
        status: str,
    ) -> bool:
        """Update session status.

        Args:
            session_id: UUID of the session.
            status: New status value.

        Returns:
            True if successful, False otherwise.
        """
        session = self.get_session(session_id)
        if not session:
            return False

        session.status = status
        session.updated_at = datetime.now(UTC)
        self.db.commit()
        return True

    def delete_session(self, session_id: str) -> bool:
        """Delete a session and its associated data.

        Args:
            session_id: UUID of the session.

        Returns:
            True if successful, False otherwise.
        """
        session = self.get_session(session_id)
        if not session:
            return False

        FileService(self.db).clear_files_by_session_id(session_id)

        # First delete the associated SessionMemory to avoid foreign key constraint
        memory = self.get_session_memory(session_id)
        if memory:
            self.db.delete(memory)

        # Then delete the session
        self.db.delete(session)
        self.db.commit()
        return True

    def get_full_session_history(self, session_id: str) -> list[dict[str, Any]]:
        """Get full session history with recursion details.

        This method fetches all ReactTasks for a session with their
        recursion details for displaying complete conversation history.

        Args:
            session_id: UUID of the session.

        Returns:
            List of task dictionaries with recursion details.
        """
        from app.models.react import ReactRecursion

        # Get all tasks for this session, ordered by creation time
        stmt = (
            select(ReactTask)
            .where(ReactTask.session_id == session_id)
            .order_by(col(ReactTask.created_at).asc())
        )
        tasks = list(self.db.exec(stmt).all())
        file_history = FileService(self.db).build_history_items(
            [task.task_id for task in tasks]
        )
        current_plan_by_task = self._load_current_plan_by_task(tasks)

        result = []
        for task in tasks:
            skill_selection_result: dict[str, Any] | None = None
            if task.skill_selection_result:
                try:
                    parsed_skill_selection = json.loads(task.skill_selection_result)
                    if isinstance(parsed_skill_selection, dict):
                        skill_selection_result = parsed_skill_selection
                except json.JSONDecodeError:
                    skill_selection_result = None

            # Get recursions for this task
            recursion_stmt = (
                select(ReactRecursion)
                .where(ReactRecursion.task_id == task.task_id)
                .order_by(col(ReactRecursion.iteration_index).asc())
            )
            recursions = list(self.db.exec(recursion_stmt).all())

            # Build recursion list
            recursion_list = []
            for recursion in recursions:
                recursion_list.append(
                    {
                        "iteration": recursion.iteration_index,
                        "trace_id": recursion.trace_id,
                        "observe": recursion.observe,
                        "thinking": recursion.thinking,
                        "thought": recursion.thought,
                        "abstract": recursion.abstract,
                        "summary": recursion.summary,
                        "action_type": recursion.action_type,
                        "action_output": recursion.action_output,
                        "tool_call_results": recursion.tool_call_results,
                        "status": recursion.status,
                        "error_log": recursion.error_log,
                        "prompt_tokens": recursion.prompt_tokens,
                        "completion_tokens": recursion.completion_tokens,
                        "total_tokens": recursion.total_tokens,
                        "cached_input_tokens": recursion.cached_input_tokens,
                        "created_at": recursion.created_at,
                        "updated_at": recursion.updated_at,
                    }
                )

            # Extract agent answer from the last recursion with ANSWER action
            agent_answer = None
            for recursion in reversed(recursions):
                if recursion.action_type == "ANSWER" and recursion.action_output:
                    try:
                        output = json.loads(recursion.action_output)
                        agent_answer = output.get("answer")
                        if agent_answer:
                            break
                    except json.JSONDecodeError:
                        pass

            result.append(
                {
                    "task_id": task.task_id,
                    "user_message": task.user_message,
                    "files": file_history.get(task.task_id, []),
                    "agent_answer": agent_answer,
                    "status": task.status,
                    "total_tokens": task.total_tokens,
                    "skill_selection_result": skill_selection_result,
                    "current_plan": current_plan_by_task.get(task.task_id, []),
                    "recursions": recursion_list,
                    "created_at": task.created_at,
                    "updated_at": task.updated_at,
                }
            )

        return result

    def get_last_task_event_id(self, session_id: str) -> int:
        """Return the latest persisted task-event cursor for a session.

        Args:
            session_id: Session UUID whose event cursor should be inspected.

        Returns:
            The latest event primary key, or ``0`` when none exist yet.
        """
        statement = (
            select(ReactTaskEvent)
            .where(ReactTaskEvent.session_id == session_id)
            .order_by(col(ReactTaskEvent.id).desc())
        )
        event = self.db.exec(statement).first()
        return int(event.id or 0) if event is not None else 0

    def get_resume_from_task_event_id(self, session_id: str) -> int:
        """Return the reconnect cursor that safely replays active task events.

        Why: full-history cannot include in-flight recursion fields such as
        ``abstract`` or ``summary`` until that recursion is finalized, so a
        reconnecting observer must replay active-task events from the event log.

        Args:
            session_id: Session UUID whose reconnect cursor should be derived.

        Returns:
            The event cursor after which reconnecting observers should subscribe.
        """
        tasks_statement = (
            select(ReactTask)
            .where(ReactTask.session_id == session_id)
            .where(col(ReactTask.status).in_(["pending", "running"]))
            .order_by(col(ReactTask.created_at).asc())
        )
        active_tasks = list(self.db.exec(tasks_statement).all())
        if not active_tasks:
            return self.get_last_task_event_id(session_id)

        task_ids = [task.task_id for task in active_tasks]
        event_statement = (
            select(ReactTaskEvent)
            .where(ReactTaskEvent.session_id == session_id)
            .where(col(ReactTaskEvent.task_id).in_(task_ids))
            .order_by(col(ReactTaskEvent.id).asc())
        )
        first_active_event = self.db.exec(event_statement).first()
        if first_active_event is None or first_active_event.id is None:
            return self.get_last_task_event_id(session_id)
        return max(first_active_event.id - 1, 0)

    def _load_current_plan_by_task(
        self,
        tasks: list[ReactTask],
    ) -> dict[str, list[dict[str, Any]]]:
        """Load the latest persisted current-plan snapshot for each task.

        Args:
            tasks: Tasks whose latest visible current-plan should be returned.

        Returns:
            Mapping from task_id to the normalized current-plan payload.
        """
        task_ids = [task.task_id for task in tasks]
        if not task_ids:
            return {}

        state_stmt = (
            select(ReactRecursionState)
            .where(col(ReactRecursionState.task_id).in_(task_ids))
            .order_by(
                col(ReactRecursionState.task_id).asc(),
                col(ReactRecursionState.iteration_index).desc(),
            )
        )
        states = list(self.db.exec(state_stmt).all())

        current_plan_by_task: dict[str, list[dict[str, Any]]] = {}
        for state in states:
            if state.task_id in current_plan_by_task:
                continue

            normalized_plan = self._extract_current_plan_from_snapshot(
                state.current_state
            )
            if normalized_plan:
                current_plan_by_task[state.task_id] = normalized_plan

        missing_task_ids = [
            task_id for task_id in task_ids if task_id not in current_plan_by_task
        ]
        if not missing_task_ids:
            return current_plan_by_task

        fallback_stmt = (
            select(ReactPlanStep)
            .where(col(ReactPlanStep.task_id).in_(missing_task_ids))
            .order_by(
                col(ReactPlanStep.task_id).asc(),
                col(ReactPlanStep.created_at).asc(),
            )
        )
        fallback_steps = list(self.db.exec(fallback_stmt).all())
        for step in fallback_steps:
            current_plan_by_task.setdefault(step.task_id, []).append(
                {
                    "step_id": step.step_id,
                    "general_goal": step.general_goal,
                    "specific_description": step.specific_description,
                    "completion_criteria": step.completion_criteria,
                    "status": step.status,
                    "recursion_history": [],
                }
            )

        return current_plan_by_task

    def _extract_current_plan_from_snapshot(
        self,
        snapshot_payload: str,
    ) -> list[dict[str, Any]]:
        """Extract the compact current-plan shape from one persisted snapshot.

        Args:
            snapshot_payload: Serialized React current-state JSON payload.

        Returns:
            Normalized current-plan entries, or an empty list when unavailable.
        """
        try:
            parsed_snapshot = json.loads(snapshot_payload)
        except json.JSONDecodeError:
            return []

        if not isinstance(parsed_snapshot, dict):
            return []

        raw_context = parsed_snapshot.get("context")
        if not isinstance(raw_context, dict):
            return []

        return self._normalize_current_plan(raw_context.get("plan"))

    def _normalize_current_plan(self, raw_plan: Any) -> list[dict[str, Any]]:
        """Normalize raw snapshot plan data into a stable API payload.

        Args:
            raw_plan: Untrusted plan payload extracted from persisted state.

        Returns:
            Sanitized current-plan entries ready for API serialization.
        """
        if not isinstance(raw_plan, list):
            return []

        normalized_plan: list[dict[str, Any]] = []
        for step in raw_plan:
            if not isinstance(step, dict):
                continue

            step_id = step.get("step_id")
            if not isinstance(step_id, str) or not step_id:
                continue

            recursion_history: list[dict[str, Any]] = []
            raw_history = step.get("recursion_history")
            if isinstance(raw_history, list):
                for history_item in raw_history:
                    if not isinstance(history_item, dict):
                        continue

                    iteration = history_item.get("iteration")
                    summary = history_item.get("summary", "")
                    recursion_history.append(
                        {
                            "iteration": iteration
                            if isinstance(iteration, int)
                            else None,
                            "summary": summary if isinstance(summary, str) else "",
                        }
                    )

            normalized_plan.append(
                {
                    "step_id": step_id,
                    "general_goal": (
                        step.get("general_goal")
                        if isinstance(step.get("general_goal"), str)
                        else ""
                    ),
                    "specific_description": (
                        step.get("specific_description")
                        if isinstance(step.get("specific_description"), str)
                        else ""
                    ),
                    "completion_criteria": (
                        step.get("completion_criteria")
                        if isinstance(step.get("completion_criteria"), str)
                        else ""
                    ),
                    "status": (
                        step.get("status")
                        if isinstance(step.get("status"), str)
                        else "pending"
                    ),
                    "recursion_history": recursion_history,
                }
            )

        return normalized_plan
