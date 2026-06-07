"""Prompt-context estimation helpers for ReAct chat surfaces."""

from __future__ import annotations

import json
from typing import Any

from app.crud.llm import llm as llm_crud
from app.llm.token_estimator import estimate_messages_tokens
from app.models.react import ReactTask
from app.models.session import Session as SessionModel
from app.orchestration.react.context import ReactContext
from app.orchestration.react.prompt_template import (
    build_runtime_payload_message,
    build_runtime_system_prompt,
    build_runtime_task_bootstrap_message,
    build_runtime_user_prompt,
)
from app.orchestration.react.runtime_payload import build_recursion_user_payload
from app.schemas.react import ReactContextUsageResponse
from app.services.agent_release_runtime_service import (
    AgentReleaseRuntimeService,
    AgentRuntimeConfig,
)
from app.services.extension_service import ExtensionService
from app.services.file_service import FileService
from app.services.react_prompt_usage_service import ReactPromptUsageService
from app.services.react_runtime_service import ReactRuntimeService, TaskRuntimeState
from app.services.skill_service import (
    build_mandatory_skills_prompt_json,
    build_skills_metadata_prompt_json,
    build_skills_metadata_prompt_payload,
)
from app.services.workspace_guidance_service import build_workspace_guidance_prompt
from app.services.workspace_service import WorkspaceService
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
        user_id: int,
        session_id: str | None = None,
        task_id: str | None = None,
        draft_message: str = "",
        file_ids: list[str] | None = None,
        session_type: str = "client",
        test_snapshot: dict[str, Any] | None = None,
        mandatory_skill_names: list[str] | None = None,
    ) -> ReactContextUsageResponse:
        """Estimate the prompt window used by the current chat surface.

        Args:
            agent_id: Agent whose prompt should be estimated.
            user_id: Authenticated user ID used for ownership checks and file access.
            session_id: Optional conversation session for session-memory lookup.
            task_id: Optional active task whose runtime messages should be measured.
            draft_message: Current unsent composer text.
            file_ids: Uploaded file IDs that should contribute prompt blocks.
            session_type: Session type used before a session has been created.
            test_snapshot: Optional Studio working-copy snapshot used before the
                first studio_test session is created.
            mandatory_skill_names: Ordered mandatory skill names whose full
                prompt payload should be included in the estimate.

        Returns:
            Structured prompt-usage estimate for the chat surface.

        Raises:
            ValueError: If the agent, LLM, task, or files cannot be resolved.
        """
        normalized_file_ids = self._normalize_file_ids(file_ids or [])
        attachment_blocks = self._build_attachment_blocks(
            file_ids=normalized_file_ids,
            user_id=user_id,
        )

        task = (
            self._load_task(task_id, agent_id=agent_id, user_id=user_id)
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

        runtime_state = (
            self.runtime_service.load(task)
            if task is not None
            else self._load_runtime_state(session_id=effective_session_id)
        )
        messages = [dict(message) for message in runtime_state.messages]
        estimation_mode = "session_runtime"
        draft_tokens = 0
        bootstrap_tokens = 0
        includes_task_bootstrap = False
        preview_messages: list[dict[str, Any]] = []

        if task is not None:
            estimation_mode = "active_task"
            if draft_message or attachment_blocks:
                if mandatory_skill_names:
                    resume_prompt_object = build_runtime_task_bootstrap_message(
                        self._build_user_prompt(
                            runtime_config=runtime_config,
                            user_id=user_id,
                            session_id=effective_session_id,
                            mandatory_skill_names=mandatory_skill_names,
                        ),
                    )
                    preview_messages.append(resume_prompt_object)
                    bootstrap_tokens = estimate_messages_tokens([resume_prompt_object])
                    includes_task_bootstrap = True
                draft_message_payload = self._build_task_user_payload(
                    task=task,
                    draft_message=draft_message,
                    pending_action_result=runtime_state.pending_action_result,
                    after_compaction=runtime_state.compact_result is not None,
                )
                draft_message_object = build_runtime_payload_message(
                    draft_message_payload,
                    attachments=attachment_blocks,
                )
                preview_messages.append(draft_message_object)
                draft_tokens = estimate_messages_tokens([draft_message_object])
                estimation_mode = (
                    "reply_preview"
                    if task.status == "waiting_input"
                    else "next_iteration_preview"
                )
        elif draft_message or attachment_blocks:
            preview_messages = self._build_new_task_preview_messages(
                runtime_config=runtime_config,
                user_id=user_id,
                session_id=effective_session_id,
                draft_message=draft_message,
                attachment_blocks=attachment_blocks,
                include_system_prompt=(
                    not messages or messages[0].get("role") != "system"
                ),
                mandatory_skill_names=mandatory_skill_names,
            )
            if preview_messages:
                includes_task_bootstrap = True
                if len(preview_messages) >= 1:
                    bootstrap_tokens = estimate_messages_tokens([preview_messages[0]])
                if len(preview_messages) >= 2:
                    draft_tokens = estimate_messages_tokens([preview_messages[1]])
                estimation_mode = "next_turn_preview"

        max_context_tokens = max(int(llm_config.max_context or 0), 0)
        return ReactContextUsageResponse(
            **ReactPromptUsageService.build_usage_summary(
                task_id=task.task_id if task is not None else None,
                session_id=effective_session_id,
                estimation_mode=estimation_mode,
                messages=messages,
                max_context_tokens=max_context_tokens,
                exact_prompt_tokens=runtime_state.exact_prompt_tokens,
                exact_prompt_message_count=runtime_state.exact_prompt_message_count,
                preview_messages=preview_messages,
                bootstrap_tokens=bootstrap_tokens,
                draft_tokens=draft_tokens,
                includes_task_bootstrap=includes_task_bootstrap,
            )
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
        user_id: int,
    ) -> ReactTask:
        """Load one task and verify it belongs to the current agent and user.

        Args:
            task_id: UUID string of the task to load.
            agent_id: Expected agent ID for ownership verification.
            user_id: Expected user ID for ownership verification.

        Returns:
            The loaded ReactTask row.

        Raises:
            ValueError: If the task is not found or does not belong to the
                requested agent or user.
        """
        statement = select(ReactTask).where(ReactTask.task_id == task_id)
        task = self.db.exec(statement).first()
        if task is None:
            raise ValueError(f"Task {task_id} not found.")
        if task.agent_id != agent_id:
            raise ValueError("Task does not belong to the requested agent.")
        if task.user_id != user_id:
            raise ValueError("Task does not belong to the current user.")
        return task

    def _build_new_task_preview_messages(
        self,
        *,
        runtime_config: AgentRuntimeConfig,
        user_id: int,
        session_id: str | None,
        draft_message: str,
        attachment_blocks: list[dict[str, Any]],
        include_system_prompt: bool,
        mandatory_skill_names: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Build preview messages for the next new task in a session.

        Args:
            runtime_config: Resolved agent runtime configuration.
            user_id: Authenticated user ID for skill/tool access resolution.
            session_id: Optional session whose workspace guidance should be injected.
            draft_message: Current unsent composer text.
            attachment_blocks: Pre-built multimodal attachment blocks.
            include_system_prompt: Whether to prepend the system prompt message.
            mandatory_skill_names: Ordered mandatory skill names to include.

        Returns:
            Ordered list of preview messages for token estimation.
        """
        messages: list[dict[str, Any]] = []
        extension_skills = ExtensionService(self.db).build_bundle_skill_payloads(
            runtime_config.extension_bundle
        )
        skills_json = build_skills_metadata_prompt_json(
            self.db,
            user_id,
            raw_skill_ids=runtime_config.raw_skill_ids,
            extra_skills=extension_skills,
        )
        if include_system_prompt:
            messages.append(
                {
                    "role": "system",
                    "content": build_runtime_system_prompt(
                        skills=skills_json,
                    ),
                }
            )

        user_prompt = self._build_user_prompt(
            runtime_config=runtime_config,
            user_id=user_id,
            session_id=session_id,
            mandatory_skill_names=mandatory_skill_names,
        )
        messages.append(build_runtime_task_bootstrap_message(user_prompt))
        payload = {
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
        user_id: int,
        session_id: str | None,
        mandatory_skill_names: list[str] | None = None,
    ) -> str:
        """Build the task bootstrap user prompt used for next-turn previews.

        Args:
            runtime_config: Resolved agent runtime configuration.
            user_id: Authenticated user ID used to look up the username for
                downstream skill and extension services that have not yet been
                migrated to user_id.
            session_id: Optional session whose workspace guidance should be injected.
            mandatory_skill_names: Ordered mandatory skill names to include.

        Returns:
            Rendered user prompt string for the task bootstrap message.
        """
        extension_skills = ExtensionService(self.db).build_bundle_skill_payloads(
            runtime_config.extension_bundle
        )
        return build_runtime_user_prompt(
            mandatory_skills=build_mandatory_skills_prompt_json(
                self.db,
                user_id,
                raw_skill_ids=runtime_config.raw_skill_ids,
                selected_skill_names=mandatory_skill_names or [],
                extra_skills=extension_skills,
            ),
            workspace_guidance=self._build_workspace_guidance(session_id=session_id),
        )

    def _build_workspace_guidance(self, *, session_id: str | None) -> str:
        """Build the active workspace guidance block for one session.

        Args:
            session_id: Session whose workspace guidance should be injected.

        Returns:
            Rendered workspace guidance markdown, or an empty string when the
            session has no runtime workspace or no supported guidance file.
        """
        if session_id is None:
            return ""

        statement = select(SessionModel).where(SessionModel.session_id == session_id)
        session_row = self.db.exec(statement).first()
        if session_row is None or session_row.workspace_id is None:
            return ""

        workspace_service = WorkspaceService(self.db)
        workspace = workspace_service.get_workspace(session_row.workspace_id)
        if workspace is None:
            return ""

        return build_workspace_guidance_prompt(
            workspace_service.get_workspace_path(workspace)
        )

    def list_runtime_skills(
        self,
        *,
        agent_id: int,
        user_id: int,
        session_id: str | None = None,
        session_type: str = "client",
        test_snapshot: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        """List runtime-visible skill metadata for the current chat surface.

        Args:
            agent_id: Agent whose runtime-visible skills should be listed.
            user_id: Authenticated user ID.
            session_id: Optional session ID used for release-pinned resolution.
            session_type: Session type used before a session exists.
            test_snapshot: Optional Studio working-copy snapshot for previews.

        Returns:
            Deterministic list of runtime-visible skill metadata.
        """
        runtime_config = self._resolve_runtime_config(
            agent_id=agent_id,
            session_id=session_id,
            task=None,
            session_type=session_type,
            test_snapshot=test_snapshot,
        )
        extension_skills = ExtensionService(self.db).build_bundle_skill_payloads(
            runtime_config.extension_bundle
        )
        return build_skills_metadata_prompt_payload(
            self.db,
            user_id,
            raw_skill_ids=runtime_config.raw_skill_ids,
            extra_skills=extension_skills,
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
    def _parse_name_allowlist(raw_json: str | None) -> set[str]:
        """Parse an optional JSON string selection into a set of names."""
        if raw_json is None:
            return set()

        text = raw_json.strip()
        if not text:
            return set()

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
        user_id: int,
    ) -> list[dict[str, Any]]:
        """Build neutral multimodal blocks for uploaded draft attachments.

        Args:
            file_ids: Deduplicated file IDs to resolve and preprocess.
            user_id: Authenticated user ID for file ownership verification.

        Returns:
            Flattened list of multimodal content blocks for LLM prompt injection.

        Raises:
            ValueError: If any referenced file does not exist or is not owned by
                the requesting user.
        """
        if not file_ids:
            return []

        files = []
        for file_id in file_ids:
            file_asset = self.file_service.get_file_for_user(file_id, user_id)
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
        after_compaction: bool = False,
    ) -> dict[str, Any]:
        """Build the next user payload using the task's current plan context."""
        context = ReactContext.from_task(task, self.db)
        effective_action_result = self._with_clarify_reply_preview(
            pending_action_result=pending_action_result,
            reply=draft_message,
            task=task,
        )
        return build_recursion_user_payload(
            task,
            context,
            effective_action_result,
            after_compaction=after_compaction,
        )

    def _load_runtime_state(
        self,
        *,
        session_id: str | None,
    ) -> TaskRuntimeState:
        """Load persisted session runtime state when a session exists."""
        if not session_id:
            return TaskRuntimeState(
                messages=[],
                compact_result=None,
                pending_action_result=None,
                previous_response_id=None,
                exact_prompt_tokens=None,
                exact_prompt_message_count=None,
            )
        try:
            return self.runtime_service.load_session(session_id)
        except RuntimeError:
            return TaskRuntimeState(
                messages=[],
                compact_result=None,
                pending_action_result=None,
                previous_response_id=None,
                exact_prompt_tokens=None,
                exact_prompt_message_count=None,
            )

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
