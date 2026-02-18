"""Session Memory Service for managing session-level memory.

This service handles all CRUD operations for session memory,
including applying deltas from LLM responses and managing
the persistent session state.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.models.react import ReactTask
from app.models.session import Session, SessionMemory
from sqlmodel import Session as DBSession, col, select

logger = logging.getLogger(__name__)


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
        now = datetime.now(timezone.utc)

        # Create session
        session = Session(
            session_id=session_id,
            agent_id=agent_id,
            user=user,
            status="active",
            chat_history=json.dumps({"version": 1, "messages": []}),
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
        stmt = stmt.order_by(col(Session.updated_at).desc()).limit(limit)
        return list(self.db.exec(stmt).all())

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
        memory_items = [item for item in memory_items if item.get("id") not in delete_ids]

        # Save updated memory
        memory.memory_items = json.dumps(memory_items, ensure_ascii=False)
        memory.updated_at = datetime.now(timezone.utc)
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
        session.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        return True

    def update_object(
        self,
        session_id: str,
        object_data: dict[str, Any],
    ) -> bool:
        """Update session object (purpose).

        Args:
            session_id: UUID of the session.
            object_data: Dictionary with content, source, confidence.

        Returns:
            True if successful, False otherwise.
        """
        session = self.get_session(session_id)
        if not session:
            return False

        session.object = json.dumps(object_data, ensure_ascii=False)
        session.updated_at = datetime.now(timezone.utc)
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
            "agent_answer": agent_answer or "",
            "status": task.status,
            "summary": task_summary,
        }

        conversations.append(conversation)

        memory.conversations = json.dumps(conversations, ensure_ascii=False)
        memory.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        return True

    def update_chat_history(
        self,
        session_id: str,
        message_type: str,
        content: str,
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
            history = json.loads(session.chat_history or '{"version": 1, "messages": []}')
        except json.JSONDecodeError:
            history = {"version": 1, "messages": []}

        if "messages" not in history:
            history["messages"] = []

        history["messages"].append({
            "type": message_type,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        session.chat_history = json.dumps(history, ensure_ascii=False)
        session.updated_at = datetime.now(timezone.utc)
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
        session.updated_at = datetime.now(timezone.utc)
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

        result = []
        for task in tasks:
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
                recursion_list.append({
                    "iteration": recursion.iteration_index,
                    "trace_id": recursion.trace_id,
                    "observe": recursion.observe,
                    "thought": recursion.thought,
                    "abstract": recursion.abstract,
                    "action_type": recursion.action_type,
                    "action_output": recursion.action_output,
                    "tool_call_results": recursion.tool_call_results,
                    "status": recursion.status,
                    "prompt_tokens": recursion.prompt_tokens,
                    "completion_tokens": recursion.completion_tokens,
                    "total_tokens": recursion.total_tokens,
                    "created_at": recursion.created_at,
                    "updated_at": recursion.updated_at,
                })

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

            result.append({
                "task_id": task.task_id,
                "user_message": task.user_message,
                "agent_answer": agent_answer,
                "status": task.status,
                "total_tokens": task.total_tokens,
                "recursions": recursion_list,
                "created_at": task.created_at,
                "updated_at": task.updated_at,
            })

        return result
