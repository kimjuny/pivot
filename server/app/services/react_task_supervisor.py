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
from app.models.user import User
from app.orchestration.react.engine import ReactEngine
from app.orchestration.skills import select_skills_with_usage
from app.orchestration.tool.manager import ToolExecutionContext, ToolManager
from app.schemas.react import ReactStreamEvent, ReactStreamEventType, TokenUsage
from app.services.agent_release_runtime_service import AgentReleaseRuntimeService
from app.services.agent_service import AgentService
from app.services.extension_hook_effect_service import (
    ExtensionHookEffectService,
    HookEffectApplicationResult,
)
from app.services.extension_hook_execution_service import (
    ExtensionHookExecutionService,
)
from app.services.extension_hook_service import ExtensionHookService
from app.services.extension_service import ExtensionService
from app.services.file_service import FileService
from app.services.react_runtime_service import ReactRuntimeService
from app.services.session_service import SessionService
from app.services.skill_change_service import apply_skill_change_submission
from app.services.skill_service import (
    build_selected_skills_prompt_block,
    build_skill_mounts,
    list_visible_skills,
)
from fastapi.concurrency import run_in_threadpool
from sqlmodel import Session, col, desc, select

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ReactTaskLaunchRequest:
    """Immutable launch parameters captured before background execution starts."""

    agent_id: int
    message: str | None
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


def _should_run_skill_resolution(
    *,
    task: ReactTask,
    resolver_llm_id: int | None,
) -> bool:
    """Return whether this launch should execute pre-task skill matching.

    Why: when a task resumes from a persisted CLARIFY pause, the runtime window
    already contains the selected-skill bootstrap context. Re-running skill
    resolution adds latency and duplicate UI events without changing the task.
    """
    if resolver_llm_id is None:
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

    async def submit_pending_user_action(
        self,
        *,
        task_id: str,
        username: str,
        decision: Literal["approve", "reject"],
    ) -> ReactTaskLaunchResult:
        """Apply one structured waiting action and resume the task."""
        with Session(get_engine()) as db:
            statement = select(ReactTask).where(ReactTask.task_id == task_id)
            task = db.exec(statement).first()
            if task is None:
                raise ValueError(f"Task {task_id} not found")
            if task.user != username:
                raise ValueError("Task does not belong to the current user")
            if task.status != "waiting_input":
                raise ValueError("Task is not waiting for a user action")

            pending_user_action = self._load_pending_user_action(task)
            if pending_user_action is None:
                raise ValueError("Task does not have a structured pending user action")
            if pending_user_action.get("kind") != "skill_change_approval":
                raise ValueError("Unsupported pending user action kind")

            approval_request = pending_user_action.get("approval_request")
            if not isinstance(approval_request, dict):
                raise ValueError("Pending user action is missing approval metadata")
            submission_id = approval_request.get("submission_id")
            if not isinstance(submission_id, int) or submission_id <= 0:
                raise ValueError("Pending user action is missing submission_id")

            current_user = db.exec(
                select(User).where(User.username == username)
            ).first()
            if current_user is None:
                raise ValueError(f"User '{username}' not found.")

            apply_result = apply_skill_change_submission(
                db,
                current_user,
                submission_id=submission_id,
                decision=decision,
            )
            runtime_service = ReactRuntimeService(db)
            runtime_service.set_next_action_result(
                task,
                [
                    {
                        "result": {
                            "kind": "skill_change_result",
                            "decision": decision,
                            **apply_result,
                        }
                    }
                ],
            )
            task.status = "pending"
            task.cancel_requested_at = None
            task.updated_at = datetime.now(UTC)
            db.add(task)
            SessionService(db).sync_runtime_status(task.session_id, commit=False)
            db.commit()

            cursor_before_start = self._get_last_event_cursor(
                db=db,
                session_id=task.session_id,
            )
            launch = ReactTaskLaunchRequest(
                agent_id=task.agent_id,
                message=None,
                username=username,
                session_id=task.session_id,
                file_ids=[],
                task_id=task.task_id,
            )

        async with self._lock:
            existing_job = self._active_jobs.get(task_id)
            if existing_job is None or existing_job.done():
                self._active_jobs[task_id] = asyncio.create_task(
                    self._run_task(task_id=task_id, launch=launch),
                    name=f"react-task-{task_id}",
                )

        return ReactTaskLaunchResult(
            task_id=task.task_id,
            session_id=task.session_id,
            status="pending",
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
            SessionService(db).sync_runtime_status(task.session_id, commit=False)
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
        session = None
        if launch.session_id:
            session = SessionService(db).get_session(launch.session_id)
            if session is None:
                raise ValueError(f"Session {launch.session_id} not found")
            if session.user != launch.username:
                raise ValueError("Session does not belong to the current user")
        agent_service = AgentService(db)
        if session is not None and session.type == "studio_test":
            agent_service.get_required_agent(launch.agent_id)
        else:
            agent_service.require_interaction_enabled(launch.agent_id)
        runtime_config = (
            AgentReleaseRuntimeService(db).resolve_for_session(launch.session_id)
            if launch.session_id
            else AgentReleaseRuntimeService(db).resolve_for_agent(launch.agent_id)
        )
        if runtime_config.agent_id != launch.agent_id:
            raise ValueError("Session does not belong to the requested agent")
        if runtime_config.llm_id is None:
            raise ValueError(f"Agent {runtime_config.agent_name} has no LLM configured")

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
                if existing_task.pending_user_action_json:
                    raise ValueError(
                        "This task requires a structured user action instead of a text reply"
                    )
                if launch.message is None or launch.message.strip() == "":
                    raise ValueError("Reply message cannot be empty")
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
            if launch.message is None or launch.message.strip() == "":
                raise ValueError("message is required when starting a new text turn")
            launch_timestamp = datetime.now(UTC)
            task = ReactTask(
                task_id=str(uuid.uuid4()),
                session_id=launch.session_id,
                agent_id=launch.agent_id,
                user=launch.username,
                user_message=launch.message,
                user_intent=launch.message,
                status="pending",
                iteration=0,
                max_iteration=runtime_config.max_iteration,
                cancel_requested_at=None,
                created_at=launch_timestamp,
                updated_at=launch_timestamp,
            )
            if session is not None:
                session.updated_at = launch_timestamp
                db.add(session)
            db.add(task)
            SessionService(db).sync_runtime_status(task.session_id, commit=False)
            db.commit()
            db.refresh(task)

        return task, session_cursor

    def _load_pending_user_action(
        self,
        task: ReactTask,
    ) -> dict[str, Any] | None:
        """Parse the persisted structured waiting action on one task."""
        if not task.pending_user_action_json:
            return None
        try:
            parsed = json.loads(task.pending_user_action_json)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

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
        task.status = "pending"
        task.cancel_requested_at = None
        task.updated_at = datetime.now(UTC)
        db.add(last_recursion)
        db.add(task)
        SessionService(db).sync_runtime_status(task.session_id, commit=False)
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
                runtime_config = AgentReleaseRuntimeService(db).resolve_for_task(task)
                hook_service = ExtensionHookService(
                    runtime_config.extension_bundle,
                    execution_service=ExtensionHookExecutionService(db),
                )
                hook_effect_service = ExtensionHookEffectService()
                if runtime_config.llm_id is None:
                    raise ValueError(
                        f"Agent {runtime_config.agent_name} has no LLM configured"
                    )

                llm_config = llm_crud.get(runtime_config.llm_id, db)
                if llm_config is None:
                    raise ValueError(
                        f"LLM configuration with ID {runtime_config.llm_id} not found"
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
                    db=db,
                    username=launch.username,
                    agent_id=agent.id or 0,
                    raw_tool_ids=runtime_config.raw_tool_ids,
                    extension_bundle=runtime_config.extension_bundle,
                )

                available_skills = list_visible_skills(db, launch.username)
                extension_skills = ExtensionService(db).build_bundle_skill_payloads(
                    runtime_config.extension_bundle
                )
                available_skills.extend(extension_skills)
                total_skill_count = len(available_skills)
                allowed_skills = _parse_name_allowlist(runtime_config.raw_skill_ids)
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
                    extra_skills=extension_skills,
                )

                engine = ReactEngine(
                    llm=llm,
                    tool_manager=request_tool_manager,
                    db=db,
                    tool_execution_context=ToolExecutionContext(
                        username=launch.username,
                        agent_id=agent.id or 0,
                        sandbox_timeout_seconds=runtime_config.sandbox_timeout_seconds,
                        web_search_provider=launch.web_search_provider,
                        allowed_skills=tuple(allowed_skill_mounts),
                    ),
                    stream_llm_responses=bool(llm_config.streaming),
                    llm_runtime_kwargs=llm_runtime_kwargs,
                )

                before_start_effects = await self._run_task_hooks(
                    db=db,
                    session_id=task.session_id,
                    hook_service=hook_service,
                    hook_effect_service=hook_effect_service,
                    task=task,
                    runtime_config=runtime_config,
                    event_name="task.before_start",
                    event_payload={"message": launch.message},
                )

                async with self._lock:
                    self._active_engines[task_id] = engine

                selected_skills: list[str] = []
                skill_resolution_tokens: dict[str, int] | None = None
                selected_skills_text = ""
                resolution_duration_ms = 0

                resolver_llm_id = runtime_config.skill_resolution_llm_id
                if resolver_llm_id is not None and _should_run_skill_resolution(
                    task=task,
                    resolver_llm_id=resolver_llm_id,
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
                                task.user_message,
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
                                extra_skills=extension_skills,
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
                    task_bootstrap_prefix_blocks=(
                        before_start_effects.task_bootstrap_head_blocks
                    ),
                    task_bootstrap_suffix_blocks=(
                        before_start_effects.task_bootstrap_tail_blocks
                    ),
                    turn_user_message=launch.message,
                    turn_files=turn_files,
                    turn_file_blocks=turn_file_blocks,
                ):
                    await self._publish_event(
                        db=db,
                        session_id=task.session_id,
                        event_data=event_data,
                    )
                    await self._run_iteration_hooks_for_event(
                        db=db,
                        session_id=task.session_id,
                        hook_service=hook_service,
                        hook_effect_service=hook_effect_service,
                        task=task,
                        runtime_config=runtime_config,
                        event_data=event_data,
                    )

                if task.status == "completed":
                    await self._run_task_hooks(
                        db=db,
                        session_id=task.session_id,
                        hook_service=hook_service,
                        hook_effect_service=hook_effect_service,
                        task=task,
                        runtime_config=runtime_config,
                        event_name="task.completed",
                        event_payload={},
                    )
                elif task.status == "waiting_input":
                    await self._run_task_hooks(
                        db=db,
                        session_id=task.session_id,
                        hook_service=hook_service,
                        hook_effect_service=hook_effect_service,
                        task=task,
                        runtime_config=runtime_config,
                        event_name="task.waiting_input",
                        event_payload={},
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
                    SessionService(db).sync_runtime_status(
                        task.session_id, commit=False
                    )
                    db.commit()
                    await self._publish_event(
                        db=db,
                        session_id=task.session_id,
                        event_data={
                            "type": "error",
                            "task_id": task.task_id,
                            "iteration": task.iteration,
                            "timestamp": datetime.now(UTC).isoformat(),
                            "data": {"error": str(exc), "terminal": True},
                        },
                    )
                    runtime_config = AgentReleaseRuntimeService(db).resolve_for_task(
                        task
                    )
                    await self._run_task_hooks(
                        db=db,
                        session_id=task.session_id,
                        hook_service=ExtensionHookService(
                            runtime_config.extension_bundle,
                            execution_service=ExtensionHookExecutionService(db),
                        ),
                        hook_effect_service=ExtensionHookEffectService(),
                        task=task,
                        runtime_config=runtime_config,
                        event_name="task.failed",
                        event_payload={"error": str(exc)},
                    )
        finally:
            async with self._lock:
                self._active_jobs.pop(task_id, None)
                self._active_engines.pop(task_id, None)

    def _build_request_tool_manager(
        self,
        *,
        db: Session,
        username: str,
        agent_id: int,
        raw_tool_ids: str | None,
        extension_bundle: list[dict[str, Any]],
    ) -> ToolManager:
        """Build the request-scoped tool registry used for one task."""
        return ExtensionService(db).build_request_tool_manager(
            username=username,
            agent_id=agent_id,
            raw_tool_ids=raw_tool_ids,
            extension_bundle=extension_bundle,
        )

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

    async def _run_task_hooks(
        self,
        *,
        db: Session,
        session_id: str | None,
        hook_service: ExtensionHookService,
        hook_effect_service: ExtensionHookEffectService,
        task: ReactTask,
        runtime_config: Any,
        event_name: str,
        event_payload: dict[str, Any],
    ) -> HookEffectApplicationResult:
        """Execute task-level extension hooks and publish emitted events."""
        hook_context = {
            "session_id": task.session_id,
            "task_id": task.task_id,
            "trace_id": None,
            "iteration": task.iteration,
            "agent_id": task.agent_id,
            "user": self._build_hook_user_snapshot(db=db, username=task.user),
            "release_id": runtime_config.release_id,
            "execution_mode": "live",
            "timestamp": datetime.now(UTC).isoformat(),
            "task": self._build_task_hook_snapshot(db=db, task=task),
            "runtime": {
                "source": runtime_config.source,
                "task_status": task.status,
            },
            "event_payload": event_payload,
        }
        try:
            effects = await hook_service.run_task_hooks(
                event_name=event_name,
                hook_context=hook_context,
            )
            application_result = hook_effect_service.apply_effects(
                event_name=event_name,
                effects=effects,
            )
        except Exception:
            logger.warning(
                "Extension hooks failed task_id=%s event=%s",
                task.task_id,
                event_name,
                exc_info=True,
            )
            return HookEffectApplicationResult()
        for emitted_event in application_result.emitted_events:
            await self._publish_event(
                db=db,
                session_id=session_id,
                event_data=emitted_event,
            )
        return application_result

    def _build_task_hook_snapshot(
        self,
        *,
        db: Session,
        task: ReactTask,
    ) -> dict[str, Any]:
        """Build stable task metadata exposed to lifecycle hooks.

        Why: mutable extensions such as external memory providers need a small
        amount of task context like the original user request and the final
        answer, but they still should not depend on Pivot ORM objects directly.
        """
        return {
            "user_message": task.user_message,
            "status": task.status,
            "total_tokens": task.total_tokens,
            "agent_answer": self._extract_task_agent_answer(
                db=db, task_id=task.task_id
            ),
        }

    def _build_hook_user_snapshot(
        self,
        *,
        db: Session,
        username: str,
    ) -> dict[str, Any]:
        """Build stable user metadata exposed to lifecycle hooks.

        Why: external extensions such as memory backends often need one stable
        namespace that combines the current user and agent. Hooks should not
        query Pivot models directly, so the supervisor provides a small user
        snapshot as part of the hook context.
        """
        user = db.exec(select(User).where(User.username == username)).first()
        return {
            "id": user.id if user is not None else None,
            "username": username,
        }

    def _extract_task_agent_answer(
        self,
        *,
        db: Session,
        task_id: str,
    ) -> str | None:
        """Return the latest persisted ANSWER payload for one task."""
        statement = (
            select(ReactRecursion)
            .where(ReactRecursion.task_id == task_id)
            .where(ReactRecursion.action_type == "ANSWER")
            .order_by(desc(col(ReactRecursion.iteration_index)))
        )
        recursions = list(db.exec(statement).all())
        for recursion in recursions:
            if not recursion.action_output:
                continue
            try:
                output = json.loads(recursion.action_output)
            except json.JSONDecodeError:
                continue
            if not isinstance(output, dict):
                continue
            answer = output.get("answer")
            if isinstance(answer, str) and answer.strip():
                return answer.strip()
        return None

    async def _run_iteration_hooks_for_event(
        self,
        *,
        db: Session,
        session_id: str | None,
        hook_service: ExtensionHookService,
        hook_effect_service: ExtensionHookEffectService,
        task: ReactTask,
        runtime_config: Any,
        event_data: dict[str, Any],
    ) -> None:
        """Translate stable runtime events into iteration hook invocations."""
        event_type_value = str(event_data.get("type", "")).strip()
        hook_event_name = {
            "plan_update": "iteration.plan_updated",
            "answer": "iteration.answer_ready",
            "error": "iteration.error",
            "tool_call": "iteration.before_tool_call",
            "tool_result": "iteration.after_tool_result",
        }.get(event_type_value)
        if hook_event_name is None:
            return

        raw_data = event_data.get("data")
        event_payload: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}

        hook_context = {
            "session_id": task.session_id,
            "task_id": task.task_id,
            "trace_id": event_data.get("trace_id"),
            "iteration": int(event_data.get("iteration", task.iteration) or 0),
            "agent_id": task.agent_id,
            "user": self._build_hook_user_snapshot(db=db, username=task.user),
            "release_id": runtime_config.release_id,
            "execution_mode": "live",
            "timestamp": event_data.get("timestamp") or datetime.now(UTC).isoformat(),
            "runtime": {
                "source": runtime_config.source,
                "task_status": task.status,
            },
            "event_payload": event_payload,
        }
        try:
            effects = await hook_service.run_hooks(
                event_name=hook_event_name,
                hook_context=hook_context,
            )
            application_result = hook_effect_service.apply_effects(
                event_name=hook_event_name,
                effects=effects,
            )
        except Exception:
            logger.warning(
                "Extension iteration hooks failed task_id=%s event=%s",
                task.task_id,
                hook_event_name,
                exc_info=True,
            )
            return

        for emitted_event in application_result.emitted_events:
            await self._publish_event(
                db=db,
                session_id=session_id,
                event_data=emitted_event,
            )

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
