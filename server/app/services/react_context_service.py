"""Prompt-context estimation helpers for ReAct chat surfaces."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from app.config import get_settings
from app.crud.llm import llm as llm_crud
from app.llm.token_estimator import estimate_messages_tokens
from app.models.react import ReactTask
from app.orchestration.react.context import ReactContext
from app.orchestration.react.prompt_template import (
    build_runtime_payload_message,
    build_runtime_system_prompt,
    build_runtime_task_bootstrap_message,
    build_runtime_user_prompt,
)
from app.schemas.react import ReactContextUsageResponse
from app.services.agent_release_runtime_service import (
    AgentReleaseRuntimeService,
    AgentRuntimeConfig,
)
from app.services.extension_service import ExtensionService
from app.services.file_service import FileService
from app.services.react_runtime_service import ReactRuntimeService
from sqlmodel import Session as DBSession, select

if TYPE_CHECKING:
    from app.orchestration.tool.manager import ToolManager


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
        session_type: str = "consumer",
        test_snapshot: dict[str, Any] | None = None,
    ) -> ReactContextUsageResponse:
        """Estimate the prompt window used by the current chat surface.

        Args:
            agent_id: Agent whose prompt should be estimated.
            username: Authenticated username used for private tool and file access.
            session_id: Optional conversation session for session-memory lookup.
            task_id: Optional active task whose runtime messages should be measured.
            draft_message: Current unsent composer text.
            file_ids: Uploaded file IDs that should contribute prompt blocks.
            session_type: Session type used before a session has been created.
            test_snapshot: Optional Studio working-copy snapshot used before the
                first studio_test session is created.

        Returns:
            Structured prompt-usage estimate for the chat surface.

        Raises:
            ValueError: If the agent, LLM, task, or files cannot be resolved.
        """
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
        runtime_config = self._resolve_runtime_config(
            agent_id=agent_id,
            session_id=effective_session_id,
            task=task,
            session_type=session_type,
            test_snapshot=test_snapshot,
        )
        if runtime_config.llm_id is None:
            raise ValueError(
                f"Agent {runtime_config.agent_name} has no LLM configured."
            )

        llm_config = llm_crud.get(runtime_config.llm_id, self.db)
        if llm_config is None:
            raise ValueError(f"LLM configuration {runtime_config.llm_id} not found.")

        base_messages = self._load_session_runtime_messages(
            session_id=effective_session_id,
        )
        messages = [dict(message) for message in base_messages]
        estimation_mode = "session_runtime"
        draft_tokens = 0
        bootstrap_tokens = 0
        preview_tokens = 0
        includes_task_bootstrap = False

        if task is not None:
            runtime_state = self.runtime_service.load(task)
            messages = [dict(message) for message in runtime_state.messages]
            base_messages = [dict(message) for message in runtime_state.messages]
            estimation_mode = "active_task"
            if draft_message or attachment_blocks:
                draft_message_payload = self._build_task_user_payload(
                    task=task,
                    draft_message=draft_message,
                    pending_action_result=runtime_state.pending_action_result,
                )
                draft_message_object = build_runtime_payload_message(
                    draft_message_payload,
                    attachments=attachment_blocks,
                )
                messages.append(draft_message_object)
                draft_tokens = estimate_messages_tokens([draft_message_object])
                estimation_mode = (
                    "reply_preview"
                    if task.status == "waiting_input"
                    else "next_iteration_preview"
                )
        elif draft_message or attachment_blocks:
            preview_messages = self._build_new_task_preview_messages(
                runtime_config=runtime_config,
                username=username,
                session_id=effective_session_id,
                draft_message=draft_message,
                attachment_blocks=attachment_blocks,
                include_system_prompt=(
                    not messages or messages[0].get("role") != "system"
                ),
            )
            if preview_messages:
                messages.extend(preview_messages)
                includes_task_bootstrap = True
                if len(preview_messages) >= 1:
                    bootstrap_tokens = estimate_messages_tokens([preview_messages[0]])
                if len(preview_messages) >= 2:
                    draft_tokens = estimate_messages_tokens([preview_messages[1]])
                estimation_mode = "next_turn_preview"

        session_tokens = estimate_messages_tokens(base_messages)
        used_tokens = estimate_messages_tokens(messages)
        preview_tokens = max(used_tokens - session_tokens, 0)
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
            session_message_count=len(base_messages),
            used_tokens=used_tokens,
            remaining_tokens=remaining_tokens,
            max_context_tokens=max_context_tokens,
            used_percent=used_percent,
            remaining_percent=remaining_percent,
            system_tokens=system_tokens,
            conversation_tokens=conversation_tokens,
            session_tokens=session_tokens,
            preview_tokens=preview_tokens,
            bootstrap_tokens=bootstrap_tokens,
            draft_tokens=draft_tokens,
            includes_task_bootstrap=includes_task_bootstrap,
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

    def _build_new_task_preview_messages(
        self,
        *,
        runtime_config: AgentRuntimeConfig,
        username: str,
        session_id: str | None,
        draft_message: str,
        attachment_blocks: list[dict[str, Any]],
        include_system_prompt: bool,
    ) -> list[dict[str, Any]]:
        """Build preview messages for the next new task in a session."""
        messages: list[dict[str, Any]] = []
        if include_system_prompt:
            messages.append(
                {"role": "system", "content": build_runtime_system_prompt()}
            )

        user_prompt = self._build_user_prompt(
            runtime_config=runtime_config,
            username=username,
            session_id=session_id,
        )
        messages.append(build_runtime_task_bootstrap_message(user_prompt))
        payload = {
            "trace_id": "preview",
            "iteration": 1,
            "user_intent": draft_message,
            "current_plan": [],
        }
        messages.append(
            build_runtime_payload_message(
                payload,
                attachments=attachment_blocks,
            )
        )
        return messages

    def _build_user_prompt(
        self,
        *,
        runtime_config: AgentRuntimeConfig,
        username: str,
        session_id: str | None,
    ) -> str:
        """Build the task bootstrap user prompt used for next-turn previews."""
        tool_manager = self._build_request_tool_manager(
            username=username,
            runtime_config=runtime_config,
        )
        return build_runtime_user_prompt(
            tool_manager=tool_manager,
            skills="",
        )

    def _build_request_tool_manager(
        self,
        *,
        username: str,
        runtime_config: AgentRuntimeConfig,
    ) -> ToolManager:
        """Rebuild the request-scoped tool catalog used in ReAct prompts."""
        return ExtensionService(self.db).build_request_tool_manager(
            username=username,
            agent_id=runtime_config.agent_id,
            raw_tool_ids=runtime_config.raw_tool_ids,
            extension_bundle=runtime_config.extension_bundle,
        )

    def _resolve_runtime_config(
        self,
        *,
        agent_id: int,
        session_id: str | None,
        task: ReactTask | None,
        session_type: str,
        test_snapshot: dict[str, Any] | None,
    ) -> AgentRuntimeConfig:
        """Resolve the effective runtime config for prompt estimation.

        Args:
            agent_id: Requested agent identifier from the API payload.
            session_id: Optional session driving release-pinned estimation.
            task: Optional active task that already belongs to one session.
            session_type: Session type used before a session exists.
            test_snapshot: Optional Studio working-copy snapshot for draft previews.

        Returns:
            Effective runtime config for the estimation request.

        Raises:
            ValueError: If the session does not belong to the requested agent.
        """
        runtime_service = AgentReleaseRuntimeService(self.db)
        if task is not None:
            runtime_config = runtime_service.resolve_for_task(task)
        elif session_id:
            runtime_config = runtime_service.resolve_for_session(session_id)
        elif session_type == "studio_test" and test_snapshot is not None:
            runtime_config = runtime_service.resolve_for_test_payload(
                agent_id=agent_id,
                working_copy_snapshot=test_snapshot,
            )
        else:
            runtime_config = runtime_service.resolve_for_agent(agent_id)

        if runtime_config.agent_id != agent_id:
            raise ValueError("Session does not belong to the requested agent.")
        return runtime_config

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
        effective_action_result = self._with_clarify_reply_preview(
            pending_action_result=pending_action_result,
            reply=draft_message,
            task=task,
        )
        payload: dict[str, Any] = {
            "trace_id": "preview",
            "iteration": task.iteration + 1,
            "user_intent": task.user_intent,
            "current_plan": self._build_current_plan_payload(context),
        }
        if effective_action_result is not None:
            payload["action_result"] = effective_action_result
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

    def _load_session_runtime_messages(
        self,
        *,
        session_id: str | None,
    ) -> list[dict[str, Any]]:
        """Load persisted session runtime messages when a session exists."""
        if not session_id:
            return []
        try:
            runtime_state = self.runtime_service.load_session(session_id)
        except RuntimeError:
            return []
        return [dict(message) for message in runtime_state.messages]

    @staticmethod
    def _with_clarify_reply_preview(
        *,
        pending_action_result: list[dict[str, Any]] | None,
        reply: str,
        task: ReactTask,
    ) -> list[dict[str, Any]] | None:
        """Project the draft clarify reply into the pending action_result preview.

        Why: the persisted runtime state does not include the user's unsent
        clarify reply yet, but the composer preview should reflect the exact
        payload shape that will be submitted once the user sends it.
        """
        if not pending_action_result:
            return None
        if task.status != "waiting_input" or not reply:
            return pending_action_result

        preview_results: list[dict[str, Any]] = []
        for item in pending_action_result:
            if not isinstance(item, dict):
                continue
            preview_item = dict(item)
            result_value = preview_item.get("result")
            if isinstance(result_value, dict):
                preview_item["result"] = {
                    **result_value,
                    "reply": reply,
                }
            preview_results.append(preview_item)
        return preview_results

    @staticmethod
    def _to_percent(used_tokens: int, max_context_tokens: int) -> int:
        """Convert token counts into a rounded usage percentage."""
        if max_context_tokens <= 0:
            return 0
        raw_percent = round((used_tokens / max_context_tokens) * 100)
        return max(min(int(raw_percent), 100), 0)
