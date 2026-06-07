"""Execute agent-to-agent delegation by running a sub-agent ReAct loop."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.models.react import ReactTask
from app.models.session import Session
from app.orchestration.react.prompt_template import (
    build_runtime_system_prompt,
)
from app.services.agent_release_runtime_service import AgentReleaseRuntimeService
from app.services.agent_service import AgentService
from app.services.react_runtime_service import ReactRuntimeService
from sqlmodel import select

if TYPE_CHECKING:
    from app.models.agent_delegation import AgentDelegation
    from app.orchestration.react.engine import ReactEngine
    from app.orchestration.tool.manager import ToolExecutionContext
    from sqlmodel import Session as DBSession

logger = logging.getLogger(__name__)

MAX_DELEGATION_DEPTH = 3


def _delegation_event(event_type: str, **kwargs: Any) -> dict[str, Any]:
    """Build a delegation-level SSE event dict."""
    return {"type": event_type, "data": kwargs}


def _refreshed_token_usage(task: ReactTask) -> dict[str, int]:
    """Read latest token counters from a refreshed task row."""
    return {
        "total_tokens": task.total_tokens,
        "prompt_tokens": task.total_prompt_tokens,
        "completion_tokens": task.total_completion_tokens,
    }


# Appended to the sub-agent's system prompt so it knows it can CLARIFY.
_CLARIFY_PROMPT_SECTION = """\

## Delegation Clarify

You are a delegated sub-agent working on behalf of another agent.
If the instruction is ambiguous or you need more information to proceed,
use the CLARIFY action to ask a question. Your question will be forwarded
to the agent that delegated to you, and you will receive a response to
continue working.
"""


class DelegationExecutor:
    """Run a sub-agent task on behalf of a calling agent.

    Creates a delegation Session + ReactTask, runs the callee's ReAct loop,
    and returns the final answer to the caller. Supports CLARIFY pausing:
    when the sub-agent issues a CLARIFY action, the delegation session is
    kept alive and the caller can resume by providing a response.
    """

    def __init__(self, db: DBSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # New delegation
    # ------------------------------------------------------------------

    async def execute_delegation(
        self,
        *,
        caller_context: ToolExecutionContext,
        caller_task_id: str,
        caller_agent_id: int,
        delegation_depth: int,
        delegation: AgentDelegation,
        instruction: str,
        on_event: Any | None = None,
    ) -> dict[str, Any]:
        """Execute a new delegation by creating and running a sub-agent task.

        Args:
            caller_context: The tool execution context of the calling agent.
            caller_task_id: UUID of the parent ReactTask.
            caller_agent_id: ID of the agent that initiated the delegation.
            delegation_depth: Current nesting depth (parent's depth).
            delegation: The AgentDelegation row configuring this call.
            instruction: The task instruction for the sub-agent.
            on_event: Optional async callback for delegation SSE events.

        Returns:
            Dict with status, answer, iterations, and token usage.
            status is "completed" on success, "clarify" if sub-agent
            asks a question, or includes an error key on failure.

        Raises:
            ValueError: If delegation depth exceeds the limit.
        """
        if delegation_depth >= MAX_DELEGATION_DEPTH:
            raise ValueError(
                f"Delegation depth {delegation_depth} exceeds "
                f"maximum allowed depth {MAX_DELEGATION_DEPTH}"
            )

        callee_agent = AgentService(self.db).get_agent(delegation.callee_agent_id)
        if callee_agent is None or callee_agent.id is None:
            raise ValueError(f"Callee agent {delegation.callee_agent_id} not found")
        callee_agent_id: int = callee_agent.id

        runtime_config = AgentReleaseRuntimeService(self.db).resolve_for_agent(
            delegation.callee_agent_id
        )

        from app.crud.llm import llm as llm_crud
        from app.llm.llm_factory import create_llm_from_config
        from app.orchestration.react.engine import ReactEngine
        from app.orchestration.tool.manager import ToolExecutionContext
        from app.services.extension_service import ExtensionService

        request_tool_manager = ExtensionService(self.db).build_request_tool_manager(
            user_id=caller_context.user_id,
            agent_id=callee_agent_id,
            raw_tool_ids=runtime_config.raw_tool_ids,
            extension_bundle=runtime_config.extension_bundle,
        )

        session_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        delegation_session = Session(
            session_id=session_id,
            agent_id=callee_agent_id,
            type="delegation",
            user_id=caller_context.user_id,
            status="active",
            runtime_status="running",
            parent_task_id=caller_task_id,
            parent_agent_id=caller_agent_id,
            title=f"Delegation: {caller_agent_id} → {callee_agent.name}",
            chat_history='{"version": 1, "messages": []}',
            react_llm_messages="[]",
            react_llm_cache_state="{}",
            created_at=now,
            updated_at=now,
        )
        self.db.add(delegation_session)

        max_iterations = (
            delegation.max_iterations_override
            if delegation.max_iterations_override is not None
            else runtime_config.max_iteration
        )
        child_task = ReactTask(
            task_id=str(uuid.uuid4()),
            session_id=session_id,
            agent_id=callee_agent_id,
            user_id=caller_context.user_id,
            user_message=instruction,
            user_intent=instruction,
            status="pending",
            iteration=0,
            max_iteration=max_iterations,
            parent_task_id=caller_task_id,
            parent_agent_id=caller_agent_id,
            delegation_depth=delegation_depth + 1,
            created_at=now,
            updated_at=now,
        )
        self.db.add(child_task)
        self.db.commit()
        self.db.refresh(child_task)

        logger.info(
            "Delegation started: parent_task=%s → child_task=%s callee=%s depth=%d",
            caller_task_id,
            child_task.task_id,
            callee_agent.name,
            delegation_depth + 1,
        )

        child_context = ToolExecutionContext(
            user_id=caller_context.user_id,
            agent_id=callee_agent_id,
            workspace_id=caller_context.workspace_id,
            workspace_backend_path=caller_context.workspace_backend_path,
            session_id=session_id,
            sandbox_timeout_seconds=delegation.max_timeout_seconds,
            web_search_provider=caller_context.web_search_provider,
            allowed_skills=caller_context.allowed_skills,
            db_session_factory=caller_context.db_session_factory,
        )

        system_prompt = (
            build_runtime_system_prompt(
                skills="[]",
                delegation_agents="",
            )
            + _CLARIFY_PROMPT_SECTION
        )

        if runtime_config.llm_id is None:
            raise ValueError("Callee agent has no LLM configuration")
        llm_config = llm_crud.get(runtime_config.llm_id, self.db)
        if llm_config is None:
            raise ValueError(
                f"LLM configuration with ID {runtime_config.llm_id} not found"
            )
        llm = create_llm_from_config(llm_config)
        max_context_tokens = max(int(llm_config.max_context or 0), 0)

        engine = ReactEngine(
            llm=llm,
            tool_manager=request_tool_manager,
            db=self.db,
            tool_execution_context=child_context,
            stream_llm_responses=False,
        )

        runtime_service = ReactRuntimeService(self.db)
        runtime_service.initialize(task=child_task, system_prompt=system_prompt)

        result = await self._run_sub_agent_loop(
            engine=engine,
            child_task=child_task,
            delegation_session=delegation_session,
            callee_agent_name=callee_agent.name,
            turn_user_message=instruction,
            max_context_tokens=max_context_tokens,
            compact_threshold_percent=runtime_config.compact_threshold_percent,
            on_event=on_event,
        )

        if result["status"] != "clarify":
            self._close_delegation_session(delegation_session)
            self.db.refresh(child_task)
            self.db.commit()

        return result

    # ------------------------------------------------------------------
    # Resume a paused delegation (CLARIFY response)
    # ------------------------------------------------------------------

    async def resume_delegation(
        self,
        *,
        delegation_context_id: str,
        caller_context: ToolExecutionContext,
        response: str,
        on_event: Any | None = None,
    ) -> dict[str, Any]:
        """Resume a paused delegation after the caller answers a CLARIFY.

        Args:
            delegation_context_id: Session ID of the paused delegation.
            caller_context: The tool execution context of the calling agent.
            response: The caller's answer to the sub-agent's CLARIFY question.
            on_event: Optional async callback for delegation SSE events.

        Returns:
            Same result format as execute_delegation.

        Raises:
            ValueError: If the delegation_context_id is invalid or session
                is not in a resumable state.
        """
        from app.crud.llm import llm as llm_crud
        from app.llm.llm_factory import create_llm_from_config
        from app.orchestration.react.engine import ReactEngine
        from app.orchestration.tool.manager import ToolExecutionContext
        from app.services.extension_service import ExtensionService

        delegation_session = self.db.exec(
            select(Session).where(Session.session_id == delegation_context_id)
        ).first()
        if (
            delegation_session is None
            or delegation_session.type != "delegation"
            or delegation_session.status != "active"
        ):
            raise ValueError(
                f"Delegation session {delegation_context_id} not found "
                "or not resumable"
            )

        child_task = self.db.exec(
            select(ReactTask).where(ReactTask.session_id == delegation_context_id)
        ).first()
        if child_task is None:
            raise ValueError(
                f"No task found for delegation session {delegation_context_id}"
            )

        callee_agent_id: int = delegation_session.agent_id
        callee_agent = AgentService(self.db).get_agent(callee_agent_id)
        if callee_agent is None:
            raise ValueError(f"Callee agent {callee_agent_id} not found")

        runtime_config = AgentReleaseRuntimeService(self.db).resolve_for_agent(
            callee_agent_id
        )

        request_tool_manager = ExtensionService(self.db).build_request_tool_manager(
            user_id=caller_context.user_id,
            agent_id=callee_agent_id,
            raw_tool_ids=runtime_config.raw_tool_ids,
            extension_bundle=runtime_config.extension_bundle,
        )

        child_context = ToolExecutionContext(
            user_id=caller_context.user_id,
            agent_id=callee_agent_id,
            workspace_id=caller_context.workspace_id,
            workspace_backend_path=caller_context.workspace_backend_path,
            session_id=delegation_context_id,
            sandbox_timeout_seconds=300,
            web_search_provider=caller_context.web_search_provider,
            allowed_skills=caller_context.allowed_skills,
            db_session_factory=caller_context.db_session_factory,
        )

        if runtime_config.llm_id is None:
            raise ValueError("Callee agent has no LLM configuration")
        llm_config = llm_crud.get(runtime_config.llm_id, self.db)
        if llm_config is None:
            raise ValueError(
                f"LLM configuration with ID {runtime_config.llm_id} not found"
            )
        llm = create_llm_from_config(llm_config)
        max_context_tokens = max(int(llm_config.max_context or 0), 0)

        # Patch the pending action_result to replace the CLARIFY placeholder
        # reply with the caller's actual response. The engine injects this
        # into the first resumed iteration's user payload so the sub-agent LLM
        # sees the answer.
        runtime_svc = ReactRuntimeService(self.db)
        runtime_state = runtime_svc.load(child_task)
        patched = self._patch_clarify_reply(
            runtime_state.pending_action_result, response
        )
        runtime_svc.set_next_action_result(child_task, patched)

        engine = ReactEngine(
            llm=llm,
            tool_manager=request_tool_manager,
            db=self.db,
            tool_execution_context=child_context,
            stream_llm_responses=False,
        )

        delegation_session.runtime_status = "running"
        delegation_session.updated_at = datetime.now(UTC)
        self.db.add(delegation_session)
        self.db.commit()

        logger.info(
            "Delegation resumed: session=%s child_task=%s callee=%s",
            delegation_context_id,
            child_task.task_id,
            callee_agent.name,
        )

        result = await self._run_sub_agent_loop(
            engine=engine,
            child_task=child_task,
            delegation_session=delegation_session,
            callee_agent_name=callee_agent.name,
            turn_user_message=response,
            max_context_tokens=max_context_tokens,
            compact_threshold_percent=runtime_config.compact_threshold_percent,
            on_event=on_event,
        )

        if result["status"] != "clarify":
            self._close_delegation_session(delegation_session)
            self.db.refresh(child_task)
            self.db.commit()

        return result

    # ------------------------------------------------------------------
    # Shared sub-agent event loop
    # ------------------------------------------------------------------

    async def _run_sub_agent_loop(
        self,
        *,
        engine: ReactEngine,
        child_task: ReactTask,
        delegation_session: Session,
        callee_agent_name: str,
        turn_user_message: str,
        max_context_tokens: int,
        compact_threshold_percent: int,
        on_event: Any | None = None,
    ) -> dict[str, Any]:
        """Run the sub-agent's ReAct loop and handle ANSWER / CLARIFY / error.

        Returns:
            Result dict. ``status`` is ``"completed"``, ``"clarify"``, or
            ``"error"``.
        """
        final_answer: str | None = None
        clarify_question: str | None = None
        iteration_count = 0

        token_usage = {
            "total_tokens": child_task.total_tokens,
            "prompt_tokens": child_task.total_prompt_tokens,
            "completion_tokens": child_task.total_completion_tokens,
        }

        if on_event is not None:
            await on_event(
                _delegation_event(
                    "delegation_start",
                    delegated_agent=callee_agent_name,
                    instruction=turn_user_message,
                )
            )

        try:
            async for event_data in engine.run_task(
                task=child_task,
                turn_user_message=turn_user_message,
                max_context_tokens=max_context_tokens,
                compact_threshold_percent=compact_threshold_percent,
            ):
                event_type = event_data.get("type")

                if event_type == "recursion_start":
                    iteration_count += 1

                elif event_type == "answer":
                    answer_data = event_data.get("data")
                    if isinstance(answer_data, dict):
                        final_answer = answer_data.get("answer", "")
                    elif isinstance(answer_data, str):
                        final_answer = answer_data

                elif event_type == "clarify":
                    clarify_data = event_data.get("data", {})
                    if isinstance(clarify_data, dict):
                        clarify_question = clarify_data.get("question", "")
                    elif isinstance(clarify_data, str):
                        clarify_question = clarify_data

        except Exception as e:
            logger.error(
                "Delegation failed: child_task=%s error=%s",
                child_task.task_id,
                e,
            )
            self._close_delegation_session(delegation_session)
            self.db.refresh(child_task)
            self.db.commit()
            token_usage = _refreshed_token_usage(child_task)
            if on_event is not None:
                await on_event(
                    _delegation_event(
                        "delegation_error",
                        delegated_agent=callee_agent_name,
                        error=str(e),
                        iterations=iteration_count,
                        token_usage=token_usage,
                    )
                )
            return {
                "status": "error",
                "delegated_agent": callee_agent_name,
                "answer": f"Delegation failed: {e}",
                "iterations": iteration_count,
                "token_usage": token_usage,
            }

        # Refresh token usage after loop completes.
        self.db.refresh(child_task)
        token_usage = _refreshed_token_usage(child_task)

        # Sub-agent issued CLARIFY — keep session alive for resume.
        if clarify_question is not None:
            logger.info(
                "Delegation paused (clarify): child_task=%s question=%s",
                child_task.task_id,
                clarify_question[:100],
            )
            delegation_session.runtime_status = "idle"
            delegation_session.updated_at = datetime.now(UTC)
            self.db.add(delegation_session)
            self.db.commit()
            if on_event is not None:
                await on_event(
                    _delegation_event(
                        "delegation_clarify",
                        delegated_agent=callee_agent_name,
                        question=clarify_question,
                        delegation_context_id=delegation_session.session_id,
                        iterations=iteration_count,
                        token_usage=token_usage,
                    )
                )
            return {
                "status": "clarify",
                "delegated_agent": callee_agent_name,
                "question": clarify_question,
                "delegation_context_id": delegation_session.session_id,
                "iterations": iteration_count,
                "token_usage": token_usage,
            }

        # Normal completion.
        logger.info(
            "Delegation completed: child_task=%s iterations=%d tokens=%d",
            child_task.task_id,
            iteration_count,
            child_task.total_tokens,
        )
        if on_event is not None:
            await on_event(
                _delegation_event(
                    "delegation_result",
                    delegated_agent=callee_agent_name,
                    answer=final_answer or "",
                    iterations=iteration_count,
                    token_usage=token_usage,
                )
            )
        return {
            "status": "completed",
            "delegated_agent": callee_agent_name,
            "answer": final_answer or "",
            "iterations": iteration_count,
            "token_usage": token_usage,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _patch_clarify_reply(
        pending: list[dict[str, Any]] | None,
        reply_text: str,
    ) -> list[dict[str, Any]]:
        """Replace the CLARIFY placeholder reply with the actual response.

        The engine stores the CLARIFY output as the pending action_result for
        the next iteration. The ``reply`` field contains a placeholder string
        that must be replaced with the caller's actual response before the
        sub-agent's ReAct loop resumes.

        Args:
            pending: Stored pending action_result from the CLARIFY iteration.
            reply_text: The caller agent's response to inject.

        Returns:
            Patched action_result list, or an empty list fallback.
        """
        if not pending:
            return [{"result": {"reply": reply_text}}]
        patched = []
        for item in pending:
            result = dict(item.get("result", {}))
            result["reply"] = reply_text
            patched.append({"result": result})
        return patched

    def _close_delegation_session(self, delegation_session: Session) -> None:
        """Mark the delegation session as closed."""
        fresh = self.db.get(Session, delegation_session.id)
        if fresh is not None:
            fresh.status = "closed"
            fresh.runtime_status = "idle"
            fresh.updated_at = datetime.now(UTC)
            self.db.add(fresh)
