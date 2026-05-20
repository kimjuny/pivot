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

if TYPE_CHECKING:
    from app.models.agent_delegation import AgentDelegation
    from app.orchestration.tool.manager import ToolExecutionContext
    from sqlmodel import Session as DBSession

logger = logging.getLogger(__name__)

MAX_DELEGATION_DEPTH = 3


class DelegationExecutor:
    """Run a sub-agent task on behalf of a calling agent.

    Creates a delegation Session + ReactTask, runs the callee's ReAct loop,
    and returns the final answer to the caller.
    """

    def __init__(self, db: DBSession) -> None:
        self.db = db

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
        """Execute a delegation by creating and running a sub-agent task.

        Args:
            caller_context: The tool execution context of the calling agent.
            caller_task_id: UUID of the parent ReactTask.
            caller_agent_id: ID of the agent that initiated the delegation.
            delegation_depth: Current nesting depth (parent's depth).
            delegation: The AgentDelegation row configuring this call.
            instruction: The task instruction for the sub-agent.
            on_event: Optional async callback for delegation SSE events.

        Returns:
            Dict with answer, iterations, and token usage.

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

        # Resolve callee's runtime config (use live agent config for delegations)
        runtime_config = AgentReleaseRuntimeService(self.db).resolve_for_agent(
            delegation.callee_agent_id
        )

        from app.crud.llm import llm as llm_crud
        from app.llm.llm_factory import create_llm_from_config
        from app.orchestration.react.engine import ReactEngine
        from app.orchestration.tool.manager import ToolExecutionContext
        from app.services.extension_service import ExtensionService

        # Build callee's tool manager
        request_tool_manager = ExtensionService(self.db).build_request_tool_manager(
            user_id=caller_context.user_id,
            agent_id=callee_agent_id,
            raw_tool_ids=runtime_config.raw_tool_ids,
            extension_bundle=runtime_config.extension_bundle,
        )

        # Create delegation session
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

        # Create child ReactTask
        child_task_id = str(uuid.uuid4())
        max_iterations = (
            delegation.max_iterations_override
            if delegation.max_iterations_override is not None
            else runtime_config.max_iteration
        )
        child_task = ReactTask(
            task_id=child_task_id,
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
            child_task_id,
            callee_agent.name,
            delegation_depth + 1,
        )

        # Build sub-agent execution context
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

        # Build system prompt with delegation section (sub-agent should NOT
        # see the caller's delegation list to avoid confusion)
        system_prompt = build_runtime_system_prompt(
            tool_manager=request_tool_manager,
            skills="[]",
            delegation_agents="",
        )

        if runtime_config.llm_id is None:
            raise ValueError("Callee agent has no LLM configuration")
        llm_config = llm_crud.get(runtime_config.llm_id, self.db)
        if llm_config is None:
            raise ValueError(
                f"LLM configuration with ID {runtime_config.llm_id} not found"
            )
        llm = create_llm_from_config(llm_config)

        engine = ReactEngine(
            llm=llm,
            tool_manager=request_tool_manager,
            db=self.db,
            tool_execution_context=child_context,
            stream_llm_responses=False,
        )

        # Initialize the runtime window with the system prompt
        runtime_service = ReactRuntimeService(self.db)
        runtime_service.initialize(task=child_task, system_prompt=system_prompt)

        final_answer: str | None = None
        iteration_count = 0
        try:
            async for event_data in engine.run_task(
                task=child_task,
                turn_user_message=instruction,
            ):
                event_type = event_data.get("type")
                if event_type == "recursion":
                    iteration_count += 1
                if event_type == "answer":
                    answer_data = event_data.get("data")
                    if isinstance(answer_data, dict):
                        final_answer = answer_data.get("answer", "")
                    elif isinstance(answer_data, str):
                        final_answer = answer_data
                if on_event is not None:
                    await on_event(event_data)
        except Exception as e:
            logger.error(
                "Delegation failed: child_task=%s error=%s",
                child_task_id,
                e,
            )
            final_answer = f"Delegation failed: {e}"

        # Close delegation session
        delegation_session = self.db.get(Session, delegation_session.id)
        if delegation_session is not None:
            delegation_session.status = "closed"
            delegation_session.runtime_status = "idle"
            delegation_session.updated_at = datetime.now(UTC)
            self.db.add(delegation_session)

        # Refresh child task for final token counts
        self.db.refresh(child_task)
        self.db.commit()

        logger.info(
            "Delegation completed: child_task=%s iterations=%d tokens=%d",
            child_task_id,
            iteration_count,
            child_task.total_tokens,
        )

        return {
            "delegated_agent": callee_agent.name,
            "answer": final_answer or "",
            "iterations": iteration_count,
            "token_usage": {
                "total_tokens": child_task.total_tokens,
                "prompt_tokens": child_task.total_prompt_tokens,
                "completion_tokens": child_task.total_completion_tokens,
            },
        }
