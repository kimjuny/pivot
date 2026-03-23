"""Background supervisor for reconnectable ReAct task execution.

This service decouples task execution from one specific HTTP streaming request so
browser tabs, channel consumers, and other observers can attach and detach
without interrupting the running task itself.
"""

from __future__ import annotations

import asyncio
import json
import logging
import traceback
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Literal

from app.crud.llm import llm as llm_crud
from app.db.session import get_engine
from app.llm.llm_factory import create_llm_from_config
from app.llm.thinking_policy import build_runtime_thinking_kwargs
from app.models.agent import Agent
from app.models.react import ReactRecursion, ReactTask, ReactTaskEvent
from app.orchestration.react.engine import ReactEngine
from app.orchestration.skills import select_skills_with_usage
from app.orchestration.tool import get_tool_manager
from app.orchestration.tool.builtin.programmatic_tool_call import (
    make_programmatic_tool_call,
)
from app.orchestration.tool.manager import ToolExecutionContext, ToolManager
from app.schemas.react import ReactStreamEvent, ReactStreamEventType, TokenUsage
from app.services.file_service import FileService
from app.services.react_runtime_service import ReactRuntimeService
from app.services.session_service import SessionService
from app.services.skill_service import (
    build_selected_skills_prompt_block,
    build_skill_mounts,
    list_visible_skills,
)
from app.services.workspace_service import (
    ensure_agent_workspace,
    load_all_user_tool_metadata,
)
from fastapi.concurrency import run_in_threadpool
from sqlmodel import Session, col, desc, select

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ReactTaskLaunchRequest:
    """Immutable launch parameters captured before background execution starts."""

    agent_id: int
    message: str
    username: str
    session_id: str | None
    file_ids: list[str]
    web_search_provider: str | None = None
    thinking_mode: Literal["fast", "thinking"] | None = None
    task_id: str | None = None


@dataclass(slots=True)
class ReactTaskLaunchResult:
    """Metadata returned to callers immediately after enqueueing a task."""

    task_id: str
    session_id: str | None
    status: str
    cursor_before_start: int


@dataclass(slots=True)
class _SessionSubscriber:
    """One live session subscription that may optionally filter by task."""

    queue: asyncio.Queue[dict[str, Any]]
    task_id: str | None = None


def _parse_name_allowlist(raw_json: str | None) -> set[str] | None:
    """Parse optional JSON allowlist text into a normalized set."""
    if raw_json is None:
        return None

    text = raw_json.strip()
    if text == "":
        return None

    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return set()

    if not isinstance(parsed, list):
        return set()

    result: set[str] = set()
    for item in parsed:
        if isinstance(item, str):
            normalized = item.strip()
            if normalized:
                result.add(normalized)
    return result


def _should_run_skill_resolution(*, task: ReactTask, agent: Agent) -> bool:
    """Return whether this launch should execute pre-task skill matching.

    Why: when a task resumes from a persisted CLARIFY pause, the runtime window
    already contains the selected-skill bootstrap context. Re-running skill
    resolution adds latency and duplicate UI events without changing the task.
    """
    if agent.skill_resolution_llm_id is None:
        return False

    return task.iteration == 0 and task.status in {"pending", "running"}


class ReactTaskSupervisor:
    """Owns background task execution and reconnectable event fan-out."""

    def __init__(self) -> None:
        self._active_jobs: dict[str, asyncio.Task[None]] = {}
        self._active_engines: dict[str, ReactEngine] = {}
        self._session_subscribers: dict[str, list[_SessionSubscriber]] = {}
        self._lock = asyncio.Lock()

    async def start_task(
        self,
        launch: ReactTaskLaunchRequest,
    ) -> ReactTaskLaunchResult:
        """Create or resume a task and ensure background execution is running.

        Args:
            launch: Immutable launch parameters captured from the caller.

        Returns:
            Immediate task metadata for the caller.

        Raises:
            ValueError: If the launch is invalid.
        """
        with Session(get_engine()) as db:
            task, cursor_before_start = self._prepare_task(db=db, launch=launch)
            task_id = task.task_id
            session_id = task.session_id
            status = task.status

        async with self._lock:
            existing_job = self._active_jobs.get(task_id)
            if existing_job is None or existing_job.done():
                self._active_jobs[task_id] = asyncio.create_task(
                    self._run_task(task_id=task_id, launch=launch),
                    name=f"react-task-{task_id}",
                )

        return ReactTaskLaunchResult(
            task_id=task_id,
            session_id=session_id,
            status=status,
            cursor_before_start=cursor_before_start,
        )

    async def request_cancel(self, task_id: str) -> bool:
        """Request cancellation for one task.

        Args:
            task_id: Task UUID to cancel.

        Returns:
            ``True`` when an active in-memory execution was found.
        """
        cancel_timestamp = datetime.now(UTC)
        session_id: str | None = None

        with Session(get_engine()) as db:
            statement = select(ReactTask).where(ReactTask.task_id == task_id)
            task = db.exec(statement).first()
            if task is None:
                return False
            if task.status in {"completed", "failed", "cancelled"}:
                return False

            task.status = "cancelled"
            task.cancel_requested_at = cancel_timestamp
            task.updated_at = cancel_timestamp
            db.add(task)
            db.commit()

            session_id = task.session_id
            await self._publish_event(
                db=db,
                session_id=session_id,
                event_data={
                    "type": "task_cancelled",
                    "task_id": task_id,
                    "iteration": task.iteration,
                    "timestamp": cancel_timestamp.isoformat(),
                    "data": {"reason": "user_stop"},
                },
            )

        async with self._lock:
            engine = self._active_engines.get(task_id)
            if engine is not None:
                engine.cancelled = True
                return True

        return False

    async def subscribe(
        self,
        *,
        session_id: str,
        task_id: str | None = None,
    ) -> _SessionSubscriber:
        """Register one live subscriber for a session event stream."""
        subscriber = _SessionSubscriber(queue=asyncio.Queue(), task_id=task_id)
        async with self._lock:
            self._session_subscribers.setdefault(session_id, []).append(subscriber)
        return subscriber

    async def unsubscribe(
        self,
        *,
        session_id: str,
        subscriber: _SessionSubscriber,
    ) -> None:
        """Remove one live subscriber from a session event stream."""
        async with self._lock:
            subscribers = self._session_subscribers.get(session_id, [])
            self._session_subscribers[session_id] = [
                item for item in subscribers if item is not subscriber
            ]
            if not self._session_subscribers[session_id]:
                self._session_subscribers.pop(session_id, None)

    def list_events(
        self,
        *,
        session_id: str,
        after_id: int = 0,
        task_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return persisted events newer than one cursor."""
        with Session(get_engine()) as db:
            statement = (
                select(ReactTaskEvent)
                .where(ReactTaskEvent.session_id == session_id)
                .where(col(ReactTaskEvent.id) > after_id)
                .order_by(col(ReactTaskEvent.id).asc())
            )
            if task_id is not None:
                statement = statement.where(ReactTaskEvent.task_id == task_id)
            rows = list(db.exec(statement).all())

        return [self._row_to_payload(row) for row in rows]

    def get_task(self, task_id: str) -> ReactTask | None:
        """Load one task row for API callers."""
        with Session(get_engine()) as db:
            statement = select(ReactTask).where(ReactTask.task_id == task_id)
            return db.exec(statement).first()

    def _prepare_task(
        self,
        *,
        db: Session,
        launch: ReactTaskLaunchRequest,
    ) -> tuple[ReactTask, int]:
        """Create or resume a task before background execution starts."""
        agent = db.get(Agent, launch.agent_id)
        if agent is None:
            raise ValueError(f"Agent {launch.agent_id} not found")
        if not agent.llm_id:
            raise ValueError(f"Agent {agent.name} has no LLM configured")
        if launch.session_id:
            session = SessionService(db).get_session(launch.session_id)
            if session is None:
                raise ValueError(f"Session {launch.session_id} not found")
            if session.user != launch.username:
                raise ValueError("Session does not belong to the current user")

        session_cursor = self._get_last_event_cursor(
            db=db,
            session_id=launch.session_id,
        )
        runtime_service = ReactRuntimeService(db)
        task: ReactTask | None = None

        if launch.task_id:
            statement = select(ReactTask).where(ReactTask.task_id == launch.task_id)
            existing_task = db.exec(statement).first()
            if existing_task is None:
                raise ValueError(f"Task {launch.task_id} not found")

            if existing_task.user != launch.username:
                raise ValueError("Task does not belong to the current user")

            if existing_task.status == "waiting_input":
                self._inject_clarify_reply(
                    db=db,
                    task=existing_task,
                    reply=launch.message,
                    runtime_service=runtime_service,
                )
                task = existing_task
            elif existing_task.status in {"pending", "running"}:
                task = existing_task
            else:
                raise ValueError(
                    "Only waiting-input tasks can be resumed with a task_id"
                )

        if task is None:
            task = ReactTask(
                task_id=str(uuid.uuid4()),
                session_id=launch.session_id,
                agent_id=launch.agent_id,
                user=launch.username,
                user_message=launch.message,
                user_intent=launch.message,
                status="pending",
                iteration=0,
                max_iteration=agent.max_iteration,
                cancel_requested_at=None,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            db.add(task)
            db.commit()
            db.refresh(task)

        return task, session_cursor

    def _inject_clarify_reply(
        self,
        *,
        db: Session,
        task: ReactTask,
        reply: str,
        runtime_service: ReactRuntimeService,
    ) -> None:
        """Persist a clarify reply onto the last clarify recursion."""
        statement = (
            select(ReactRecursion)
            .where(ReactRecursion.task_id == task.task_id)
            .order_by(desc(col(ReactRecursion.iteration_index)))
        )
        last_recursion = db.exec(statement).first()
        if last_recursion is None or last_recursion.action_type != "CLARIFY":
            raise ValueError("Task is waiting for input but has no clarify action")

        try:
            payload = json.loads(last_recursion.action_output or "{}")
        except json.JSONDecodeError:
            payload = {}

        payload["reply"] = reply
        last_recursion.action_output = json.dumps(payload, ensure_ascii=False)
        last_recursion.updated_at = datetime.now(UTC)
        task.cancel_requested_at = None
        task.updated_at = datetime.now(UTC)
        db.add(last_recursion)
        db.add(task)
        db.commit()

        runtime_service.set_next_action_result(task, [{"result": payload}])

    async def _run_task(self, *, task_id: str, launch: ReactTaskLaunchRequest) -> None:
        """Execute one task in the background and persist every emitted event."""
        try:
            with Session(get_engine()) as db:
                statement = select(ReactTask).where(ReactTask.task_id == task_id)
                task = db.exec(statement).first()
                if task is None:
                    logger.warning("Background task %s vanished before start", task_id)
                    return

                agent = db.get(Agent, task.agent_id)
                if agent is None:
                    raise ValueError(f"Agent {task.agent_id} not found")
                if not agent.llm_id:
                    raise ValueError(f"Agent {agent.name} has no LLM configured")

                llm_config = llm_crud.get(agent.llm_id, db)
                if llm_config is None:
                    raise ValueError(
                        f"LLM configuration with ID {agent.llm_id} not found"
                    )
                llm_runtime_kwargs = build_runtime_thinking_kwargs(
                    protocol=llm_config.protocol,
                    thinking_policy=llm_config.thinking_policy,
                    thinking_effort=llm_config.thinking_effort,
                    thinking_budget_tokens=llm_config.thinking_budget_tokens,
                    thinking_mode=launch.thinking_mode,
                )

                llm = create_llm_from_config(llm_config)

                turn_files = []
                turn_file_blocks = []
                if launch.file_ids:
                    file_service = FileService(db)
                    attached_files = file_service.attach_files_to_task(
                        file_ids=launch.file_ids,
                        username=launch.username,
                        session_id=task.session_id,
                        task_id=task.task_id,
                    )
                    turn_files = file_service.build_history_items([task.task_id]).get(
                        task.task_id, []
                    )
                    turn_file_blocks = [
                        content_block
                        for item in file_service.preprocess_files(attached_files)
                        for content_block in item.content_blocks
                    ]

                request_tool_manager = self._build_request_tool_manager(
                    username=launch.username,
                    agent_id=agent.id or 0,
                    raw_tool_ids=agent.tool_ids,
                )

                available_skills = list_visible_skills(db, launch.username)
                total_skill_count = len(available_skills)
                allowed_skills = _parse_name_allowlist(agent.skill_ids)
                if allowed_skills is not None:
                    available_skills = [
                        item
                        for item in available_skills
                        if item.get("name") in allowed_skills
                    ]
                candidate_skill_count = len(available_skills)
                allowed_skill_names: list[str] = []
                seen_skill_names: set[str] = set()
                for skill_item in available_skills:
                    skill_name = skill_item.get("name")
                    if (
                        not isinstance(skill_name, str)
                        or not skill_name
                        or skill_name in seen_skill_names
                    ):
                        continue
                    seen_skill_names.add(skill_name)
                    allowed_skill_names.append(skill_name)

                allowed_skill_mounts = build_skill_mounts(
                    db,
                    launch.username,
                    allowed_skill_names,
                )

                engine = ReactEngine(
                    llm=llm,
                    tool_manager=request_tool_manager,
                    db=db,
                    tool_execution_context=ToolExecutionContext(
                        username=launch.username,
                        agent_id=agent.id or 0,
                        sandbox_timeout_seconds=agent.sandbox_timeout_seconds,
                        web_search_provider=launch.web_search_provider,
                        allowed_skills=tuple(allowed_skill_mounts),
                    ),
                    stream_llm_responses=bool(llm_config.streaming),
                    llm_runtime_kwargs=llm_runtime_kwargs,
                )

                async with self._lock:
                    self._active_engines[task_id] = engine

                selected_skills: list[str] = []
                skill_resolution_tokens: dict[str, int] | None = None
                selected_skills_text = ""
                resolution_duration_ms = 0

                resolver_llm_id = agent.skill_resolution_llm_id
                if (
                    resolver_llm_id is not None
                    and _should_run_skill_resolution(task=task, agent=agent)
                ):
                    await self._publish_event(
                        db=db,
                        session_id=task.session_id,
                        event_data={
                            "type": "skill_resolution_start",
                            "task_id": task_id,
                            "iteration": task.iteration,
                            "timestamp": datetime.now(UTC).isoformat(),
                        },
                    )

                    resolution_started_at = perf_counter()
                    try:
                        resolver_llm_config = llm_crud.get(resolver_llm_id, db)
                        if resolver_llm_config is not None:
                            resolver_llm = create_llm_from_config(resolver_llm_config)
                            session_context = {}
                            if task.session_id:
                                session_context = ReactRuntimeService(
                                    db
                                ).build_session_context_payload(task.session_id)

                            selection_result = await run_in_threadpool(
                                select_skills_with_usage,
                                resolver_llm,
                                launch.message,
                                available_skills,
                                session_context,
                            )
                            raw_selected_skills = selection_result.get(
                                "selected_skills", []
                            )
                            if isinstance(raw_selected_skills, list):
                                selected_skills = [
                                    item
                                    for item in raw_selected_skills
                                    if isinstance(item, str)
                                ]
                            skill_resolution_tokens = selection_result.get("tokens")
                            selected_skills_text = build_selected_skills_prompt_block(
                                session=db,
                                username=launch.username,
                                selected_skills=selected_skills,
                            )
                    except Exception as exc:
                        logger.warning(
                            "Skill resolution failed task_id=%s: %s", task_id, exc
                        )

                    resolution_duration_ms = int(
                        (perf_counter() - resolution_started_at) * 1000
                    )
                    skill_result_event = {
                        "type": "skill_resolution_result",
                        "task_id": task_id,
                        "iteration": task.iteration,
                        "timestamp": datetime.now(UTC).isoformat(),
                        "data": {
                            "count": len(selected_skills),
                            "selected_skills": selected_skills,
                            "total_skill_count": total_skill_count,
                            "candidate_skill_count": candidate_skill_count,
                            "duration_ms": resolution_duration_ms,
                            "tokens": skill_resolution_tokens,
                        },
                    }
                    task.skill_selection_result = json.dumps(
                        skill_result_event["data"],
                        ensure_ascii=False,
                    )
                    task.updated_at = datetime.now(UTC)
                    db.add(task)
                    db.commit()
                    if engine.cancelled or task.status == "cancelled":
                        return
                    await self._publish_event(
                        db=db,
                        session_id=task.session_id,
                        event_data=skill_result_event,
                    )

                async for event_data in engine.run_task(
                    task=task,
                    selected_skills_text=selected_skills_text,
                    turn_user_message=launch.message,
                    turn_files=turn_files,
                    turn_file_blocks=turn_file_blocks,
                ):
                    await self._publish_event(
                        db=db,
                        session_id=task.session_id,
                        event_data=event_data,
                    )
        except Exception as exc:
            logger.error("Background ReAct task failed task_id=%s err=%s", task_id, exc)
            logger.error(traceback.format_exc())
            with Session(get_engine()) as db:
                statement = select(ReactTask).where(ReactTask.task_id == task_id)
                task = db.exec(statement).first()
                if task is not None and task.status not in {"completed", "cancelled"}:
                    task.status = "failed"
                    task.updated_at = datetime.now(UTC)
                    db.add(task)
                    db.commit()
                    await self._publish_event(
                        db=db,
                        session_id=task.session_id,
                        event_data={
                            "type": "error",
                            "task_id": task.task_id,
                            "iteration": task.iteration,
                            "timestamp": datetime.now(UTC).isoformat(),
                            "data": {"error": str(exc)},
                        },
                    )
        finally:
            async with self._lock:
                self._active_jobs.pop(task_id, None)
                self._active_engines.pop(task_id, None)

    def _build_request_tool_manager(
        self,
        *,
        username: str,
        agent_id: int,
        raw_tool_ids: str | None,
    ) -> ToolManager:
        """Build the request-scoped tool registry used for one task."""
        ensure_agent_workspace(username, agent_id)
        shared_manager = get_tool_manager()
        request_tool_manager = ToolManager()
        for meta in shared_manager.list_tools():
            request_tool_manager.add_entry(meta)

        private_metas = load_all_user_tool_metadata(username)
        for meta in private_metas:
            if request_tool_manager.get_tool(meta.name) is None:
                request_tool_manager.add_entry(meta)
            else:
                logger.warning(
                    "Private tool '%s' conflicts with a shared tool name and was skipped.",
                    meta.name,
                )

        ptc_meta = request_tool_manager.get_tool("programmatic_tool_call")
        if ptc_meta is not None:
            full_callables = {m.name: m.func for m in request_tool_manager.list_tools()}
            ptc_meta.func = make_programmatic_tool_call(full_callables)

        allowed_tools = _parse_name_allowlist(raw_tool_ids)
        if allowed_tools is None:
            return request_tool_manager

        filtered_manager = ToolManager()
        for meta in request_tool_manager.list_tools():
            if meta.name in allowed_tools:
                filtered_manager.add_entry(meta)
        return filtered_manager

    async def _publish_event(
        self,
        *,
        db: Session,
        session_id: str | None,
        event_data: dict[str, Any],
    ) -> None:
        """Persist one emitted event and fan it out to live subscribers."""
        event_type_value = str(event_data.get("type", "")).strip()
        if event_type_value == "":
            return

        try:
            event_type = ReactStreamEventType(event_type_value)
        except ValueError:
            logger.warning("Skipping unknown task event type: %s", event_type_value)
            return

        row = ReactTaskEvent(
            session_id=session_id,
            task_id=str(event_data.get("task_id", "")),
            type=event_type.value,
            trace_id=(
                str(event_data.get("trace_id"))
                if event_data.get("trace_id") is not None
                else None
            ),
            iteration=int(event_data.get("iteration", 0) or 0),
            delta=(
                str(event_data.get("delta"))
                if event_data.get("delta") is not None
                else None
            ),
            data_json=self._serialize_optional_json(event_data.get("data")),
            tokens_json=self._serialize_optional_json(event_data.get("tokens")),
            total_tokens_json=self._serialize_optional_json(
                event_data.get("total_tokens")
            ),
            created_at=self._parse_event_timestamp(event_data.get("timestamp")),
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        payload = self._row_to_payload(row)
        await self._fan_out_live_event(payload=payload)

    async def _fan_out_live_event(self, *, payload: dict[str, Any]) -> None:
        """Push one event payload to all live subscribers of the owning session."""
        session_id = payload.get("session_id")
        if not isinstance(session_id, str) or session_id == "":
            return

        async with self._lock:
            subscribers = list(self._session_subscribers.get(session_id, []))

        for subscriber in subscribers:
            if subscriber.task_id and subscriber.task_id != payload.get("task_id"):
                continue
            await subscriber.queue.put(payload)

    def _row_to_payload(self, row: ReactTaskEvent) -> dict[str, Any]:
        """Convert a persisted task-event row into API payload shape."""
        data = self._parse_optional_json(row.data_json)
        tokens = self._parse_optional_json(row.tokens_json)
        total_tokens = self._parse_optional_json(row.total_tokens_json)
        event = ReactStreamEvent(
            event_id=row.id,
            type=ReactStreamEventType(row.type),
            task_id=row.task_id,
            trace_id=row.trace_id,
            iteration=row.iteration,
            delta=row.delta,
            data=data if isinstance(data, dict) else None,
            timestamp=row.created_at,
            tokens=TokenUsage(**tokens) if isinstance(tokens, dict) else None,
            total_tokens=(
                TokenUsage(**total_tokens) if isinstance(total_tokens, dict) else None
            ),
        )
        payload = event.model_dump(mode="json")
        payload["session_id"] = row.session_id
        return payload

    def _get_last_event_cursor(self, *, db: Session, session_id: str | None) -> int:
        """Return the current latest event cursor for one session."""
        if session_id is None:
            return 0
        statement = (
            select(ReactTaskEvent)
            .where(ReactTaskEvent.session_id == session_id)
            .order_by(col(ReactTaskEvent.id).desc())
        )
        row = db.exec(statement).first()
        return int(row.id or 0) if row is not None else 0

    def _serialize_optional_json(self, value: Any) -> str | None:
        """Serialize one optional payload for event persistence."""
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False)

    def _parse_optional_json(self, raw_value: str | None) -> Any:
        """Parse one optional persisted JSON blob."""
        if raw_value is None:
            return None
        try:
            return json.loads(raw_value)
        except json.JSONDecodeError:
            return None

    def _parse_event_timestamp(self, raw_value: Any) -> datetime:
        """Normalize an event timestamp into explicit UTC."""
        if isinstance(raw_value, datetime):
            return raw_value if raw_value.tzinfo else raw_value.replace(tzinfo=UTC)
        if isinstance(raw_value, str):
            try:
                parsed = datetime.fromisoformat(raw_value)
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
            except ValueError:
                pass
        return datetime.now(UTC)


_SUPERVISOR: ReactTaskSupervisor | None = None


def get_react_task_supervisor() -> ReactTaskSupervisor:
    """Return the process-wide reconnectable ReAct task supervisor."""
    global _SUPERVISOR
    if _SUPERVISOR is None:
        _SUPERVISOR = ReactTaskSupervisor()
    return _SUPERVISOR
