"""ReAct Engine - Core execution engine for ReAct state machine.

This module implements the main execution loop for the ReAct agent,
handling recursion cycles, tool calling, and state management.
"""

import asyncio
import contextlib
import json
import logging
import re
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from time import perf_counter
from typing import TYPE_CHECKING, Any

from app.config import get_settings
from app.crud.llm import llm as llm_crud
from app.llm.abstract_llm import AbstractLLM, ChatMessage, Choice, Response, UsageInfo
from app.llm.token_estimator import estimate_messages_tokens, estimate_text_tokens
from app.llm.usage_accumulator import StreamingUsageAccumulator, usage_to_token_counter
from app.models.agent import Agent
from app.models.react import (
    ReactRecursion,
    ReactTask,
)
from app.orchestration.compact.compact_prompt import COMPACT_PROMPT
from app.orchestration.tool.manager import ToolExecutionContext, ToolManager
from app.schemas.file import FileAssetListItem
from app.services.react_runtime_service import ReactRuntimeService, TaskRuntimeState
from app.services.react_state_service import ReactStateService
from app.services.session_service import SessionService
from app.services.task_attachment_service import TaskAttachmentService
from fastapi.concurrency import run_in_threadpool
from sqlmodel import Session

from .context import ReactContext
from .parser import (
    PARSE_RETRY_INSTRUCTION,
    PARSE_RETRY_LIMIT,
    parse_react_output,
    safe_load_json,
)
from .prompt_template import build_runtime_system_prompt, build_runtime_user_prompt

if TYPE_CHECKING:
    from .types import ParsedReactDecision

# Get logger for this module
logger = logging.getLogger(__name__)


class ReactEngine:
    """ReAct state machine execution engine.

    This class implements the core ReAct execution loop, managing:
    - Recursion cycles
    - LLM interactions with tool calling
    - Tool execution
    - State persistence
    """

    def __init__(
        self,
        llm: AbstractLLM,
        tool_manager: ToolManager,
        db: Session,
        tool_execution_context: ToolExecutionContext | None = None,
        stream_llm_responses: bool = True,
        llm_runtime_kwargs: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize ReAct engine.

        Args:
            llm: Language model instance for ReAct reasoning
            tool_manager: Tool manager for executing tool calls
            db: Database session for persistence
        """
        self.llm = llm
        self.tool_manager = tool_manager
        self.db = db
        self.tool_execution_context = tool_execution_context
        self.stream_llm_responses = stream_llm_responses
        self.llm_runtime_kwargs = llm_runtime_kwargs or {}
        self.runtime_service = ReactRuntimeService(db)
        self.state_service = ReactStateService(db)
        self.cancelled = False  # Flag to signal cancellation

    def _new_token_counter(self) -> dict[str, int]:
        """Create a token counter used across parse retries.

        Returns:
            A mutable token counter dictionary.
        """
        return {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cached_input_tokens": 0,
        }

    def _accumulate_usage(
        self, token_counter: dict[str, int], usage: Any | None
    ) -> None:
        """Accumulate one finalized usage payload into ``token_counter``.

        Args:
            token_counter: Mutable token tally shared by one recursion.
            usage: Usage object returned by LLM response (may be None).
        """
        if usage is None:
            return

        self._accumulate_token_counter(
            token_counter,
            usage_to_token_counter(usage),
        )

    def _accumulate_token_counter(
        self,
        token_counter: dict[str, int],
        usage_counter: dict[str, int],
    ) -> None:
        """Accumulate normalized token counts into ``token_counter``.

        Args:
            token_counter: Mutable token tally shared by one recursion.
            usage_counter: Normalized token counts from one completed request.
        """
        token_counter["prompt_tokens"] += int(
            usage_counter.get("prompt_tokens", 0) or 0
        )
        token_counter["completion_tokens"] += int(
            usage_counter.get("completion_tokens", 0) or 0
        )
        token_counter["total_tokens"] += int(usage_counter.get("total_tokens", 0) or 0)
        token_counter["cached_input_tokens"] += int(
            usage_counter.get("cached_input_tokens", 0) or 0
        )

    def _ensure_total_tokens(self, token_counter: dict[str, int]) -> None:
        """Backfill ``total_tokens`` when providers omit it in usage payloads."""
        if token_counter["total_tokens"] > 0:
            return

        inferred_total = (
            token_counter["prompt_tokens"] + token_counter["completion_tokens"]
        )
        if inferred_total > 0:
            token_counter["total_tokens"] = inferred_total

    def _persist_answer_attachments(
        self,
        *,
        task: ReactTask,
        action_output: dict[str, Any],
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Normalize and persist assistant attachments declared on an answer."""
        normalized_output = dict(action_output)
        declared_paths = TaskAttachmentService.extract_declared_paths(normalized_output)
        normalized_output.pop("attatchments", None)

        if not declared_paths:
            normalized_output["attachments"] = []
            return normalized_output, []

        attachment_service = TaskAttachmentService(self.db)
        attachments = attachment_service.create_from_answer_paths(
            username=task.user,
            agent_id=task.agent_id,
            task_id=task.task_id,
            session_id=task.session_id,
            paths=declared_paths,
        )
        public_payload = attachment_service.to_event_payload(attachments)
        normalized_output["attachments"] = public_payload
        return normalized_output, public_payload

    @staticmethod
    def _to_percent(used_tokens: int, max_context_tokens: int) -> int:
        """Convert token counts into a bounded integer percentage."""
        if max_context_tokens <= 0:
            return 0
        raw_percent = round((used_tokens / max_context_tokens) * 100)
        return max(min(int(raw_percent), 100), 0)

    def _build_usage_snapshot(
        self,
        *,
        task: ReactTask,
        messages: list[dict[str, Any]],
        max_context_tokens: int,
    ) -> dict[str, Any]:
        """Build a context-usage snapshot for runtime events and decisions."""
        used_tokens = estimate_messages_tokens(messages)
        remaining_tokens = max(max_context_tokens - used_tokens, 0)
        used_percent = self._to_percent(used_tokens, max_context_tokens)
        system_tokens = 0
        if messages and messages[0].get("role") == "system":
            system_tokens = estimate_messages_tokens([messages[0]])
        conversation_tokens = max(used_tokens - system_tokens, 0)
        return {
            "task_id": task.task_id,
            "session_id": task.session_id,
            "estimation_mode": "active_task",
            "message_count": len(messages),
            "session_message_count": len(messages),
            "used_tokens": used_tokens,
            "remaining_tokens": remaining_tokens,
            "max_context_tokens": max_context_tokens,
            "used_percent": used_percent,
            "remaining_percent": max(100 - used_percent, 0),
            "system_tokens": system_tokens,
            "conversation_tokens": conversation_tokens,
            "session_tokens": used_tokens,
            "preview_tokens": 0,
            "bootstrap_tokens": 0,
            "draft_tokens": 0,
            "includes_task_bootstrap": False,
        }

    async def _execute_compaction(
        self,
        *,
        task: ReactTask,
        source_messages: list[dict[str, Any]],
    ) -> tuple[str, dict[str, int]]:
        """Run one compact-model call over the provided runtime messages."""
        compact_messages = [dict(message) for message in source_messages]
        compact_messages.append({"role": "user", "content": COMPACT_PROMPT})

        response = await run_in_threadpool(
            self.llm.chat,
            compact_messages,
            _pivot_task_id=task.task_id,
        )
        token_counter = self._new_token_counter()
        self._accumulate_usage(token_counter, response.usage)
        self._ensure_total_tokens(token_counter)

        content = response.first().message.content or "{}"
        compact_payload = safe_load_json(content)
        compact_result = json.dumps(compact_payload, ensure_ascii=False)
        return compact_result, token_counter

    async def _maybe_compact_runtime_window(
        self,
        *,
        task: ReactTask,
        runtime_state: TaskRuntimeState,
        system_prompt: str,
        max_context_tokens: int,
        threshold_percent: int,
        reason: str,
    ) -> tuple[TaskRuntimeState, list[dict[str, Any]]]:
        """Compact the runtime prompt window when the configured threshold is hit."""
        if max_context_tokens <= 0 or threshold_percent <= 0:
            return runtime_state, []

        usage_before = self._build_usage_snapshot(
            task=task,
            messages=runtime_state.messages,
            max_context_tokens=max_context_tokens,
        )
        if usage_before["used_percent"] < threshold_percent:
            return runtime_state, []

        original_messages = [dict(message) for message in runtime_state.messages]
        original_compact_result = runtime_state.compact_result

        if reason == "task_start_threshold":
            prefix_messages = runtime_state.messages
            stashed_messages: list[dict[str, Any]] = []
        else:
            task_start_index = max(task.runtime_message_start_index, 0)
            prefix_messages = runtime_state.messages[:task_start_index]
            stashed_messages = [
                dict(message)
                for message in runtime_state.messages[task_start_index:]
                if message.get("role") != "system"
            ]

        source_messages = [
            dict(message)
            for message in prefix_messages
            if message.get("role") != "system"
        ]
        if not source_messages:
            return runtime_state, []
        if (
            runtime_state.compact_result is not None
            and len(source_messages) == 1
            and source_messages[0].get("role") == "assistant"
            and source_messages[0].get("content") == runtime_state.compact_result
        ):
            return runtime_state, []

        events = [
            {
                "type": "compact_start",
                "task_id": task.task_id,
                "iteration": task.iteration,
                "timestamp": datetime.now(UTC).isoformat(),
                "data": {
                    "reason": reason,
                    "threshold_percent": threshold_percent,
                    "usage_before": usage_before,
                },
            }
        ]

        try:
            if stashed_messages:
                self.runtime_service.stash_task_messages(task, stashed_messages)
                runtime_state = self.runtime_service.replace_runtime_messages(
                    task,
                    prefix_messages,
                    compact_result=original_compact_result,
                    preserve_pending_action_result=True,
                    preserve_cache_state=True,
                )

            compact_result, compact_usage = await self._execute_compaction(
                task=task,
                source_messages=source_messages,
            )
            self.state_service.record_task_usage(task, compact_usage)

            restored_messages = [
                {"role": "system", "content": system_prompt},
                {"role": "assistant", "content": compact_result},
            ]
            if stashed_messages:
                restored_messages.extend(
                    self.runtime_service.load_stashed_task_messages(task)
                )
                task.runtime_message_start_index = 2
            else:
                task.runtime_message_start_index = 0

            task.updated_at = datetime.now(UTC)
            self.db.add(task)
            runtime_state = self.runtime_service.replace_runtime_messages(
                task,
                restored_messages,
                compact_result=compact_result,
                preserve_pending_action_result=True,
                preserve_cache_state=False,
            )
            if stashed_messages:
                self.runtime_service.clear_stashed_task_messages(task)

            usage_after = self._build_usage_snapshot(
                task=task,
                messages=runtime_state.messages,
                max_context_tokens=max_context_tokens,
            )
            events.append(
                {
                    "type": "compact_complete",
                    "task_id": task.task_id,
                    "iteration": task.iteration,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "data": {
                        "reason": reason,
                        "threshold_percent": threshold_percent,
                        "usage_before": usage_before,
                        "usage_after": usage_after,
                        "compact_tokens": compact_usage,
                    },
                }
            )
            return runtime_state, events
        except Exception as exc:
            logger.exception(
                "Context compact failed task_id=%s iteration=%s reason=%s",
                task.task_id,
                task.iteration,
                reason,
            )
            if stashed_messages:
                runtime_state = self.runtime_service.replace_runtime_messages(
                    task,
                    original_messages,
                    compact_result=original_compact_result,
                    preserve_pending_action_result=True,
                    preserve_cache_state=True,
                )
                self.runtime_service.clear_stashed_task_messages(task)
            events.append(
                {
                    "type": "compact_failed",
                    "task_id": task.task_id,
                    "iteration": task.iteration,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "data": {
                        "reason": reason,
                        "threshold_percent": threshold_percent,
                        "usage_before": usage_before,
                        "error": str(exc) or repr(exc),
                    },
                }
            )
            return runtime_state, events

    @staticmethod
    def _next_stream_chunk_or_none(
        stream_iterator: Iterator[Response],
    ) -> Response | None:
        """Return the next streaming chunk, or ``None`` when stream is exhausted."""
        try:
            return next(stream_iterator)
        except StopIteration:
            return None

    async def _stream_chat_response(
        self,
        messages: list[dict[str, Any]],
        llm_chat_kwargs: dict[str, Any],
        token_counter: dict[str, int],
        token_meter_queue: asyncio.Queue[dict[str, Any]] | None = None,
    ) -> Response:
        """Collect full model output via ``chat_stream`` while emitting live updates."""
        stream_iterator = self.llm.chat_stream(
            messages=messages,
            **llm_chat_kwargs,
        )  # type: ignore[arg-type]

        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        # Keep empty until provider emits a real response id.
        # Random fallback IDs would poison ``previous_response_id`` chaining.
        response_id = ""
        response_model = getattr(self.llm, "model", "")

        stream_started_at = perf_counter()
        last_report_at = stream_started_at
        last_report_tokens = 0
        estimated_completion_tokens = 0
        usage_accumulator = StreamingUsageAccumulator()

        while True:
            stream_chunk = await run_in_threadpool(
                self._next_stream_chunk_or_none,
                stream_iterator,
            )
            if stream_chunk is None:
                break

            if isinstance(stream_chunk.id, str) and stream_chunk.id:
                response_id = stream_chunk.id
            if isinstance(stream_chunk.model, str) and stream_chunk.model:
                response_model = stream_chunk.model

            usage_accumulator.observe(stream_chunk.usage)

            for chunk_choice in stream_chunk.choices:
                chunk_message = chunk_choice.message
                reasoning_delta = chunk_message.reasoning_content
                if isinstance(reasoning_delta, str) and reasoning_delta:
                    reasoning_parts.append(reasoning_delta)
                    estimated_completion_tokens += estimate_text_tokens(reasoning_delta)
                    if token_meter_queue is not None:
                        await token_meter_queue.put(
                            {
                                "type": "reasoning",
                                "delta": reasoning_delta,
                            }
                        )

                content_delta = chunk_message.content
                if isinstance(content_delta, str) and content_delta:
                    content_parts.append(content_delta)
                    estimated_completion_tokens += estimate_text_tokens(content_delta)

            if token_meter_queue is not None:
                now = perf_counter()
                if now - last_report_at >= 1.0:
                    window_seconds = max(now - last_report_at, 1e-6)
                    window_tokens = max(
                        estimated_completion_tokens - last_report_tokens,
                        0,
                    )
                    await token_meter_queue.put(
                        {
                            "type": "token_rate",
                            "tokens_per_second": round(
                                window_tokens / window_seconds,
                                2,
                            ),
                            "estimated_completion_tokens": estimated_completion_tokens,
                        }
                    )
                    last_report_at = now
                    last_report_tokens = estimated_completion_tokens

        # Final flush so UI gets the latest completion estimate before action arrives.
        if token_meter_queue is not None:
            now = perf_counter()
            window_seconds = max(now - last_report_at, 1e-6)
            window_tokens = max(estimated_completion_tokens - last_report_tokens, 0)
            await token_meter_queue.put(
                {
                    "type": "token_rate",
                    "tokens_per_second": round(window_tokens / window_seconds, 2),
                    "estimated_completion_tokens": estimated_completion_tokens,
                }
            )

        attempt_usage_counter = usage_accumulator.build_token_counter()

        # Usage fallback: estimate prompt/completion when provider does not return usage.
        if (
            attempt_usage_counter["prompt_tokens"] == 0
            and attempt_usage_counter["completion_tokens"] == 0
            and attempt_usage_counter["total_tokens"] == 0
        ):
            estimated_prompt_tokens = estimate_messages_tokens(messages)
            attempt_usage_counter["prompt_tokens"] = estimated_prompt_tokens
            attempt_usage_counter["completion_tokens"] = estimated_completion_tokens
            attempt_usage_counter["total_tokens"] = (
                estimated_prompt_tokens + estimated_completion_tokens
            )
        elif attempt_usage_counter["total_tokens"] <= 0 and (
            attempt_usage_counter["prompt_tokens"] > 0
            or attempt_usage_counter["completion_tokens"] > 0
        ):
            attempt_usage_counter["total_tokens"] = (
                attempt_usage_counter["prompt_tokens"]
                + attempt_usage_counter["completion_tokens"]
            )

        self._accumulate_token_counter(token_counter, attempt_usage_counter)
        self._ensure_total_tokens(attempt_usage_counter)
        self._ensure_total_tokens(token_counter)

        full_content = "".join(content_parts)
        full_reasoning = "".join(reasoning_parts) or None
        usage_info = (
            UsageInfo(
                prompt_tokens=attempt_usage_counter["prompt_tokens"],
                completion_tokens=attempt_usage_counter["completion_tokens"],
                total_tokens=attempt_usage_counter["total_tokens"],
                cached_input_tokens=attempt_usage_counter["cached_input_tokens"],
            )
            if attempt_usage_counter["total_tokens"] > 0
            else None
        )
        return Response(
            id=response_id,
            choices=[
                Choice(
                    index=0,
                    message=ChatMessage(
                        role="assistant",
                        content=full_content,
                        reasoning_content=full_reasoning,
                    ),
                )
            ],
            created=int(datetime.now(UTC).timestamp()),
            model=response_model,
            usage=usage_info,
        )

    def _build_parse_retry_messages(
        self, messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Append a one-shot parse repair instruction for lightweight retries.

        Args:
            messages: Original request messages sent to the model.

        Returns:
            A new message list with one extra user instruction appended.
        """
        retry_messages: list[dict[str, Any]] = list(messages)
        retry_messages.append({"role": "user", "content": PARSE_RETRY_INSTRUCTION})
        return retry_messages

    def _is_timeout_error(self, exc: Exception) -> bool:
        """Whether an exception chain represents an LLM request timeout.

        Why: timeout retries should not consume iteration budget or pollute
        persisted LLM messages, same as malformed JSON rollback behavior.
        """
        timeout_keywords = ("timed out", "timeout")
        current: BaseException | None = exc
        while current is not None:
            if isinstance(current, TimeoutError):
                return True

            class_name = type(current).__name__.lower()
            message = str(current).lower()
            if "timeout" in class_name:
                return True
            if any(keyword in message for keyword in timeout_keywords):
                return True

            current = current.__cause__ or current.__context__
        return False

    def _is_non_retryable_llm_error(self, exc: Exception) -> bool:
        """Whether an exception is a deterministic LLM request/configuration error.

        Why: transport/configuration 4xx errors should fail fast instead of
        consuming the whole iteration budget with identical retries.
        """
        current: BaseException | None = exc
        while current is not None:
            status_code = getattr(
                getattr(current, "response", None), "status_code", None
            )
            if (
                isinstance(status_code, int)
                and 400 <= status_code < 500
                and status_code not in {408, 409, 429}
            ):
                return True

            message = str(current)
            http_match = re.search(r"\bHTTP\s+(\d{3})\b", message)
            if http_match:
                parsed_status = int(http_match.group(1))
                if 400 <= parsed_status < 500 and parsed_status not in {408, 409, 429}:
                    return True

            current = current.__cause__ or current.__context__
        return False

    def _format_message_content_for_log(self, content: str) -> str:
        """Format one message content for human-readable logging.

        Args:
            content: Raw message content.

        Returns:
            Pretty-printed string for log output.
        """
        try:
            parsed = parse_react_output(content).to_dict()
        except ValueError:
            return content
        return json.dumps(parsed, ensure_ascii=False, indent=2)

    def _log_messages_pretty(
        self,
        messages: list[dict[str, Any]],
        task_id: str,
        iteration: int,
        trace_id: str,
        phase: str,
        start_index: int = 0,
        iteration_message_start: int = 1,
    ) -> None:
        """Log incremental LLM messages with readable per-message formatting.

        Args:
            messages: Full message history sent to LLM.
            task_id: Current task UUID.
            iteration: Current human-facing iteration (1-based).
            trace_id: Current recursion trace ID.
            phase: Logging phase, typically "send" or "receive".
            start_index: Start index (inclusive) of incremental messages to log.
            iteration_message_start: Display index for the first logged message.
        """
        delta_messages = messages[start_index:]
        if not delta_messages:
            return

        rendered_lines = [
            (
                "LLM messages delta\n"
                f"task_id={task_id} iteration={iteration} trace_id={trace_id} "
                f"phase={phase} delta_count={len(delta_messages)}"
            )
        ]
        display_message_index = iteration_message_start
        for msg in delta_messages:
            role = msg.get("role", "unknown")
            if role == "system":
                continue
            raw_content = msg.get("content", "")
            content = raw_content if isinstance(raw_content, str) else str(raw_content)
            rendered_lines.append(
                f"[iteration-{iteration}, message-{display_message_index}] role={role}"
            )
            rendered_lines.append(self._format_message_content_for_log(content))
            display_message_index += 1

        logger.debug("\n%s", "\n".join(rendered_lines))

    def _uses_incremental_request_messages(self) -> bool:
        """Whether current LLM transport uses incremental-only request messages."""
        return self.llm.uses_incremental_request_messages()

    def _build_current_plan_payload(
        self, context: ReactContext
    ) -> list[dict[str, Any]]:
        """Convert current in-memory plan context to compact user-message payload.

        Args:
            context: Current ReAct context snapshot.

        Returns:
            List of plan step dictionaries for user-message injection.
        """
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

    def _persist_session_title(
        self,
        task: ReactTask,
        session_title: str,
    ) -> str:
        """Persist one assistant-proposed session title when available.

        Args:
            task: Current running task.
            session_title: Raw session title from the parsed model decision.

        Returns:
            The normalized persisted title, or ``""`` when no update happened.
        """
        normalized_title = session_title.strip()
        if not normalized_title or not task.session_id:
            return ""

        updated_session = SessionService(self.db).update_session_metadata(
            task.session_id,
            title=normalized_title,
        )
        if updated_session is None or updated_session.title is None:
            return ""
        return updated_session.title

    def _build_recursion_user_payload(
        self,
        task: ReactTask,
        context: ReactContext,
        trace_id: str,
        pending_action_result: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        """Build the per-recursion user payload appended to messages.

        Args:
            task: Current running task.
            context: Current context snapshot.
            trace_id: Server-generated recursion trace ID for this iteration.
            pending_action_result: Result payload from the prior recursion, if any.

        Returns:
            Serializable payload for the recursion user message.
        """
        payload: dict[str, Any] = {
            "trace_id": trace_id,
            "iteration": task.iteration + 1,
            "user_intent": task.user_intent,
            "current_plan": self._build_current_plan_payload(context),
        }
        if pending_action_result is not None:
            payload["action_result"] = pending_action_result
        return payload

    def _build_next_pending_action_result(
        self, event_data: dict[str, Any]
    ) -> list[dict[str, Any]] | None:
        """Derive next recursion's action_result payload from current action output.

        Args:
            event_data: Recursion event payload produced by execute_recursion.

        Returns:
            action_result payload list for next recursion, or None when not needed.
        """
        action_type = event_data.get("action_type")
        if action_type == "CALL_TOOL":
            tool_results = event_data.get("tool_results", [])
            if not isinstance(tool_results, list):
                return [{"error": "Invalid tool_results payload"}]
            compact_results: list[dict[str, Any]] = []
            for result_item in tool_results:
                if not isinstance(result_item, dict):
                    continue
                compact_item: dict[str, Any] = {}
                tool_call_id = result_item.get("tool_call_id")
                if isinstance(tool_call_id, str) and tool_call_id:
                    compact_item["id"] = tool_call_id
                if result_item.get("success") is True:
                    compact_item["result"] = result_item.get("result")
                else:
                    compact_item["error"] = result_item.get(
                        "error", "Tool execution failed"
                    )
                compact_results.append(compact_item)
            return compact_results
        if action_type == "CLARIFY":
            output = event_data.get("output", {})
            return [{"result": output if isinstance(output, dict) else {}}]
        return None

    def _extract_pending_user_action_from_tool_results(
        self,
        tool_results: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Extract one system-owned waiting action from tool results, if any."""
        for result_item in tool_results:
            if result_item.get("success") is not True:
                continue
            raw_result = result_item.get("result")
            if not isinstance(raw_result, dict):
                continue
            pending_user_action = raw_result.get("pending_user_action")
            if isinstance(pending_user_action, dict):
                return dict(pending_user_action)
        return None

    async def execute_recursion(
        self,
        task: ReactTask,
        context: ReactContext,
        trace_id: str,
        messages: list[dict[str, Any]],
        llm_chat_kwargs: dict[str, Any] | None = None,
        token_meter_queue: asyncio.Queue[dict[str, Any]] | None = None,
    ) -> tuple[ReactRecursion, dict[str, Any]]:
        """
        Execute a single recursion cycle.

        Args:
            task: The ReactTask being executed
            context: Current context state
            messages: Message history for LLM
            llm_chat_kwargs: Extra runtime kwargs passed to LLM chat call.
            token_meter_queue: Optional queue for realtime token-rate snapshots.

        Returns:
            Tuple of (ReactRecursion record, event data for streaming)
        """
        task_id_value = task.task_id
        task_iteration_value = task.iteration

        # Use server-generated trace_id from this recursion cycle.
        context.update_for_new_recursion(trace_id)

        recursion = self.state_service.start_recursion(task, trace_id)

        # Call LLM WITHOUT tools parameter (using prompt-based approach).
        # Stable schema rules live in the session-level system prompt, while the
        # task-scoped tool/session-memory/skills catalog is injected once via the
        # task bootstrap user prompt before recursion begins.
        try:
            token_counter = self._new_token_counter()
            response = None
            message: ChatMessage | None = None
            assistant_message_raw: str | None = None
            decision: ParsedReactDecision | None = None
            parse_error: ValueError | None = None
            request_messages = messages

            for parse_attempt in range(PARSE_RETRY_LIMIT + 1):
                if self.stream_llm_responses:
                    response = await self._stream_chat_response(
                        messages=request_messages,
                        llm_chat_kwargs=llm_chat_kwargs or {},
                        token_counter=token_counter,
                        token_meter_queue=token_meter_queue,
                    )
                else:
                    response = await run_in_threadpool(
                        self.llm.chat,
                        messages=request_messages,
                        **(llm_chat_kwargs or {}),
                    )  # type: ignore[arg-type]
                    self._accumulate_usage(token_counter, response.usage)
                    self._ensure_total_tokens(token_counter)

                choice = response.first()
                message = choice.message

                # Parse JSON from content to get observe, reason, summary, action_type
                content = message.content or "{}"
                assistant_message_raw = content

                try:
                    decision = parse_react_output(content)
                    logger.debug(
                        "Successfully parsed LLM output (trace_id=%s, attempt=%s)",
                        trace_id,
                        parse_attempt + 1,
                    )
                    break
                except ValueError as e:
                    parse_error = e
                    if parse_attempt < PARSE_RETRY_LIMIT:
                        logger.warning(
                            "Failed to parse LLM output (trace_id=%s, attempt=%s): %s. "
                            "Retrying once with strict format repair instruction.",
                            trace_id,
                            parse_attempt + 1,
                            e,
                        )
                        request_messages = self._build_parse_retry_messages(messages)
                        continue

                    logger.error(
                        f"Failed to parse LLM response\n"
                        f"Trace ID: {trace_id}\n"
                        f"Task ID: {task.task_id}\n"
                        f"Iteration: {task.iteration}\n"
                        f"Error: {e}"
                    )

            if response is None or decision is None or message is None:
                tokens_data = self.state_service.finalize_error(
                    task,
                    recursion,
                    str(parse_error or "Failed to parse LLM output"),
                    token_counter,
                )

                return recursion, {
                    "trace_id": trace_id,
                    "action_type": "ERROR",
                    "error": str(parse_error or "Failed to parse LLM output"),
                    "tokens": tokens_data,
                    "assistant_message": None,
                    "rollback_messages": True,
                    "llm_response_id": response.id if response is not None else None,
                }

            observe = decision.observe
            thinking = message.reasoning_content
            reason = decision.reason
            summary = decision.summary
            session_title = decision.session_title
            action = decision.action
            action_type = action.action_type
            action_output = dict(action.output)
            answer_attachments: list[dict[str, Any]] = []

            if action_type == "ANSWER":
                action_output, answer_attachments = self._persist_answer_attachments(
                    task=task,
                    action_output=action_output,
                )

            # Extract the plan step this recursion belongs to.
            # The LLM returns action.step_id when executing as part of a plan.
            # We must validate its presence when a plan exists, but never abort — a
            # missing step_id should only surface as a warning so the task can continue.
            action_step_id = action.step_id

            task_summary = decision.task_summary

            # Handle CALL_TOOL with native function calling
            tool_results: list[dict[str, Any]] = []
            reconstructed_tool_calls: list[dict[str, Any]] = []

            if action_type == "CALL_TOOL":
                for tool_call in action.tool_calls:
                    try:
                        # Execute tool asynchronously via thread pool
                        result = await run_in_threadpool(
                            self.tool_manager.execute,
                            tool_call.name,
                            context=self.tool_execution_context,
                            **tool_call.arguments,
                        )

                        tool_results.append(
                            {
                                "tool_call_id": tool_call.id,
                                "name": tool_call.name,
                                "arguments": tool_call.arguments,
                                "result": result,
                                "success": True,
                            }
                        )

                        # Keep tool_call in reconstructed format for event data
                        reconstructed_tool_calls.append(tool_call.to_dict())

                    except Exception as e:
                        logger.error("Tool %s execution failed: %s", tool_call.name, e)
                        # Provide helpful error message with available tools
                        if "not found in registry" in str(e):
                            available_tools = self.tool_manager.list_tools()
                            tool_names = [tool.name for tool in available_tools]
                            error_msg = (
                                f"Tool '{tool_call.name}' not found. "
                                f"Available tools: {', '.join(tool_names)}"
                            )
                        else:
                            error_msg = f"Tool execution failed: {e!s}"
                        tool_results.append(
                            {
                                "tool_call_id": tool_call.id,
                                "name": tool_call.name,
                                "arguments": tool_call.arguments,
                                "error": error_msg,
                                "success": False,
                            }
                        )
                        # Always record the call attempt so the frontend knows
                        # which function was invoked and with what arguments,
                        # regardless of whether execution succeeded or failed.
                        reconstructed_tool_calls.append(tool_call.to_dict())

            # Validate optional step status updates requested by the LLM.
            step_status_updates_validated = [
                item.to_dict() for item in action.step_status_update
            ]
            pending_user_action = self._extract_pending_user_action_from_tool_results(
                tool_results
            )
            tokens_data = self.state_service.finalize_success(
                task=task,
                recursion=recursion,
                context=context,
                observe=observe,
                thinking=thinking,
                reason=reason,
                action_type=action_type,
                action_output=action_output,
                action_step_id=action_step_id,
                step_status_updates=step_status_updates_validated,
                summary=summary,
                tool_results=tool_results,
                token_counter=token_counter,
                pending_user_action=pending_user_action,
            )
            persisted_session_title = self._persist_session_title(task, session_title)

            # Prepare event data
            event_data = {
                "trace_id": trace_id,
                "action_type": action_type,
                "llm_response_id": response.id,
                "observe": observe,
                "thinking": thinking,
                "reason": reason,
                "summary": summary,
                "session_title": persisted_session_title,
                "output": action_output,
                "answer_attachments": answer_attachments,
                "assistant_message": assistant_message_raw,
                "tool_calls": reconstructed_tool_calls,  # Native tool_calls
                "tool_results": tool_results,  # Tool execution results
                "pending_user_action": pending_user_action,
                "task_summary": task_summary,
                "step_status_update": step_status_updates_validated,
                "current_plan": self._build_current_plan_payload(context),
            }

            # Add token usage if available
            if tokens_data is not None:
                event_data["tokens"] = tokens_data

            return recursion, event_data

        except Exception as e:
            # Handle errors with detailed logging
            error_msg = str(e)
            is_timeout_error = self._is_timeout_error(e)
            non_retryable_error = self._is_non_retryable_llm_error(e)
            logger.error(
                f"Recursion execution failed for trace_id={trace_id}\n"
                f"Error type: {type(e).__name__}\n"
                f"Error message: {error_msg}\n"
                f"Task ID: {task_id_value}\n"
                f"Iteration: {task_iteration_value}"
            )

            tokens_data = self.state_service.finalize_error(
                task,
                recursion,
                error_msg,
            )

            rollback_messages = is_timeout_error

            return recursion, {
                "trace_id": trace_id,
                "action_type": "ERROR",
                "error": (
                    f"LLM request timeout: {error_msg}"
                    if is_timeout_error
                    else error_msg
                ),
                "assistant_message": None,
                "tokens": tokens_data,
                "rollback_messages": rollback_messages,
                "non_retryable_error": non_retryable_error,
            }

    async def run_task(
        self,
        task: ReactTask,
        selected_skills_text: str = "",
        turn_user_message: str | None = None,
        turn_files: list[FileAssetListItem] | None = None,
        turn_file_blocks: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Execute complete ReAct task with streaming events.

        Args:
            task: The ReactTask to execute.
            selected_skills_text: Selected skill markdown block injected in the
                once-per-task bootstrap user prompt.
            turn_user_message: User input of the current turn (used for chat history).
            turn_files: Uploaded file summaries for chat history and prompting.
            turn_file_blocks: Neutral multimodal content blocks for this turn.

        Yields:
            Stream events for each recursion cycle

        Raises:
            asyncio.CancelledError: If the task is cancelled by client disconnect
        """
        agent = self.db.get(Agent, task.agent_id)
        if agent is None:
            raise RuntimeError(
                f"Agent {task.agent_id} not found for task {task.task_id}."
            )

        max_context_tokens = 0
        if agent.llm_id is not None:
            llm_config = llm_crud.get(agent.llm_id, self.db)
            if llm_config is not None:
                max_context_tokens = max(int(llm_config.max_context or 0), 0)
        compact_threshold_percent = max(int(agent.compact_threshold_percent or 0), 0)
        system_prompt = build_runtime_system_prompt()

        should_append_user_history = (
            task.iteration == 0 or turn_user_message is not None
        )
        if task.session_id and should_append_user_history:
            session_service = SessionService(self.db)
            session_service.update_chat_history(
                task.session_id,
                "user",
                turn_user_message
                if turn_user_message is not None
                else task.user_message,
                files=turn_files,
            )

        self.state_service.mark_running(task)

        runtime_state = self.runtime_service.initialize(
            task,
            system_prompt,
        )
        logged_message_count = len(runtime_state.messages)
        pending_turn_file_blocks = turn_file_blocks

        if task.iteration == 0:
            runtime_state, compact_events = await self._maybe_compact_runtime_window(
                task=task,
                runtime_state=runtime_state,
                system_prompt=system_prompt,
                max_context_tokens=max_context_tokens,
                threshold_percent=compact_threshold_percent,
                reason="task_start_threshold",
            )
            for compact_event in compact_events:
                yield compact_event
            logged_message_count = len(runtime_state.messages)
            runtime_state = self.runtime_service.append_task_bootstrap_prompt(
                task,
                build_runtime_user_prompt(
                    tool_manager=self.tool_manager,
                    skills=selected_skills_text,
                ),
            )
            self._log_messages_pretty(
                messages=runtime_state.messages,
                task_id=task.task_id,
                iteration=task.iteration + 1,
                trace_id="task-bootstrap",
                phase="send",
                start_index=logged_message_count,
                iteration_message_start=0,
            )
            logged_message_count = len(runtime_state.messages)

        try:
            while task.iteration < task.max_iteration:
                runtime_state = self.runtime_service.load(task)
                (
                    runtime_state,
                    compact_events,
                ) = await self._maybe_compact_runtime_window(
                    task=task,
                    runtime_state=runtime_state,
                    system_prompt=system_prompt,
                    max_context_tokens=max_context_tokens,
                    threshold_percent=compact_threshold_percent,
                    reason="iteration_threshold",
                )
                for compact_event in compact_events:
                    yield compact_event
                if compact_events:
                    logged_message_count = len(runtime_state.messages)

                trace_id = str(uuid.uuid4())

                # Check if task was cancelled
                if self.cancelled or task.status == "cancelled":
                    logger.info(f"Task {task.task_id} cancelled, exiting loop")
                    self.state_service.mark_cancelled(task)
                    self.runtime_service.clear_task_state(task)
                    break
                # Load current context
                context = self.state_service.load_context(task)

                # Yield recursion start event
                yield {
                    "type": "recursion_start",
                    "task_id": task.task_id,
                    "trace_id": trace_id,
                    "iteration": task.iteration,
                    "timestamp": datetime.now(UTC).isoformat(),
                }

                # Append iteration payload as a new user message.
                user_payload = self._build_recursion_user_payload(
                    task,
                    context,
                    trace_id,
                    runtime_state.pending_action_result,
                )
                attachments = pending_turn_file_blocks
                runtime_state = self.runtime_service.append_user_payload(
                    task,
                    user_payload,
                    attachments=attachments,
                )
                pending_turn_file_blocks = None
                self._log_messages_pretty(
                    messages=runtime_state.messages,
                    task_id=task.task_id,
                    iteration=task.iteration + 1,
                    trace_id="pending",
                    phase="send",
                    start_index=logged_message_count,
                    iteration_message_start=1,
                )
                logged_message_count = len(runtime_state.messages)

                messages_for_llm = runtime_state.messages
                llm_chat_kwargs: dict[str, Any] = {
                    **self.llm_runtime_kwargs,
                    "_pivot_task_id": task.task_id,
                }
                if (
                    self._uses_incremental_request_messages()
                    and runtime_state.previous_response_id
                ):
                    llm_chat_kwargs["_pivot_previous_response_id"] = (
                        runtime_state.previous_response_id
                    )
                    messages_for_llm = self.runtime_service.get_incremental_messages(
                        task
                    )

                # Execute recursion against the fully accumulated message history.
                token_meter_queue: asyncio.Queue[dict[str, Any]] | None = None
                if self.stream_llm_responses:
                    token_meter_queue = asyncio.Queue()

                recursion_task = asyncio.create_task(
                    self.execute_recursion(
                        task=task,
                        context=context,
                        trace_id=trace_id,
                        messages=messages_for_llm,
                        llm_chat_kwargs=llm_chat_kwargs,
                        token_meter_queue=token_meter_queue,
                    )
                )

                cancelled_during_recursion = False
                last_meter_emit_at = perf_counter()
                last_estimated_completion_tokens = 0
                while True:
                    if self.cancelled or task.status == "cancelled":
                        recursion_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await recursion_task
                        self.state_service.mark_cancelled(task)
                        self.runtime_service.clear_task_state(task)
                        cancelled_during_recursion = True
                        break

                    if token_meter_queue is None:
                        done, _ = await asyncio.wait({recursion_task}, timeout=0.2)
                        if done:
                            break
                        continue

                    if recursion_task.done() and token_meter_queue.empty():
                        break

                    try:
                        meter_data = await asyncio.wait_for(
                            token_meter_queue.get(),
                            timeout=0.2,
                        )
                    except TimeoutError:
                        now = perf_counter()
                        if now - last_meter_emit_at >= 1.0:
                            # Keep UI cadence stable: when provider stream stalls,
                            # emit a heartbeat with zero instantaneous rate.
                            yield {
                                "type": "token_rate",
                                "task_id": task.task_id,
                                "trace_id": trace_id,
                                "iteration": task.iteration,
                                "data": {
                                    "tokens_per_second": 0.0,
                                    "estimated_completion_tokens": (
                                        last_estimated_completion_tokens
                                    ),
                                },
                                "timestamp": datetime.now(UTC).isoformat(),
                            }
                            last_meter_emit_at = now
                        continue

                    meter_type = meter_data.get("type")
                    if meter_type == "reasoning":
                        reasoning_delta = meter_data.get("delta")
                        if isinstance(reasoning_delta, str) and reasoning_delta:
                            yield {
                                "type": "reasoning",
                                "task_id": task.task_id,
                                "trace_id": trace_id,
                                "iteration": task.iteration,
                                "delta": reasoning_delta,
                                "timestamp": datetime.now(UTC).isoformat(),
                            }
                        continue

                    raw_rate = meter_data.get("tokens_per_second")
                    raw_estimated = meter_data.get("estimated_completion_tokens")
                    tokens_per_second = (
                        float(raw_rate) if isinstance(raw_rate, int | float) else 0.0
                    )
                    estimated_completion_tokens = (
                        int(raw_estimated)
                        if isinstance(raw_estimated, int | float)
                        else last_estimated_completion_tokens
                    )
                    if tokens_per_second < 0:
                        tokens_per_second = 0.0
                    if estimated_completion_tokens < 0:
                        estimated_completion_tokens = 0

                    last_estimated_completion_tokens = estimated_completion_tokens
                    last_meter_emit_at = perf_counter()
                    yield {
                        "type": "token_rate",
                        "task_id": task.task_id,
                        "trace_id": trace_id,
                        "iteration": task.iteration,
                        "data": {
                            "tokens_per_second": round(tokens_per_second, 2),
                            "estimated_completion_tokens": estimated_completion_tokens,
                        },
                        "timestamp": datetime.now(UTC).isoformat(),
                    }

                if cancelled_during_recursion:
                    break

                recursion, event_data = await recursion_task
                if self.cancelled or task.status == "cancelled":
                    self.state_service.mark_cancelled(task)
                    self.runtime_service.clear_task_state(task)
                    break
                rollback_messages = bool(event_data.get("rollback_messages", False))
                if rollback_messages:
                    # Parse errors should be visible to users, but must not pollute
                    # persisted LLM messages. Roll back the just-appended user payload.
                    runtime_state = self.runtime_service.rollback_last_user_message(
                        task
                    )
                    logged_message_count = len(runtime_state.messages)
                    if self._uses_incremental_request_messages():
                        # Drop chained cache linkage so malformed outputs do not keep
                        # poisoning subsequent retries.
                        runtime_state = self.runtime_service.set_previous_response_id(
                            task,
                            None,
                        )
                else:
                    assistant_message = event_data.get("assistant_message")
                    if isinstance(assistant_message, str) and assistant_message:
                        runtime_state = self.runtime_service.append_assistant_message(
                            task,
                            assistant_message,
                        )
                        self._log_messages_pretty(
                            messages=runtime_state.messages,
                            task_id=task.task_id,
                            iteration=task.iteration + 1,
                            trace_id=str(event_data.get("trace_id", "")),
                            phase="receive",
                            start_index=logged_message_count,
                            iteration_message_start=2,
                        )
                        logged_message_count = len(runtime_state.messages)
                    if self._uses_incremental_request_messages():
                        response_id = event_data.get("llm_response_id")
                        if isinstance(response_id, str) and response_id:
                            runtime_state = (
                                self.runtime_service.set_previous_response_id(
                                    task,
                                    response_id,
                                )
                            )

                action_type = event_data.get("action_type", "")
                if isinstance(action_type, str):
                    action_type = action_type.strip()
                pending_user_action = event_data.get("pending_user_action")
                next_action_result = self._build_next_pending_action_result(event_data)
                if isinstance(pending_user_action, dict):
                    runtime_state = self.runtime_service.set_next_action_result(
                        task,
                        None,
                    )
                elif next_action_result is not None:
                    runtime_state = self.runtime_service.set_next_action_result(
                        task,
                        next_action_result,
                    )
                elif action_type != "ERROR":
                    # Keep previous action_result only when this recursion failed.
                    runtime_state = self.runtime_service.set_next_action_result(
                        task,
                        None,
                    )

                # Yield Observe, Reason, Action events with token info
                if recursion.thinking and not self.stream_llm_responses:
                    yield {
                        "type": "reasoning",
                        "task_id": task.task_id,
                        "trace_id": event_data.get("trace_id"),
                        "iteration": task.iteration,
                        "delta": recursion.thinking,
                        "timestamp": datetime.now(UTC).isoformat(),
                        "created_at": recursion.created_at.isoformat(),
                        "updated_at": recursion.updated_at.isoformat(),
                        "tokens": event_data.get("tokens"),
                    }

                if recursion.observe:
                    yield {
                        "type": "observe",
                        "task_id": task.task_id,
                        "trace_id": event_data.get("trace_id"),
                        "iteration": task.iteration,
                        "delta": recursion.observe,
                        "timestamp": datetime.now(UTC).isoformat(),
                        "created_at": recursion.created_at.isoformat(),
                        "updated_at": recursion.updated_at.isoformat(),
                        "tokens": event_data.get("tokens"),
                    }

                if recursion.reason:
                    yield {
                        "type": "reason",
                        "task_id": task.task_id,
                        "trace_id": event_data.get("trace_id"),
                        "iteration": task.iteration,
                        "delta": recursion.reason,
                        "timestamp": datetime.now(UTC).isoformat(),
                        "created_at": recursion.created_at.isoformat(),
                        "updated_at": recursion.updated_at.isoformat(),
                        "tokens": event_data.get("tokens"),
                    }

                if recursion.summary:
                    yield {
                        "type": "summary",
                        "task_id": task.task_id,
                        "trace_id": event_data.get("trace_id"),
                        "iteration": task.iteration,
                        "delta": recursion.summary,
                        "timestamp": datetime.now(UTC).isoformat(),
                        "created_at": recursion.created_at.isoformat(),
                        "updated_at": recursion.updated_at.isoformat(),
                        "tokens": event_data.get("tokens"),
                        "data": {
                            "current_plan": event_data.get("current_plan", []),
                            "session_title": event_data.get("session_title", ""),
                        },
                    }

                # Yield action event with type and token info
                yield {
                    "type": "action",
                    "task_id": task.task_id,
                    "trace_id": event_data.get("trace_id"),
                    "iteration": task.iteration,
                    "delta": action_type,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "created_at": recursion.created_at.isoformat(),
                    "updated_at": recursion.updated_at.isoformat(),
                    "tokens": event_data.get("tokens"),
                }

                # Yield recursion events
                if action_type == "CALL_TOOL":
                    # Get tool_calls and results from event_data (from native function calling)
                    tool_calls_data = event_data.get("tool_calls", [])
                    tool_results_data = event_data.get("tool_results", [])

                    yield {
                        "type": "tool_call",
                        "task_id": task.task_id,
                        "trace_id": event_data.get("trace_id"),
                        "iteration": task.iteration,
                        "data": {
                            "tool_calls": tool_calls_data,
                            "tool_results": tool_results_data,
                        },
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                    if isinstance(pending_user_action, dict):
                        approval_request = pending_user_action.get("approval_request")
                        question = (
                            approval_request.get("question")
                            if isinstance(approval_request, dict)
                            else None
                        )
                        yield {
                            "type": "clarify",
                            "task_id": task.task_id,
                            "trace_id": event_data.get("trace_id"),
                            "iteration": task.iteration,
                            "data": {
                                "question": (
                                    question
                                    if isinstance(question, str)
                                    else "Approve this skill change?"
                                ),
                                "approval_request": approval_request
                                if isinstance(approval_request, dict)
                                else None,
                            },
                            "timestamp": datetime.now(UTC).isoformat(),
                        }

                        self.state_service.advance_iteration(task)
                        break

                elif action_type == "RE_PLAN":
                    plan_output = event_data.get("output")
                    yield {
                        "type": "plan_update",
                        "task_id": task.task_id,
                        "trace_id": event_data.get("trace_id"),
                        "iteration": task.iteration,
                        "data": plan_output,
                        "timestamp": datetime.now(UTC).isoformat(),
                    }

                elif action_type == "REFLECT":
                    # REFLECT action: organizing thoughts without changing structure
                    # Just emit the reflect event and continue to next iteration
                    reflect_output = event_data.get("output")
                    yield {
                        "type": "reflect",
                        "task_id": task.task_id,
                        "trace_id": event_data.get("trace_id"),
                        "iteration": task.iteration,
                        "data": reflect_output,
                        "timestamp": datetime.now(UTC).isoformat(),
                    }

                elif action_type == "CLARIFY":
                    yield {
                        "type": "clarify",
                        "task_id": task.task_id,
                        "trace_id": event_data.get("trace_id"),
                        "iteration": task.iteration,
                        "data": event_data.get("output"),
                        "timestamp": datetime.now(UTC).isoformat(),
                    }

                    # Increment iteration before breaking so next run starts at next iteration
                    self.state_service.advance_iteration(task)

                    # Break loop as task is waiting for input
                    break

                elif action_type == "ANSWER":
                    yield {
                        "type": "answer",
                        "task_id": task.task_id,
                        "trace_id": event_data.get("trace_id"),
                        "iteration": task.iteration,
                        "data": event_data.get("output"),
                        "timestamp": datetime.now(UTC).isoformat(),
                    }

                    if task.session_id:
                        answer_output = event_data.get("output", {})
                        attachments_data = event_data.get("answer_attachments")
                        SessionService(self.db).update_chat_history(
                            task.session_id,
                            "assistant",
                            answer_output.get("answer", ""),
                            attachments=attachments_data
                            if isinstance(attachments_data, list)
                            else None,
                        )

                    # Task complete
                    self.state_service.mark_completed(task)
                    self.runtime_service.clear_task_state(task)

                    yield {
                        "type": "task_complete",
                        "task_id": task.task_id,
                        "iteration": task.iteration,
                        "timestamp": datetime.now(UTC).isoformat(),
                        "total_tokens": {
                            "prompt_tokens": task.total_prompt_tokens,
                            "completion_tokens": task.total_completion_tokens,
                            "total_tokens": task.total_tokens,
                            "cached_input_tokens": task.total_cached_input_tokens,
                        },
                    }
                    break

                elif action_type == "ERROR":
                    # Log the error but don't fail the task - retry with next iteration
                    error_msg = event_data.get("error", "Unknown error")
                    non_retryable_error = bool(
                        event_data.get("non_retryable_error", False)
                    )
                    if non_retryable_error:
                        logger.error(
                            "Recursion error at iteration %s (non-retryable). Error: %s",
                            task.iteration,
                            error_msg,
                        )
                    else:
                        logger.warning(
                            "Recursion error at iteration %s, retrying... Error: %s",
                            task.iteration,
                            error_msg,
                        )

                    yield {
                        "type": "error",
                        "task_id": task.task_id,
                        "trace_id": event_data.get("trace_id"),
                        "iteration": task.iteration,
                        "data": {"error": error_msg},
                        "timestamp": datetime.now(UTC).isoformat(),
                    }

                    if non_retryable_error:
                        logger.error(
                            "Non-retryable LLM error. Failing task immediately. "
                            "task_id=%s iteration=%s error=%s",
                            task.task_id,
                            task.iteration,
                            error_msg,
                        )
                        self.state_service.mark_failed(task)
                        self.runtime_service.clear_task_state(
                            task,
                            rollback_last_user_message=not rollback_messages,
                        )
                        break

                    # For malformed JSON we roll back this recursion from the LLM
                    # conversation and retry without consuming iteration budget.
                    if not rollback_messages:
                        self.state_service.advance_iteration(task)
                    continue

                # Update iteration count
                self.state_service.advance_iteration(task)

            # Max iteration reached
            if (
                task.iteration >= task.max_iteration
                and task.status == "running"
                and not self.cancelled
            ):
                self.state_service.mark_failed(task)
                self.runtime_service.clear_task_state(task)

                yield {
                    "type": "error",
                    "task_id": task.task_id,
                    "iteration": task.iteration,
                    "data": {"error": "Maximum iteration reached"},
                    "timestamp": datetime.now(UTC).isoformat(),
                }

        except Exception as e:
            if self.cancelled or task.status == "cancelled":
                logger.info(
                    "Suppressed task failure after cancellation task_id=%s iteration=%s",
                    task.task_id,
                    task.iteration,
                )
                self.state_service.mark_cancelled(task)
                self.runtime_service.clear_task_state(task)
                return

            logger.exception(
                "run_task failed unexpectedly task_id=%s iteration=%s",
                task.task_id,
                task.iteration,
            )
            self.state_service.mark_failed(task)
            self.runtime_service.clear_task_state(
                task,
                rollback_last_user_message=True,
            )
            error_message = str(e) or repr(e)

            yield {
                "type": "error",
                "task_id": task.task_id,
                "iteration": task.iteration,
                "data": {"error": error_message},
                "timestamp": datetime.now(UTC).isoformat(),
            }
