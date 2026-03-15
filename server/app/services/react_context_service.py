"""Prompt-context estimation helpers for ReAct chat surfaces."""

from __future__ import annotations

import json
from typing import Any

from app.config import get_settings
from app.crud.llm import llm as llm_crud
from app.llm.token_estimator import estimate_messages_tokens
from app.models.agent import Agent
from app.models.react import ReactTask
from app.orchestration.react.context import ReactContext
from app.orchestration.react.prompt_template import build_runtime_system_prompt
from app.orchestration.tool import get_tool_manager
from app.orchestration.tool.manager import ToolManager
from app.schemas.react import ReactContextUsageResponse
from app.services.file_service import FileService
from app.services.react_runtime_service import ReactRuntimeService
from app.services.session_memory_service import SessionMemoryService
from app.services.workspace_service import (
    ensure_agent_workspace,
    load_all_user_tool_metadata,
)
from sqlmodel import Session as DBSession, select


class ReactContextUsageService:
    """Estimate ReAct prompt usage for active tasks and next-turn previews."""

    def __init__(self, db: DBSession) -> None:
        """Initialize the service with a database session.

        Args:
            db: Database session used to load agent, task, and session state.
        """
        self.db = db
        self.runtime_service = ReactRuntimeService(db)
        self.file_service = FileService(db)

    def estimate(
        self,
        *,
        agent_id: int,
        username: str,
        session_id: str | None = None,
        task_id: str | None = None,
        draft_message: str = "",
        file_ids: list[str] | None = None,
    ) -> ReactContextUsageResponse:
        """Estimate the prompt window used by the current chat surface.

        Args:
            agent_id: Agent whose prompt should be estimated.
            username: Authenticated username used for private tool and file access.
            session_id: Optional conversation session for session-memory lookup.
            task_id: Optional active task whose runtime messages should be measured.
            draft_message: Current unsent composer text.
            file_ids: Uploaded file IDs that should contribute prompt blocks.

        Returns:
            Structured prompt-usage estimate for the chat surface.

        Raises:
            ValueError: If the agent, LLM, task, or files cannot be resolved.
        """
        agent = self.db.get(Agent, agent_id)
        if agent is None:
            raise ValueError(f"Agent {agent_id} not found.")
        if agent.llm_id is None:
            raise ValueError(f"Agent {agent.name} has no LLM configured.")

        llm_config = llm_crud.get(agent.llm_id, self.db)
        if llm_config is None:
            raise ValueError(f"LLM configuration {agent.llm_id} not found.")

        normalized_file_ids = self._normalize_file_ids(file_ids or [])
        attachment_blocks = self._build_attachment_blocks(
            file_ids=normalized_file_ids,
            username=username,
        )

        task = (
            self._load_task(task_id, agent_id=agent_id, username=username)
            if task_id
            else None
        )
        effective_session_id = session_id or (task.session_id if task else None)

        messages: list[dict[str, Any]]
        estimation_mode = "next_turn_preview"
        draft_tokens = 0

        if task is not None:
            runtime_state = self.runtime_service.load(task)
            messages = [dict(message) for message in runtime_state.messages]
            if messages:
                estimation_mode = "active_task"
                if draft_message or attachment_blocks:
                    draft_message_payload = self._build_task_user_payload(
                        task=task,
                        draft_message=draft_message,
                        pending_action_result=runtime_state.pending_action_result,
                    )
                    draft_message_object = self._build_user_message(
                        payload=draft_message_payload,
                        attachment_blocks=attachment_blocks,
                    )
                    messages.append(draft_message_object)
                    draft_tokens = estimate_messages_tokens([draft_message_object])
                    estimation_mode = (
                        "reply_preview"
                        if task.status == "waiting_input"
                        else "next_iteration_preview"
                    )
            else:
                messages = self._build_new_task_messages(
                    agent=agent,
                    username=username,
                    session_id=effective_session_id,
                    draft_message=draft_message,
                    attachment_blocks=attachment_blocks,
                )
                if len(messages) > 1:
                    draft_tokens = estimate_messages_tokens([messages[-1]])
        else:
            messages = self._build_new_task_messages(
                agent=agent,
                username=username,
                session_id=effective_session_id,
                draft_message=draft_message,
                attachment_blocks=attachment_blocks,
            )
            if len(messages) > 1:
                draft_tokens = estimate_messages_tokens([messages[-1]])

        used_tokens = estimate_messages_tokens(messages)
        max_context_tokens = max(int(llm_config.max_context or 0), 0)
        remaining_tokens = max(max_context_tokens - used_tokens, 0)
        used_percent = self._to_percent(used_tokens, max_context_tokens)
        remaining_percent = max(100 - used_percent, 0)

        system_tokens = 0
        if messages and messages[0].get("role") == "system":
            system_tokens = estimate_messages_tokens([messages[0]])
        conversation_tokens = max(used_tokens - system_tokens, 0)

        return ReactContextUsageResponse(
            task_id=task.task_id if task is not None else None,
            session_id=effective_session_id,
            estimation_mode=estimation_mode,
            message_count=len(messages),
            used_tokens=used_tokens,
            remaining_tokens=remaining_tokens,
            max_context_tokens=max_context_tokens,
            used_percent=used_percent,
            remaining_percent=remaining_percent,
            system_tokens=system_tokens,
            conversation_tokens=conversation_tokens,
            draft_tokens=draft_tokens,
        )

    @staticmethod
    def _normalize_file_ids(file_ids: list[str]) -> list[str]:
        """Deduplicate file IDs while preserving their original order."""
        normalized_ids: list[str] = []
        seen_ids: set[str] = set()
        for file_id in file_ids:
            normalized_id = file_id.strip()
            if not normalized_id or normalized_id in seen_ids:
                continue
            seen_ids.add(normalized_id)
            normalized_ids.append(normalized_id)
        return normalized_ids

    def _load_task(
        self,
        task_id: str,
        *,
        agent_id: int,
        username: str,
    ) -> ReactTask:
        """Load one task and ensure it belongs to the current agent."""
        statement = select(ReactTask).where(ReactTask.task_id == task_id)
        task = self.db.exec(statement).first()
        if task is None:
            raise ValueError(f"Task {task_id} not found.")
        if task.agent_id != agent_id:
            raise ValueError("Task does not belong to the requested agent.")
        if task.user not in {username, "web-user"}:
            raise ValueError("Task does not belong to the current user.")
        return task

    def _build_new_task_messages(
        self,
        *,
        agent: Agent,
        username: str,
        session_id: str | None,
        draft_message: str,
        attachment_blocks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Build the initial message list for a brand-new task preview."""
        system_prompt = self._build_system_prompt(
            agent=agent,
            username=username,
            session_id=session_id,
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]

        if draft_message or attachment_blocks:
            payload = {
                "trace_id": "preview",
                "iteration": 1,
                "user_intent": draft_message,
                "current_plan": [],
            }
            messages.append(
                self._build_user_message(
                    payload=payload,
                    attachment_blocks=attachment_blocks,
                )
            )

        return messages

    def _build_system_prompt(
        self,
        *,
        agent: Agent,
        username: str,
        session_id: str | None,
    ) -> str:
        """Build the system prompt used for next-turn context previews."""
        tool_manager = self._build_request_tool_manager(
            username=username,
            agent=agent,
        )
        session_memory = None
        if session_id:
            session_memory = SessionMemoryService(self.db).get_full_session_memory_dict(
                session_id
            )
        return build_runtime_system_prompt(
            tool_manager=tool_manager,
            session_memory=session_memory,
            skills="",
        )

    def _build_request_tool_manager(
        self,
        *,
        username: str,
        agent: Agent,
    ) -> ToolManager:
        """Rebuild the request-scoped tool catalog used in ReAct prompts."""
        ensure_agent_workspace(username, agent.id or 0)

        shared_manager = get_tool_manager()
        request_tool_manager = ToolManager()
        for metadata in shared_manager.list_tools():
            request_tool_manager.add_entry(metadata)

        private_metas = load_all_user_tool_metadata(username)
        for metadata in private_metas:
            if request_tool_manager.get_tool(metadata.name) is None:
                request_tool_manager.add_entry(metadata)

        allowed_tool_names = self._parse_name_allowlist(agent.tool_ids)
        if allowed_tool_names is None:
            return request_tool_manager

        filtered_manager = ToolManager()
        for metadata in request_tool_manager.list_tools():
            if metadata.name in allowed_tool_names:
                filtered_manager.add_entry(metadata)
        return filtered_manager

    @staticmethod
    def _parse_name_allowlist(raw_json: str | None) -> set[str] | None:
        """Parse an optional JSON string allowlist into a set of names."""
        if raw_json is None:
            return None

        text = raw_json.strip()
        if not text:
            return None

        try:
            parsed = json.loads(text)
        except (TypeError, ValueError):
            return set()

        if not isinstance(parsed, list):
            return set()

        result: set[str] = set()
        for item in parsed:
            if isinstance(item, str) and item.strip():
                result.add(item.strip())
        return result

    def _build_attachment_blocks(
        self,
        *,
        file_ids: list[str],
        username: str,
    ) -> list[dict[str, Any]]:
        """Build neutral multimodal blocks for uploaded draft attachments."""
        if not file_ids:
            return []

        files = []
        for file_id in file_ids:
            file_asset = self.file_service.get_file_for_user(file_id, username)
            if file_asset is None:
                raise ValueError(f"File '{file_id}' does not exist.")
            files.append(file_asset)

        return [
            block
            for prepared_file in self.file_service.preprocess_files(files)
            for block in prepared_file.content_blocks
        ]

    def _build_task_user_payload(
        self,
        *,
        task: ReactTask,
        draft_message: str,
        pending_action_result: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        """Build the next user payload using the task's current plan context."""
        context = ReactContext.from_task(task, self.db)
        payload: dict[str, Any] = {
            "trace_id": "preview",
            "iteration": task.iteration + 1,
            "user_intent": draft_message or task.user_intent,
            "current_plan": self._build_current_plan_payload(context),
        }
        if pending_action_result is not None:
            payload["action_result"] = pending_action_result
        return payload

    def _build_current_plan_payload(
        self,
        context: ReactContext,
    ) -> list[dict[str, Any]]:
        """Serialize the active plan into the same compact prompt shape."""
        current_plan: list[dict[str, Any]] = []
        history_limit = max(get_settings().REACT_CURRENT_PLAN_HISTORY_LIMIT, 0)
        for step in context.context.get("plan", []):
            if not isinstance(step, dict):
                continue
            step_id = step.get("step_id")
            if not isinstance(step_id, str):
                continue
            recursion_history: list[dict[str, Any]] = []
            raw_history = step.get("recursion_history", [])
            if isinstance(raw_history, list):
                history_slice = (
                    raw_history[-history_limit:] if history_limit > 0 else []
                )
                for history_entry in history_slice:
                    if not isinstance(history_entry, dict):
                        continue
                    recursion_history.append(
                        {
                            "iteration": history_entry.get("iteration"),
                            "summary": history_entry.get("summary", ""),
                        }
                    )
            current_plan.append(
                {
                    "step_id": step_id,
                    "general_goal": step.get("general_goal", ""),
                    "specific_description": step.get("specific_description", ""),
                    "completion_criteria": step.get("completion_criteria", ""),
                    "status": step.get("status", "pending"),
                    "recursion_history": recursion_history,
                }
            )
        return current_plan

    @staticmethod
    def _build_user_message(
        *,
        payload: dict[str, Any],
        attachment_blocks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Build one user message matching the runtime multimodal payload shape."""
        message_content: str | list[dict[str, Any]] = json.dumps(
            payload,
            ensure_ascii=False,
        )
        if attachment_blocks:
            message_content = [
                {"type": "text", "text": message_content},
                *attachment_blocks,
            ]
        return {"role": "user", "content": message_content}

    @staticmethod
    def _to_percent(used_tokens: int, max_context_tokens: int) -> int:
        """Convert token counts into a rounded usage percentage."""
        if max_context_tokens <= 0:
            return 0
        raw_percent = round((used_tokens / max_context_tokens) * 100)
        return max(min(int(raw_percent), 100), 0)
