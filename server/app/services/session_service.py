"""Session service for conversation threads and persisted chat history."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from app.models.agent_release import AgentTestSnapshot
from app.models.react import (
    ReactPlanStep,
    ReactRecursionState,
    ReactTask,
    ReactTaskEvent,
)
from app.models.session import Session
from app.schemas.file import FileAssetListItem
from app.schemas.task_attachment import TaskAttachmentListItem
from app.services.agent_service import AgentService
from app.services.file_service import FileService
from app.services.task_attachment_service import TaskAttachmentService
from sqlalchemy import func
from sqlmodel import Session as DBSession, col, select

SESSION_IDLE_TIMEOUT = timedelta(minutes=15)
SESSION_METADATA_UNSET = object()


class SessionService:
    """Service class for session records and chat-history persistence."""

    def __init__(self, db: DBSession) -> None:
        """Initialize the service with a database session.

        Args:
            db: Database session for persistence operations.
        """
        self.db = db

    @staticmethod
    def _serialize_history_files(
        files: list[FileAssetListItem | dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        """Normalizes persisted file payloads before writing chat history."""
        return [
            (
                item.model_dump()
                if isinstance(item, FileAssetListItem)
                else FileAssetListItem.model_validate(item).model_dump()
            )
            for item in files or []
        ]

    @staticmethod
    def _serialize_history_attachments(
        attachments: list[TaskAttachmentListItem | dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        """Normalizes persisted attachment payloads before writing chat history."""
        return [
            (
                item.model_dump()
                if isinstance(item, TaskAttachmentListItem)
                else TaskAttachmentListItem.model_validate(item).model_dump()
            )
            for item in attachments or []
        ]

    def create_session(
        self,
        agent_id: int,
        user: str,
        *,
        session_type: Literal["consumer", "studio_test"] = "consumer",
        test_snapshot_id: int | None = None,
    ) -> Session:
        """Create a new session row.

        Args:
            agent_id: ID of the agent for this session.
            user: Username of the session owner.
            session_type: Whether the session belongs to Consumer or Studio Test.
            test_snapshot_id: Frozen Studio working-copy snapshot pinned to the
                session when ``session_type`` is ``studio_test``.

        Returns:
            Created Session instance.

        Raises:
            ValueError: If the session type is invalid, if the agent is not
                ready for the requested session type, or if required snapshot
                metadata is missing.
        """
        session_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        release_id: int | None = None
        resolved_test_snapshot_id: int | None = None

        if session_type == "consumer":
            agent = AgentService(self.db).require_session_creation_ready(agent_id)
            release_id = agent.active_release_id
        elif session_type == "studio_test":
            AgentService(self.db).get_required_agent(agent_id)
            if test_snapshot_id is None:
                raise ValueError("Studio test sessions require a frozen snapshot.")
            resolved_test_snapshot_id = test_snapshot_id
        else:
            raise ValueError(f"Unsupported session type '{session_type}'.")

        # Create session
        session = Session(
            session_id=session_id,
            agent_id=agent_id,
            type=session_type,
            release_id=release_id,
            test_snapshot_id=resolved_test_snapshot_id,
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

    def list_sessions_for_operations(
        self,
        *,
        agent_id: int | None = None,
        status: str | None = None,
        session_type: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Session], int]:
        """List all sessions across users for the Studio Operations view.

        Args:
            agent_id: Optional agent ID filter.
            status: Optional session status filter.
            session_type: Optional session type filter.
            page: 1-based page number.
            page_size: Maximum rows per page.

        Returns:
            Tuple of (sessions, total_count) for pagination.
        """
        filter_clauses: list[Any] = []
        if agent_id is not None:
            filter_clauses.append(Session.agent_id == agent_id)
        if status is not None:
            filter_clauses.append(Session.status == status)
        if session_type is not None:
            filter_clauses.append(Session.type == session_type)

        count_stmt = select(func.count(Session.id))  # type: ignore[reportArgumentType, reportCallIssue]
        for clause in filter_clauses:
            count_stmt = count_stmt.where(clause)
        total = self.db.exec(count_stmt).one()

        data_stmt = select(Session).order_by(col(Session.updated_at).desc())
        for clause in filter_clauses:
            data_stmt = data_stmt.where(clause)
        offset = (page - 1) * page_size
        data_stmt = data_stmt.offset(offset).limit(page_size)
        sessions = list(self.db.exec(data_stmt).all())

        return sessions, total

    def get_sessions_by_user(
        self,
        user: str,
        agent_id: int | None = None,
        agent_ids: list[int] | None = None,
        session_type: Literal["consumer", "studio_test"] | None = None,
        limit: int = 50,
    ) -> list[Session]:
        """Get all sessions for a user, optionally filtered by agent.

        Args:
            user: Username to filter by.
            agent_id: Optional agent ID to filter by.
            agent_ids: Optional set of agent IDs to include.
            session_type: Optional session type to filter by.
            limit: Maximum number of sessions to return.

        Returns:
            List of Session instances.
        """
        stmt = select(Session).where(Session.user == user)
        if agent_id is not None:
            stmt = stmt.where(Session.agent_id == agent_id)
        elif agent_ids is not None:
            if len(agent_ids) == 0:
                return []
            stmt = stmt.where(col(Session.agent_id).in_(agent_ids))
        if session_type is not None:
            stmt = stmt.where(Session.type == session_type)
        stmt = stmt.order_by(
            col(Session.is_pinned).desc(),
            col(Session.updated_at).desc(),
        ).limit(limit)
        return list(self.db.exec(stmt).all())

    def get_test_workspace_hashes(
        self,
        snapshot_ids: list[int],
    ) -> dict[int, str]:
        """Return Studio workspace hashes keyed by test snapshot identifier."""
        if len(snapshot_ids) == 0:
            return {}

        statement = select(AgentTestSnapshot).where(
            col(AgentTestSnapshot.id).in_(snapshot_ids)
        )
        return {
            snapshot.id or 0: snapshot.workspace_hash
            for snapshot in self.db.exec(statement).all()
            if snapshot.id is not None
        }

    def update_session_metadata(
        self,
        session_id: str,
        *,
        title: str | None | object = SESSION_METADATA_UNSET,
        is_pinned: bool | object = SESSION_METADATA_UNSET,
    ) -> Session | None:
        """Update sidebar-visible metadata for one session.

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

        if is_pinned is not SESSION_METADATA_UNSET and session.is_pinned != is_pinned:
            session.is_pinned = bool(is_pinned)
            has_changes = True

        if has_changes:
            session.updated_at = datetime.now(UTC)
            self.db.add(session)
            self.db.commit()
            self.db.refresh(session)

        return session

    def update_chat_history(
        self,
        session_id: str,
        message_type: str,
        content: str,
        files: list[FileAssetListItem | dict[str, Any]] | None = None,
        attachments: list[TaskAttachmentListItem | dict[str, Any]] | None = None,
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
                "files": self._serialize_history_files(files),
                "attachments": self._serialize_history_attachments(attachments),
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
        TaskAttachmentService(self.db).delete_by_session_id(session_id)
        test_snapshot_id = session.test_snapshot_id

        self.db.delete(session)
        self.db.commit()
        if test_snapshot_id is not None:
            still_referenced = self.db.exec(
                select(Session).where(Session.test_snapshot_id == test_snapshot_id)
            ).first()
            if still_referenced is None:
                test_snapshot = self.db.get(AgentTestSnapshot, test_snapshot_id)
                if test_snapshot is not None:
                    self.db.delete(test_snapshot)
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
        attachment_history = TaskAttachmentService(self.db).list_by_task_ids(
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

            pending_user_action: dict[str, Any] | None = None
            if task.pending_user_action_json:
                try:
                    parsed_pending_action = json.loads(task.pending_user_action_json)
                    if isinstance(parsed_pending_action, dict):
                        pending_user_action = parsed_pending_action
                except json.JSONDecodeError:
                    pending_user_action = None

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
                        "reason": recursion.reason,
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
                    "assistant_attachments": attachment_history.get(task.task_id, []),
                    "agent_answer": agent_answer,
                    "status": task.status,
                    "total_tokens": task.total_tokens,
                    "skill_selection_result": skill_selection_result,
                    "pending_user_action": pending_user_action,
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
        ``summary`` until that recursion is finalized, so a
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
