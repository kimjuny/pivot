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
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from app.config import get_settings
from app.llm.abstract_llm import (
    AbstractLLM,
    ChatMessage,
    Choice,
    FinishReason,
    Response,
    UsageInfo,
)
from app.llm.thinking_policy import build_runtime_thinking_kwargs
from app.llm.token_estimator import estimate_messages_tokens, estimate_text_tokens
from app.llm.usage_accumulator import StreamingUsageAccumulator, usage_to_token_counter
from app.models.agent import Agent
from app.models.react import (
    ReactRecursion,
    ReactTask,
)
from app.orchestration.compact.compact_prompt import (
    CompactPromptMode,
    build_compact_prompt,
)
from app.orchestration.tool.manager import ToolExecutionContext, ToolManager
from app.schemas.file import FileAssetListItem
from app.services.react_prompt_usage_service import ReactPromptUsageService
from app.services.react_runtime_service import ReactRuntimeService, TaskRuntimeState
from app.services.react_state_service import ReactStateService
from app.services.session_service import SessionService
from app.services.task_attachment_service import TaskAttachmentService
from fastapi.concurrency import run_in_threadpool
from pydantic import TypeAdapter
from sqlmodel import Session, desc, select

from .context import ReactContext
from .parser import (
    PARSE_RETRY_INSTRUCTION,
    PARSE_RETRY_LIMIT,
    parse_react_output,
    safe_load_json,
)
from .prompt_template import (
    build_runtime_payload_message,
    build_runtime_system_prompt,
    build_runtime_task_bootstrap_message,
    build_runtime_user_prompt,
)
from .runtime_payload import build_recursion_user_payload
from .types import ParsedReactDecision, ToolCallRequest

# Get logger for this module
logger = logging.getLogger(__name__)

# Reusable adapter for partial JSON parsing of tool call arguments.
_DICT_ADAPTER = TypeAdapter(dict)


def try_partial_parse(accumulated_json: str) -> dict[str, Any] | None:
    """Parse incomplete JSON using Pydantic ``allow_partial``.

    Returns completed top-level key/value pairs, or ``None`` on failure.
    """
    try:
        result = _DICT_ADAPTER.validate_json(
            accumulated_json,
            experimental_allow_partial=True,
        )
        return result if isinstance(result, dict) else None
    except Exception:
        return None


@dataclass(slots=True)
class _StreamingToolCallState:
    """Track accumulated argument state for one streaming tool call."""

    call_id: str
    name: str
    accumulated_json: str = ""
    last_parse_time: float = 0.0
    last_parsed_result: dict[str, Any] = field(default_factory=dict)
    arguments_complete: bool = False


@dataclass(slots=True)
class _EagerToolExecutionState:
    """Track eagerly-started tool executions during streaming."""

    started_call_ids: set[str] = field(default_factory=set)
    running_tasks: dict[str, asyncio.Task[dict[str, Any]]] = field(default_factory=dict)
    result_by_call_id: dict[str, dict[str, Any]] = field(default_factory=dict)


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
        thinking_runtime_config: dict[str, Any] | None = None,
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
        self.thinking_runtime_config = thinking_runtime_config or {}
        self.runtime_service = ReactRuntimeService(db)
        self.state_service = ReactStateService(db)
        self.cancelled = False  # Flag to signal cancellation
        self._pending_multimodal_blocks: list[dict[str, Any]] = []
        self._delegation_agents: str = ""
        self._delegation_event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._write_tool_locks: dict[str, asyncio.Lock] = {}
        self._plan_pending_review: bool = False
        self._prev_steps_json: str = ""
        self._steps_unchanged_count: int = 0

    def _previous_recursion_failed(self, task: ReactTask) -> bool:
        """Return whether the latest persisted recursion ended in failure.

        Why: Auto thinking should stay cheap for normal steady-state execution,
        but it should unlock deeper reasoning when the agent needs to recover
        from the previous recursion failing, especially after tool errors.

        Args:
            task: Task whose latest recursion should be inspected.

        Returns:
            ``True`` when the previous recursion failed at the recursion level or
            any tool call in that recursion reported an error.
        """
        if task.id is None:
            return False

        statement = (
            select(ReactRecursion)
            .where(ReactRecursion.react_task_id == task.id)
            .order_by(desc(ReactRecursion.iteration_index), desc(ReactRecursion.id))
        )
        previous_recursion = self.db.exec(statement).first()
        if previous_recursion is None:
            return False
        if previous_recursion.status == "error":
            return True

        raw_tool_results = previous_recursion.tool_call_results
        if not raw_tool_results:
            return False

        try:
            parsed_tool_results = json.loads(raw_tool_results)
        except json.JSONDecodeError:
            logger.warning(
                "Failed to parse tool_call_results while resolving Auto thinking. "
                "task_id=%s trace_id=%s",
                task.task_id,
                previous_recursion.trace_id,
            )
            return True

        if not isinstance(parsed_tool_results, list):
            return True

        for item in parsed_tool_results:
            if not isinstance(item, dict):
                continue
            if item.get("success") is False:
                return True
            error_message = item.get("error")
            if isinstance(error_message, str) and error_message.strip():
                return True
        return False

    def _build_iteration_llm_runtime_kwargs(self, task: ReactTask) -> dict[str, Any]:
        """Build runtime LLM kwargs for the current recursion.

        Args:
            task: Task whose current recursion is about to run.

        Returns:
            Provider kwargs combining static settings with dynamic thinking mode.
        """
        runtime_kwargs = dict(self.llm_runtime_kwargs)
        if not self.thinking_runtime_config:
            return runtime_kwargs
        previous_iteration_failed = self._previous_recursion_failed(task)

        runtime_kwargs.update(
            build_runtime_thinking_kwargs(
                protocol=str(self.thinking_runtime_config["protocol"]),
                thinking_policy=str(self.thinking_runtime_config["thinking_policy"]),
                thinking_effort=self.thinking_runtime_config.get("thinking_effort"),
                thinking_budget_tokens=self.thinking_runtime_config.get(
                    "thinking_budget_tokens"
                ),
                thinking_mode=self.thinking_runtime_config.get("thinking_mode"),
                iteration_index=task.iteration,
                next_turn_thinking=(
                    None
                    if previous_iteration_failed
                    else self._previous_recursion_requested_thinking(task)
                ),
                previous_iteration_failed=previous_iteration_failed,
            )
        )
        return runtime_kwargs

    def _previous_recursion_requested_thinking(
        self,
        task: ReactTask,
    ) -> bool | None:
        """Return the previous recursion's Auto-mode thinking hint.

        Why: the prompt contract lets the agent choose whether the next
        recursion should think deeply. We persist raw assistant messages in the
        session runtime window already, so Auto mode can recover that hint
        without introducing extra task schema state.

        Args:
            task: Task whose latest assistant decision should be inspected.

        Returns:
            ``True`` or ``False`` when the latest current-task assistant payload
            contains ``thinking_next_turn``; otherwise ``None``.
        """
        if not task.session_id:
            return None

        try:
            runtime_state = self.runtime_service.load(task)
        except RuntimeError:
            return None

        start_index = max(task.runtime_message_start_index, 0)
        task_messages = runtime_state.messages[start_index:]
        for message in reversed(task_messages):
            if message.get("role") != "assistant":
                continue

            content = message.get("content")
            if not isinstance(content, str) or not content.strip():
                continue

            try:
                decision = parse_react_output(content)
            except ValueError:
                logger.warning(
                    "Failed to parse previous assistant payload while resolving "
                    "Auto thinking. task_id=%s",
                    task.task_id,
                )
                return None
            return decision.thinking_next_turn

        return None

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
            user_id=task.user_id,
            task_id=task.task_id,
            session_id=task.session_id,
            paths=declared_paths,
        )
        public_payload = attachment_service.to_event_payload(attachments)
        normalized_output["attachments"] = public_payload
        return normalized_output, public_payload

    def _build_usage_snapshot(
        self,
        *,
        task: ReactTask,
        runtime_state: TaskRuntimeState,
        max_context_tokens: int,
        preview_messages: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Build a context-usage snapshot for runtime events and decisions."""
        return ReactPromptUsageService.build_usage_summary(
            task_id=task.task_id,
            session_id=task.session_id,
            estimation_mode=(
                "next_iteration_preview" if preview_messages else "active_task"
            ),
            messages=runtime_state.messages,
            max_context_tokens=max_context_tokens,
            exact_prompt_tokens=runtime_state.exact_prompt_tokens,
            exact_prompt_message_count=runtime_state.exact_prompt_message_count,
            preview_messages=preview_messages,
        )

    async def _execute_compaction(
        self,
        *,
        task: ReactTask,
        source_messages: list[dict[str, Any]],
        compact_mode: CompactPromptMode = "session",
    ) -> tuple[str, dict[str, int]]:
        """Run one compact-model call over the provided runtime messages."""
        compact_messages = [dict(message) for message in source_messages]
        compact_messages.append(
            {"role": "user", "content": build_compact_prompt(mode=compact_mode)}
        )

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
        preview_messages: list[dict[str, Any]] | None = None,
        emit_event: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> tuple[TaskRuntimeState, list[dict[str, Any]]]:
        """Compact the runtime prompt window when the configured threshold is hit."""
        if max_context_tokens <= 0 or threshold_percent <= 0:
            return runtime_state, []

        usage_before = self._build_usage_snapshot(
            task=task,
            runtime_state=runtime_state,
            max_context_tokens=max_context_tokens,
            preview_messages=preview_messages,
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
        compact_mode: CompactPromptMode = "session"
        in_task_compaction = False
        source_is_current_compact = (
            runtime_state.compact_result is not None
            and len(source_messages) == 1
            and source_messages[0].get("role") == "assistant"
            and source_messages[0].get("content") == runtime_state.compact_result
        )
        if (not source_messages or source_is_current_compact) and (
            reason == "iteration_threshold" and stashed_messages
        ):
            source_messages = [dict(message) for message in stashed_messages]
            compact_mode = "in_task"
            in_task_compaction = True
        elif not source_messages or source_is_current_compact:
            return runtime_state, []

        events: list[dict[str, Any]] = []
        start_event = {
            "type": "compact_start",
            "task_id": task.task_id,
            "iteration": task.iteration,
            "timestamp": datetime.now(UTC).isoformat(),
            "data": {
                "reason": reason,
                "compact_mode": compact_mode,
                "threshold_percent": threshold_percent,
                "usage_before": usage_before,
            },
        }
        compact_started_at = perf_counter()
        logger.info(
            "Context compact started task_id=%s iteration=%s reason=%s "
            "compact_mode=%s threshold_percent=%s used_percent=%s "
            "used_tokens=%s max_context_tokens=%s source_messages=%s "
            "stashed_messages=%s",
            task.task_id,
            task.iteration,
            reason,
            compact_mode,
            threshold_percent,
            usage_before.get("used_percent"),
            usage_before.get("used_tokens"),
            usage_before.get("max_context_tokens"),
            len(source_messages),
            len(stashed_messages),
        )
        if emit_event is not None:
            await emit_event(start_event)
        else:
            events.append(start_event)

        try:
            if stashed_messages and not in_task_compaction:
                self.runtime_service.stash_task_messages(task, stashed_messages)
                runtime_state = self.runtime_service.replace_runtime_messages(
                    task,
                    prefix_messages,
                    compact_result=original_compact_result,
                    preserve_pending_action_result=True,
                    preserve_cache_state=True,
                    preserve_exact_prompt_usage_baseline=True,
                )

            compact_result, compact_usage = await self._execute_compaction(
                task=task,
                source_messages=source_messages,
                compact_mode=compact_mode,
            )
            self.state_service.record_task_usage(task, compact_usage)

            restored_messages = [
                {"role": "system", "content": system_prompt},
                {"role": "assistant", "content": compact_result},
            ]
            if stashed_messages and not in_task_compaction:
                restored_messages.extend(
                    self.runtime_service.load_stashed_task_messages(task)
                )
                task.runtime_message_start_index = 2
            elif in_task_compaction:
                task.runtime_message_start_index = 1
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
                preserve_exact_prompt_usage_baseline=False,
            )
            if stashed_messages and not in_task_compaction:
                self.runtime_service.clear_stashed_task_messages(task)

            usage_after = self._build_usage_snapshot(
                task=task,
                runtime_state=runtime_state,
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
                        "compact_mode": compact_mode,
                        "threshold_percent": threshold_percent,
                        "usage_before": usage_before,
                        "usage_after": usage_after,
                        "compact_tokens": compact_usage,
                    },
                }
            )
            logger.info(
                "Context compact completed task_id=%s iteration=%s reason=%s "
                "compact_mode=%s elapsed_ms=%s used_percent_before=%s "
                "used_percent_after=%s used_tokens_before=%s used_tokens_after=%s "
                "compact_prompt_tokens=%s compact_completion_tokens=%s "
                "compact_total_tokens=%s",
                task.task_id,
                task.iteration,
                reason,
                compact_mode,
                round((perf_counter() - compact_started_at) * 1000),
                usage_before.get("used_percent"),
                usage_after.get("used_percent"),
                usage_before.get("used_tokens"),
                usage_after.get("used_tokens"),
                compact_usage.get("prompt_tokens"),
                compact_usage.get("completion_tokens"),
                compact_usage.get("total_tokens"),
            )
            return runtime_state, events
        except Exception as exc:
            logger.exception(
                "Context compact failed task_id=%s iteration=%s reason=%s "
                "compact_mode=%s elapsed_ms=%s",
                task.task_id,
                task.iteration,
                reason,
                compact_mode,
                round((perf_counter() - compact_started_at) * 1000),
            )
            if stashed_messages:
                runtime_state = self.runtime_service.replace_runtime_messages(
                    task,
                    original_messages,
                    compact_result=original_compact_result,
                    preserve_pending_action_result=True,
                    preserve_cache_state=True,
                    preserve_exact_prompt_usage_baseline=True,
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
                        "compact_mode": compact_mode,
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
        eager_state: _EagerToolExecutionState | None = None,
    ) -> Response:
        """Collect full model output via ``chat_stream`` while emitting live updates.

        When ``eager_state`` is provided, tool calls whose arguments complete
        during streaming are executed eagerly (before the full response
        finishes).  Periodic partial-parse events (``tool_payload_delta``)
        are emitted so the frontend can render arguments progressively.
        """
        stream_iterator = self.llm.chat_stream(
            messages=messages,
            **llm_chat_kwargs,
        )  # type: ignore[arg-type]

        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        # Accumulate tool_calls by list position across streaming chunks.
        tool_calls_by_pos: dict[int, dict[str, Any]] = {}
        # Per-call streaming state for partial-parse + eager execution.
        streaming_tool_states: dict[int, _StreamingToolCallState] = {}
        # Track finish_reason from streaming chunks (e.g. LENGTH = max_tokens hit).
        stream_finish_reason: FinishReason | None = None

        partial_parse_interval = (
            get_settings().REACT_TOOL_CALL_PARTIAL_PARSE_INTERVAL_MS / 1000
        )

        # Keep empty until provider emits a real response id.
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

            # Track the finish reason (e.g. LENGTH when max_tokens is hit).
            for chunk_choice in stream_chunk.choices:
                if chunk_choice.finish_reason is not None:
                    stream_finish_reason = chunk_choice.finish_reason

            for chunk_choice in stream_chunk.choices:
                chunk_message = chunk_choice.message
                reasoning_delta = chunk_message.reasoning_content
                if isinstance(reasoning_delta, str) and reasoning_delta:
                    reasoning_parts.append(reasoning_delta)
                    estimated_completion_tokens += estimate_text_tokens(reasoning_delta)
                    if token_meter_queue is not None:
                        await token_meter_queue.put(
                            {"type": "reasoning", "delta": reasoning_delta}
                        )

                content_delta = chunk_message.content
                if isinstance(content_delta, str) and content_delta:
                    content_parts.append(content_delta)
                    estimated_completion_tokens += estimate_text_tokens(content_delta)

                # Accumulate native tool_call fragments by position.
                if chunk_message.tool_calls:
                    for pos, tc in enumerate(chunk_message.tool_calls):
                        if not isinstance(tc, dict):
                            continue
                        # OpenAI Completion streams an explicit ``index`` field
                        # for parallel tool calls.  Fall back to ``pos`` for
                        # providers that don't use it (Anthropic, Gemini, etc.)
                        idx = tc.get("index")
                        if not isinstance(idx, int):
                            idx = pos
                        if idx not in tool_calls_by_pos:
                            tool_calls_by_pos[idx] = {
                                "id": "",
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            }
                        acc = tool_calls_by_pos[idx]
                        tc_id = tc.get("id", "")
                        if isinstance(tc_id, str) and tc_id:
                            acc["id"] = tc_id
                        func = tc.get("function")
                        if isinstance(func, dict):
                            name = func.get("name", "")
                            if isinstance(name, str) and name:
                                acc["function"]["name"] = name
                            args = func.get("arguments", "")
                            if isinstance(args, str) and args:
                                acc["function"]["arguments"] += args

                        # --- Streaming tool-call tracking ---
                        call_id = acc["id"]
                        call_name = acc["function"]["name"]
                        if not call_id or not call_name:
                            continue

                        if idx not in streaming_tool_states:
                            streaming_tool_states[idx] = _StreamingToolCallState(
                                call_id=call_id,
                                name=call_name,
                            )
                            # Emit tool_call with pending_arguments on first appearance.
                            if token_meter_queue is not None:
                                await token_meter_queue.put(
                                    {
                                        "type": "action",
                                        "action_type": "CALL_TOOL",
                                    }
                                )
                                await token_meter_queue.put(
                                    {
                                        "type": "tool_call",
                                        "tool_calls": [
                                            {
                                                "id": call_id,
                                                "name": call_name,
                                                "arguments": {},
                                                "pending_arguments": True,
                                            }
                                        ],
                                        "tool_results": [],
                                    }
                                )

                        st = streaming_tool_states[idx]
                        if st.arguments_complete:
                            continue

                        # Update accumulated JSON from the assembled arguments.
                        st.accumulated_json = acc["function"]["arguments"]

            # --- Periodic partial parse for tool_payload_delta ---
            now = perf_counter()
            if token_meter_queue is not None or eager_state is not None:
                for _pos, st in streaming_tool_states.items():
                    if st.arguments_complete or not st.accumulated_json:
                        continue
                    if now - st.last_parse_time < partial_parse_interval:
                        continue
                    st.last_parse_time = now

                    parsed = try_partial_parse(st.accumulated_json)
                    if parsed is None:
                        continue

                    # Diff: emit newly completed arguments.
                    for key, value in parsed.items():
                        if (
                            key not in st.last_parsed_result
                            and token_meter_queue is not None
                        ):
                            await token_meter_queue.put(
                                {
                                    "type": "tool_payload_delta",
                                    "tool_call_id": st.call_id,
                                    "tool_name": st.name,
                                    "argument_name": key,
                                    "payload_name": key,
                                    "delta": json.dumps(value, ensure_ascii=False)
                                    if not isinstance(value, str)
                                    else value,
                                    "is_final": True,
                                }
                            )
                    st.last_parsed_result = dict(parsed)

                    # Check if arguments are now complete JSON.
                    try:
                        final_args = json.loads(st.accumulated_json)
                        if isinstance(final_args, dict):
                            self._finalize_streaming_tool_call(
                                st,
                                final_args,
                                token_meter_queue,
                                eager_state,
                            )
                    except json.JSONDecodeError:
                        pass

            # Token rate reporting.
            if token_meter_queue is not None and now - last_report_at >= 1.0:
                window_seconds = max(now - last_report_at, 1e-6)
                window_tokens = max(estimated_completion_tokens - last_report_tokens, 0)
                await token_meter_queue.put(
                    {
                        "type": "token_rate",
                        "tokens_per_second": round(window_tokens / window_seconds, 2),
                        "estimated_completion_tokens": estimated_completion_tokens,
                    }
                )
                last_report_at = now
                last_report_tokens = estimated_completion_tokens

        # --- Finalize any remaining streaming tool calls ---
        for _pos, st in streaming_tool_states.items():
            if st.arguments_complete:
                continue
            if not st.accumulated_json:
                continue
            try:
                final_args = json.loads(st.accumulated_json)
                if isinstance(final_args, dict):
                    self._finalize_streaming_tool_call(
                        st, final_args, token_meter_queue, eager_state
                    )
            except json.JSONDecodeError:
                logger.warning(
                    "Streaming tool call arguments are not valid JSON at stream end. "
                    "call_id=%s name=%s",
                    st.call_id,
                    st.name,
                )

        # Drain any completed eager results before returning.
        if eager_state is not None:
            await self._drain_eager_results(eager_state, token_meter_queue)

        # Final token-rate flush.
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

        # Usage fallback.
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

        # Assemble tool_calls from accumulated fragments.
        assembled_tool_calls: list[dict[str, Any]] | None = None
        if tool_calls_by_pos:
            assembled_tool_calls = [
                tool_calls_by_pos[i]
                for i in sorted(tool_calls_by_pos)
                if tool_calls_by_pos[i]["id"]
            ]
            if not assembled_tool_calls:
                assembled_tool_calls = None

        # Warn when max_tokens truncated a response that included tool calls.
        if stream_finish_reason == FinishReason.LENGTH and assembled_tool_calls:
            for tc in assembled_tool_calls:
                args = tc.get("function", {}).get("arguments", "")
                try:
                    json.loads(args)
                except (json.JSONDecodeError, TypeError):
                    logger.warning(
                        "max_tokens truncated a tool_use call — arguments are "
                        "incomplete JSON. The tool call will likely fail. "
                        "Consider increasing max_tokens. call_id=%s name=%s "
                        "args_prefix=%s",
                        tc.get("id", ""),
                        tc.get("function", {}).get("name", ""),
                        args[:100],
                    )

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
                    finish_reason=stream_finish_reason,
                    message=ChatMessage(
                        role="assistant",
                        content=full_content,
                        reasoning_content=full_reasoning,
                        tool_calls=assembled_tool_calls,
                    ),
                )
            ],
            created=int(datetime.now(UTC).timestamp()),
            model=response_model,
            usage=usage_info,
        )

    def _finalize_streaming_tool_call(
        self,
        st: _StreamingToolCallState,
        final_args: dict[str, Any],
        token_meter_queue: asyncio.Queue[dict[str, Any]] | None,
        eager_state: _EagerToolExecutionState | None,
    ) -> None:
        """Mark one streaming tool call as complete and optionally start eager execution."""
        st.arguments_complete = True

        # Emit remaining arguments not caught by partial parse.
        for key, value in final_args.items():
            if key not in st.last_parsed_result and token_meter_queue is not None:
                delta = (
                    json.dumps(value, ensure_ascii=False)
                    if not isinstance(value, str)
                    else value
                )
                token_meter_queue.put_nowait(
                    {
                        "type": "tool_payload_delta",
                        "tool_call_id": st.call_id,
                        "tool_name": st.name,
                        "argument_name": key,
                        "payload_name": key,
                        "delta": delta,
                        "is_final": True,
                    }
                )

        # Emit finalized tool_call (no pending_arguments).
        if token_meter_queue is not None:
            token_meter_queue.put_nowait(
                {
                    "type": "tool_call",
                    "tool_calls": [
                        {
                            "id": st.call_id,
                            "name": st.name,
                            "arguments": final_args,
                            "pending_arguments": False,
                        }
                    ],
                    "tool_results": [],
                }
            )

        # Start eager execution.
        if eager_state is not None and st.call_id not in eager_state.started_call_ids:
            eager_state.started_call_ids.add(st.call_id)
            tool_call = ToolCallRequest(
                id=st.call_id, name=st.name, arguments=final_args
            )
            execution_task = asyncio.create_task(
                self._execute_tool_call_request(tool_call)
            )
            eager_state.running_tasks[st.call_id] = execution_task

    async def _drain_eager_results(
        self,
        eager_state: _EagerToolExecutionState,
        token_meter_queue: asyncio.Queue[dict[str, Any]] | None,
    ) -> None:
        """Collect completed eager tool execution results."""
        for call_id, task in list(eager_state.running_tasks.items()):
            if not task.done():
                continue
            try:
                result = task.result()
                eager_state.result_by_call_id[call_id] = result
                del eager_state.running_tasks[call_id]
                if token_meter_queue is not None:
                    await token_meter_queue.put(
                        {"type": "tool_result", "tool_results": [result]}
                    )
            except Exception:
                logger.warning("Eager tool execution failed for call_id=%s", call_id)

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
        consuming the whole iteration budget with identical retries.  However,
        a 4xx with an empty response body usually signals a transient
        server-side glitch (the provider opened an SSE stream but crashed
        before sending any data), so we treat it as retryable.
        """
        current: BaseException | None = exc
        while current is not None:
            response = getattr(current, "response", None)
            status_code = getattr(response, "status_code", None)

            if (
                isinstance(status_code, int)
                and 400 <= status_code < 500
                and status_code not in {408, 409, 429}
            ):
                # An empty body on a 4xx is almost certainly a transient
                # server-side issue rather than a client-side mistake.
                body_text = ""
                if response is not None:
                    with contextlib.suppress(Exception):
                        body_text = (response.text or "").strip()
                if not body_text:
                    logger.warning(
                        "LLM returned HTTP %s with empty body — treating as "
                        "transient (retryable) rather than non-retryable. "
                        "This often indicates provider-side instability.",
                        status_code,
                    )
                    return False
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

    def _build_next_pending_action_result(
        self, event_data: dict[str, Any]
    ) -> list[dict[str, Any]] | None:
        """Derive next recursion's action_result payload from current action output.

        After the native tool calling migration, CALL_TOOL results are fed back
        via the message converter (``tool_results`` on the user message), so this
        method only handles non-tool action types.
        """
        action_type = event_data.get("action_type")
        if action_type == "CLARIFY":
            output = event_data.get("output", {})
            return [{"result": output if isinstance(output, dict) else {}}]
        return None

    @staticmethod
    def _compact_result_for_llm(tool_name: str, raw_result: Any) -> Any:
        """Strip tool-result fields that the LLM does not need.

        SSE events and DB persistence receive the full result; this method
        only affects what is injected into the next recursion's user message.

        Args:
            tool_name: Name of the tool that produced the result.
            raw_result: Raw tool return value (dict, str, etc.).

        Returns:
            A compacted copy suitable for LLM consumption.
        """
        if not isinstance(raw_result, dict):
            return raw_result

        if tool_name == "create_preview_endpoint":
            keep = {"preview_id", "title", "port", "path", "proxy_url"}
            return {k: v for k, v in raw_result.items() if k in keep}

        if tool_name == "web_search":
            strip_top = {
                "provider_request",
                "provider_response_metadata",
                "applied_parameters",
                "ignored_parameters",
                "provider",
            }
            strip_per_result = {
                "favicon_url",
                "resource_type",
                "score",
                "metadata",
                "source",
            }
            compact = {k: v for k, v in raw_result.items() if k not in strip_top}
            results = compact.get("results")
            if isinstance(results, list):
                compact["results"] = [
                    {k: v for k, v in r.items() if k not in strip_per_result}
                    for r in results
                    if isinstance(r, dict)
                ]
            return compact

        if tool_name == "search":
            strip_top = {
                "query",
                "path",
                "regex",
                "case_sensitive",
                "max_candidates",
                "max_hits_per_file",
            }
            strip_per_candidate = {
                "first_match_line",
                "last_match_line",
                "anchors_truncated",
            }
            compact = {k: v for k, v in raw_result.items() if k not in strip_top}
            candidates = compact.get("candidates")
            if isinstance(candidates, list):
                compact["candidates"] = [
                    {k: v for k, v in c.items() if k not in strip_per_candidate}
                    for c in candidates
                    if isinstance(c, dict)
                ]
            return compact

        if tool_name == "run_bash":
            return {k: v for k, v in raw_result.items() if k != "ok"}

        if tool_name == "edit_file":
            return {
                k: v
                for k, v in raw_result.items()
                if k not in {"message", "content_hash", "diff"}
            }

        if tool_name in ("read_file", "write_file"):
            return {
                k: v for k, v in raw_result.items() if k not in {"content_hash", "diff"}
            }

        # Generic: strip the unified pivot_action envelope from any tool.
        if "pivot_action" in raw_result:
            return {k: v for k, v in raw_result.items() if k != "pivot_action"}

        return raw_result

    def _compact_tool_results(
        self,
        tool_results: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]] | None:
        """Build compacted tool results in the internal unified format.

        Every result always has ``tool_call_id``, ``name``, ``result``, and
        ``is_error``.  The ``result`` value is always a **string** because
        all provider APIs (Anthropic, OpenAI Completion, OpenAI Response,
        Gemini) require string content in their tool-result message fields.
        """
        if not tool_results:
            return None
        compacted: list[dict[str, Any]] = []
        for result_item in tool_results:
            if not isinstance(result_item, dict):
                continue
            if result_item.get("success") is True:
                raw_result = self._compact_result_for_llm(
                    result_item.get("name", ""), result_item.get("result")
                )
                result_str = (
                    raw_result
                    if isinstance(raw_result, str)
                    else json.dumps(raw_result, ensure_ascii=False)
                )
                compact_item: dict[str, Any] = {
                    "tool_call_id": result_item.get("tool_call_id", ""),
                    "name": result_item.get("name", ""),
                    "result": result_str,
                    "is_error": False,
                }
            else:
                compact_item = {
                    "tool_call_id": result_item.get("tool_call_id", ""),
                    "name": result_item.get("name", ""),
                    "result": result_item.get("error", "Tool execution failed"),
                    "is_error": True,
                }
            compacted.append(compact_item)
        return compacted or None

    def _extract_pivot_action_from_tool_results(
        self,
        tool_results: list[dict[str, Any]],
        *,
        category_filter: str | None = None,
    ) -> dict[str, Any] | None:
        """Extract a pivot_action envelope from tool results.

        Args:
            tool_results: Tool result dicts from ``_execute_tool_call_request``.
            category_filter: If set, only return actions matching this category
                (e.g. ``"approval"``).

        Returns:
            The ``pivot_action`` dict or ``None``.
        """
        for result_item in tool_results:
            if result_item.get("success") is not True:
                continue
            raw_result = result_item.get("result")
            if not isinstance(raw_result, dict):
                continue
            pivot_action = raw_result.get("pivot_action")
            if not isinstance(pivot_action, dict):
                continue
            if (
                category_filter is not None
                and pivot_action.get("category") != category_filter
            ):
                continue
            return dict(pivot_action)
        return None

    @staticmethod
    def _write_tool_path(tool_call: ToolCallRequest) -> str | None:
        """Return a normalized target path for tools that write one file."""
        if tool_call.name not in {"edit_file", "write_file"}:
            return None
        raw_path = tool_call.arguments.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            return None
        normalized = raw_path.strip().replace("\\", "/")
        if normalized.startswith("/workspace/"):
            normalized = normalized.removeprefix("/workspace/")
        return normalized.strip("/")

    @classmethod
    def _has_duplicate_write_paths(cls, tool_calls: list[ToolCallRequest]) -> bool:
        """Return whether a batch contains multiple writes to the same file."""
        seen: set[str] = set()
        for tool_call in tool_calls:
            path = cls._write_tool_path(tool_call)
            if path is None:
                continue
            if path in seen:
                return True
            seen.add(path)
        return False

    @classmethod
    def _has_unfinished_prior_write_to_same_path(
        cls,
        tool_call: ToolCallRequest,
        batch_calls: list[ToolCallRequest],
        completed_call_ids: set[str],
    ) -> bool:
        """Return whether an earlier same-file write in this batch is unfinished."""
        path = cls._write_tool_path(tool_call)
        if path is None:
            return False
        for prior_call in batch_calls:
            if prior_call.id == tool_call.id:
                return False
            if (
                cls._write_tool_path(prior_call) == path
                and prior_call.id not in completed_call_ids
            ):
                return True
        return False

    async def _emit_tool_result(
        self,
        token_meter_queue: asyncio.Queue[dict[str, Any]] | None,
        result_item: dict[str, Any],
    ) -> None:
        """Emit one live tool result when streaming is active."""
        if token_meter_queue is None:
            return
        await token_meter_queue.put(
            {
                "type": "tool_result",
                "tool_results": [result_item],
            }
        )

    async def _emit_tool_call(
        self,
        token_meter_queue: asyncio.Queue[dict[str, Any]] | None,
        tool_calls: list[ToolCallRequest],
    ) -> None:
        """Emit live tool-call start events when streaming is active."""
        if token_meter_queue is None or not tool_calls:
            return
        await token_meter_queue.put(
            {
                "type": "tool_call",
                "tool_calls": [tool_call.to_dict() for tool_call in tool_calls],
                "tool_results": [],
            }
        )

    async def _execute_tool_call_request(
        self,
        tool_call: ToolCallRequest,
    ) -> dict[str, Any]:
        """Execute one validated tool call and normalize its result payload."""
        write_path = self._write_tool_path(tool_call)
        if write_path is not None:
            lock = self._write_tool_locks.setdefault(write_path, asyncio.Lock())
            async with lock:
                return await self._execute_tool_call_request_unlocked(tool_call)
        return await self._execute_tool_call_request_unlocked(tool_call)

    async def _execute_tool_call_request_unlocked(
        self,
        tool_call: ToolCallRequest,
    ) -> dict[str, Any]:
        """Execute one tool call after any required resource lock is held."""
        # Delegation is handled at the engine level (async sub-task),
        # not through the sync tool execution path.
        if tool_call.name == "delegate_to_agent":
            return await self._execute_delegation(tool_call)

        # Plan tool is intercepted for file I/O and approval flow.
        if tool_call.name == "plan":
            return await self._execute_plan_tool(tool_call)

        # Task tool is intercepted for file I/O (step tracking).
        if tool_call.name == "task":
            return await self._execute_task_tool(tool_call)

        try:
            result = await run_in_threadpool(
                self.tool_manager.execute,
                tool_call.name,
                context=self.tool_execution_context,
                **tool_call.arguments,
            )
            return {
                "tool_call_id": tool_call.id,
                "name": tool_call.name,
                "arguments": tool_call.arguments,
                "result": result,
                "success": True,
            }
        except Exception as e:
            logger.error("Tool %s execution failed: %s", tool_call.name, e)
            if "not found in registry" in str(e):
                available_tools = self.tool_manager.list_tools()
                tool_names = [tool.name for tool in available_tools]
                error_msg = (
                    f"Tool '{tool_call.name}' not found. "
                    f"Available tools: {', '.join(tool_names)}"
                )
            else:
                error_msg = f"Tool execution failed: {e!s}"
            return {
                "tool_call_id": tool_call.id,
                "name": tool_call.name,
                "arguments": tool_call.arguments,
                "error": error_msg,
                "success": False,
            }

    async def _execute_delegation(
        self,
        tool_call: ToolCallRequest,
    ) -> dict[str, Any]:
        """Execute an agent-to-agent delegation as a sub-task.

        Supports two modes:

        1. **New delegation**: caller provides ``agent`` (alias) and
           ``instruction``. Resolves callee, creates delegation session/task,
           and runs the sub-agent ReAct loop.
        2. **Resume delegation**: caller provides ``delegation_context_id``
           and ``response`` to answer a sub-agent's CLARIFY question. Finds
           the paused session/task and resumes the sub-agent loop.
        """
        from app.services.agent_delegation_service import AgentDelegationService
        from app.services.delegation_executor import DelegationExecutor

        if self.tool_execution_context is None:
            return {
                "tool_call_id": tool_call.id,
                "name": tool_call.name,
                "arguments": tool_call.arguments,
                "error": "No execution context available for delegation",
                "success": False,
            }

        ctx = self.tool_execution_context

        # --- Resume mode (CLARIFY response) ---
        delegation_context_id = tool_call.arguments.get("delegation_context_id")
        response = tool_call.arguments.get("response")
        delegation_on_event = self._make_delegation_event_callback()

        if delegation_context_id:
            if not response:
                return {
                    "tool_call_id": tool_call.id,
                    "name": tool_call.name,
                    "arguments": tool_call.arguments,
                    "error": "'response' is required when providing delegation_context_id",
                    "success": False,
                }
            try:
                executor = DelegationExecutor(self.db)
                result = await executor.resume_delegation(
                    delegation_context_id=delegation_context_id,
                    caller_context=ctx,
                    response=response,
                    on_event=delegation_on_event,
                )
                return {
                    "tool_call_id": tool_call.id,
                    "name": tool_call.name,
                    "arguments": tool_call.arguments,
                    "result": result,
                    "success": True,
                }
            except Exception as e:
                logger.error("Delegation resume failed: %s", e)
                return {
                    "tool_call_id": tool_call.id,
                    "name": tool_call.name,
                    "arguments": tool_call.arguments,
                    "error": f"Delegation resume failed: {e!s}",
                    "success": False,
                }

        # --- New delegation mode ---
        agent_alias = tool_call.arguments.get("agent", "")
        instruction = tool_call.arguments.get("instruction", "")

        if not agent_alias or not instruction:
            return {
                "tool_call_id": tool_call.id,
                "name": tool_call.name,
                "arguments": tool_call.arguments,
                "error": "Both 'agent' and 'instruction' parameters are required",
                "success": False,
            }

        delegation_service = AgentDelegationService(self.db)
        delegation = delegation_service.resolve_by_alias(ctx.agent_id, agent_alias)

        if delegation is None:
            return {
                "tool_call_id": tool_call.id,
                "name": tool_call.name,
                "arguments": tool_call.arguments,
                "error": (
                    f"Agent '{agent_alias}' not found in delegation list. "
                    "Check the available agents in your instructions."
                ),
                "success": False,
            }

        callee = self.db.get(Agent, delegation.callee_agent_id)
        if (
            callee is None
            or not callee.allow_delegation
            or callee.active_release_id is None
        ):
            return {
                "tool_call_id": tool_call.id,
                "name": tool_call.name,
                "arguments": tool_call.arguments,
                "error": (
                    f"Agent '{agent_alias}' is currently unavailable for delegation."
                ),
                "success": False,
            }

        try:
            executor = DelegationExecutor(self.db)
            result = await executor.execute_delegation(
                caller_context=ctx,
                caller_task_id=getattr(self, "_current_task_id", ""),
                caller_agent_id=ctx.agent_id,
                delegation_depth=getattr(self, "_current_task_delegation_depth", 0),
                delegation=delegation,
                instruction=instruction,
                on_event=delegation_on_event,
            )
            return {
                "tool_call_id": tool_call.id,
                "name": tool_call.name,
                "arguments": tool_call.arguments,
                "result": result,
                "success": True,
            }
        except Exception as e:
            logger.error("Delegation execution failed: %s", e)
            return {
                "tool_call_id": tool_call.id,
                "name": tool_call.name,
                "arguments": tool_call.arguments,
                "error": f"Delegation failed: {e!s}",
                "success": False,
            }

    async def _execute_plan_tool(
        self,
        tool_call: ToolCallRequest,
    ) -> dict[str, Any]:
        """Handle the ``plan`` tool call — engine-intercepted for file I/O.

        The plan tool writes a free-form Markdown file under
        ``{workspace}/.pivot/plans/{task_id}.md`` and pauses execution for
        user approval.
        """
        from .plan_files import write_plan_text

        if self.tool_execution_context is None:
            return {
                "tool_call_id": tool_call.id,
                "name": tool_call.name,
                "arguments": tool_call.arguments,
                "error": "No execution context available for plan tool",
                "success": False,
            }

        workspace_path = self.tool_execution_context.workspace_backend_path
        task_id = self._current_task_id
        if not task_id:
            return {
                "tool_call_id": tool_call.id,
                "name": tool_call.name,
                "arguments": tool_call.arguments,
                "error": "No active task for plan tool",
                "success": False,
            }

        plan_text = tool_call.arguments.get("plan_text")

        try:
            if plan_text is not None:
                write_plan_text(workspace_path, task_id, plan_text)
                self._plan_pending_review = True

            return {
                "tool_call_id": tool_call.id,
                "name": tool_call.name,
                "arguments": tool_call.arguments,
                "result": {"success": True},
                "success": True,
            }
        except Exception as e:
            logger.error("Plan tool execution failed: %s", e)
            return {
                "tool_call_id": tool_call.id,
                "name": tool_call.name,
                "arguments": tool_call.arguments,
                "error": f"Plan tool failed: {e!s}",
                "success": False,
            }

    async def _execute_task_tool(
        self,
        tool_call: ToolCallRequest,
    ) -> dict[str, Any]:
        """Handle the ``task`` tool call — engine-intercepted for file I/O.

        The task tool creates or updates structured steps in
        ``{workspace}/.pivot/plans/{task_id}.json``.
        """
        from .plan_files import update_steps, write_steps

        if self.tool_execution_context is None:
            return {
                "tool_call_id": tool_call.id,
                "name": tool_call.name,
                "arguments": tool_call.arguments,
                "error": "No execution context available for task tool",
                "success": False,
            }

        workspace_path = self.tool_execution_context.workspace_backend_path
        task_id = self._current_task_id
        if not task_id:
            return {
                "tool_call_id": tool_call.id,
                "name": tool_call.name,
                "arguments": tool_call.arguments,
                "error": "No active task for task tool",
                "success": False,
            }

        action = tool_call.arguments.get("action")
        steps = tool_call.arguments.get("steps")

        # Some LLMs pass list/object params as JSON strings — normalise.
        if isinstance(steps, str):
            try:
                steps = json.loads(steps)
            except (json.JSONDecodeError, ValueError):
                return {
                    "tool_call_id": tool_call.id,
                    "name": tool_call.name,
                    "arguments": tool_call.arguments,
                    "error": "Invalid JSON in 'steps' parameter",
                    "success": False,
                }
        if steps is not None and not isinstance(steps, list):
            steps = None

        if action not in ("create", "update"):
            return {
                "tool_call_id": tool_call.id,
                "name": tool_call.name,
                "arguments": tool_call.arguments,
                "error": f"Invalid action '{action}'. Must be 'create' or 'update'.",
                "success": False,
            }

        if not steps:
            return {
                "tool_call_id": tool_call.id,
                "name": tool_call.name,
                "arguments": tool_call.arguments,
                "error": "'steps' parameter is required and must be non-empty.",
                "success": False,
            }

        try:
            if action == "create":
                write_steps(workspace_path, task_id, steps)
            else:  # update
                update_steps(workspace_path, task_id, steps)

            return {
                "tool_call_id": tool_call.id,
                "name": tool_call.name,
                "arguments": tool_call.arguments,
                "result": {"success": True},
                "success": True,
            }
        except Exception as e:
            logger.error("Task tool execution failed: %s", e)
            return {
                "tool_call_id": tool_call.id,
                "name": tool_call.name,
                "arguments": tool_call.arguments,
                "error": f"Task tool failed: {e!s}",
                "success": False,
            }

    def _make_delegation_event_callback(
        self,
    ) -> Any:
        """Create an ``on_event`` callback for ``DelegationExecutor``.

        The callback puts delegation-level events into the engine's
        delegation event queue so they can be yielded by the meter pump
        loop and forwarded to the parent task's SSE subscribers.
        """

        async def _on_delegation_event(event: dict[str, Any]) -> None:
            await self._delegation_event_queue.put(event)

        return _on_delegation_event

    async def execute_recursion(
        self,
        task: ReactTask,
        context: ReactContext,
        trace_id: str,
        input_message: dict[str, Any],
        messages: list[dict[str, Any]],
        llm_chat_kwargs: dict[str, Any] | None = None,
        token_meter_queue: asyncio.Queue[dict[str, Any]] | None = None,
    ) -> tuple[ReactRecursion, dict[str, Any]]:
        """Execute a single recursion cycle.

        Routes LLM response to native tool calling or text-action parsing:
        - Native ``tool_calls`` in the response trigger the CALL_TOOL path.
        - Text-only responses are parsed as JSON for CLARIFY/ANSWER.

        Args:
            task: The ReactTask being executed.
            context: Current context state.
            input_message: Exact per-recursion user message appended for this cycle.
            messages: Message history for LLM.
            llm_chat_kwargs: Extra runtime kwargs passed to LLM chat call.
            token_meter_queue: Optional queue for realtime token-rate snapshots.

        Returns:
            Tuple of (ReactRecursion record, event data for streaming).
        """
        task_id_value = task.task_id
        task_iteration_value = task.iteration
        context.update_for_new_recursion(trace_id)
        recursion = self.state_service.start_recursion(task, trace_id, input_message)

        try:
            token_counter = self._new_token_counter()
            response: Response | None = None
            message: ChatMessage | None = None
            decision: ParsedReactDecision | None = None
            parse_error: ValueError | None = None
            request_messages = messages
            native_tool_calls: list[dict[str, Any]] | None = None
            call_tool_message: str = ""
            eager_state: _EagerToolExecutionState | None = None

            # Build native tools parameter for all LLM calls in this recursion.
            tools = self.tool_manager.to_openai_tools()
            effective_kwargs: dict[str, Any] = {
                **(llm_chat_kwargs or {}),
                "tools": tools,
            }

            for parse_attempt in range(PARSE_RETRY_LIMIT + 1):
                # Enable eager execution on first streaming attempt.
                eager_state = (
                    _EagerToolExecutionState()
                    if self.stream_llm_responses and parse_attempt == 0
                    else None
                )
                if self.stream_llm_responses:
                    response = await self._stream_chat_response(
                        messages=request_messages,
                        llm_chat_kwargs=effective_kwargs,
                        token_counter=token_counter,
                        token_meter_queue=token_meter_queue,
                        eager_state=eager_state,
                    )
                else:
                    response = await run_in_threadpool(
                        self.llm.chat,
                        messages=request_messages,
                        **effective_kwargs,
                    )
                    self._accumulate_usage(token_counter, response.usage)
                    self._ensure_total_tokens(token_counter)

                choice = response.first()
                message = choice.message

                # Native tool_calls → CALL_TOOL path.
                if message.tool_calls:
                    native_tool_calls = message.tool_calls
                    # Extract user-facing message from the JSON envelope
                    # that accompanies native tool calls.
                    call_tool_message = self._extract_call_tool_message(message.content)
                    logger.debug(
                        "LLM returned native tool_calls (trace_id=%s, count=%s, has_message=%s)",
                        trace_id,
                        len(native_tool_calls),
                        bool(call_tool_message),
                    )
                    break

                # Text-only response → parse as text action.
                content = message.content or "{}"
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
                        "Failed to parse LLM response\n"
                        "Trace ID: %s\nTask ID: %s\nIteration: %s\nError: %s",
                        trace_id,
                        task.task_id,
                        task.iteration,
                        e,
                    )
                    break

            # --- Parse failure: no tool_calls, no valid decision ---
            if response is None or (decision is None and native_tool_calls is None):
                parse_error_message = str(parse_error or "Failed to parse LLM output")
                tokens_data = self.state_service.finalize_error(
                    task, recursion, parse_error_message, token_counter
                )
                return recursion, {
                    "trace_id": trace_id,
                    "action_type": "ERROR",
                    "error": parse_error_message,
                    "tokens": tokens_data,
                    "assistant_message": None,
                    "rollback_messages": True,
                    "llm_response_id": response.id if response is not None else None,
                }

            # --- CALL_TOOL path: native tool_calls ---
            assert message is not None  # guaranteed by response check above
            if native_tool_calls is not None:
                # Wait for any remaining eager tasks to complete.
                if eager_state is not None and eager_state.running_tasks:
                    await self._wait_eager_tasks(eager_state, token_meter_queue)

                return await self._execute_call_tool_recursion(
                    task=task,
                    recursion=recursion,
                    context=context,
                    trace_id=trace_id,
                    message=message,
                    native_tool_calls=native_tool_calls,
                    token_counter=token_counter,
                    token_meter_queue=token_meter_queue,
                    response=response,
                    eager_state=eager_state,
                    call_tool_message=call_tool_message,
                )

            # --- Text action path: CLARIFY / ANSWER ---
            assert decision is not None  # guaranteed: native_tool_calls is None
            return self._execute_text_action_recursion(
                task=task,
                recursion=recursion,
                context=context,
                trace_id=trace_id,
                message=message,
                decision=decision,
                token_counter=token_counter,
                response=response,
            )

        except Exception as e:
            error_msg = str(e)
            is_timeout_error = self._is_timeout_error(e)
            non_retryable_error = self._is_non_retryable_llm_error(e)
            logger.error(
                "Recursion execution failed for trace_id=%s\n"
                "Error type: %s\nError message: %s\n"
                "Task ID: %s\nIteration: %s",
                trace_id,
                type(e).__name__,
                error_msg,
                task_id_value,
                task_iteration_value,
            )

            tokens_data = self.state_service.finalize_error(task, recursion, error_msg)
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

    # ------------------------------------------------------------------
    # Eager execution helpers
    # ------------------------------------------------------------------

    async def _wait_eager_tasks(
        self,
        eager_state: _EagerToolExecutionState,
        token_meter_queue: asyncio.Queue[dict[str, Any]] | None,
    ) -> None:
        """Wait for all running eager tasks to finish and collect their results."""
        while eager_state.running_tasks:
            await asyncio.wait(
                set(eager_state.running_tasks.values()),
                return_when=asyncio.FIRST_COMPLETED,
            )
            await self._drain_eager_results(eager_state, token_meter_queue)

    # ------------------------------------------------------------------
    # CALL_TOOL path
    # ------------------------------------------------------------------

    @staticmethod
    def _convert_native_tool_calls(
        native_tool_calls: list[dict[str, Any]],
    ) -> list[ToolCallRequest]:
        """Convert native tool_call dicts to internal ToolCallRequest objects.

        Native format has ``function.arguments`` as a JSON string.
        We parse it into a dict for internal use.
        """
        requests: list[ToolCallRequest] = []
        for tc in native_tool_calls:
            call_id = tc.get("id", "") or ""
            func = tc.get("function", {})
            name = func.get("name", "") if isinstance(func, dict) else ""
            raw_args = func.get("arguments", "{}") if isinstance(func, dict) else "{}"

            if isinstance(raw_args, str):
                try:
                    arguments = json.loads(raw_args) if raw_args.strip() else {}
                except json.JSONDecodeError:
                    logger.warning(
                        "Failed to parse tool_call arguments as JSON: %s",
                        raw_args[:200],
                    )
                    arguments = {}
            elif isinstance(raw_args, dict):
                arguments = raw_args
            else:
                arguments = {}

            if not isinstance(arguments, dict):
                arguments = {}

            requests.append(ToolCallRequest(id=call_id, name=name, arguments=arguments))
        return requests

    async def _execute_tool_calls_concurrent(
        self,
        tool_calls: list[ToolCallRequest],
        token_meter_queue: asyncio.Queue[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        """Execute tool calls concurrently, serializing writes to the same file."""
        if not tool_calls:
            return []

        # Sequential when only one call or duplicate write paths.
        if len(tool_calls) == 1 or self._has_duplicate_write_paths(tool_calls):
            results: list[dict[str, Any]] = []
            for tool_call in tool_calls:
                result = await self._execute_tool_call_request(tool_call)
                results.append(result)
                if token_meter_queue is not None:
                    await token_meter_queue.put(
                        {"type": "tool_result", "tool_results": [result]}
                    )
            return results

        # Concurrent execution.
        async def _run_and_emit(tc: ToolCallRequest) -> dict[str, Any]:
            result = await self._execute_tool_call_request(tc)
            if token_meter_queue is not None:
                await token_meter_queue.put(
                    {"type": "tool_result", "tool_results": [result]}
                )
            return result

        tasks = [asyncio.create_task(_run_and_emit(tc)) for tc in tool_calls]
        results_list: list[dict[str, Any]] = []
        for coro in asyncio.as_completed(tasks):
            results_list.append(await coro)
        return results_list

    @staticmethod
    def _extract_call_tool_message(content: str | None) -> str:
        """Extract the user-facing message from a CALL_TOOL text envelope.

        The LLM may emit truncated JSON when text and tool_calls coexist in one
        response, so we use partial parsing instead of ``parse_react_output``
        which requires valid JSON.
        """
        if not content or not content.strip():
            return ""

        stripped = content.strip()
        if not stripped.startswith("{"):
            return stripped

        parsed = try_partial_parse(stripped)
        if parsed is None:
            return stripped

        message = parsed.get("message")
        if isinstance(message, str):
            return message
        return ""

    async def _execute_call_tool_recursion(
        self,
        *,
        task: ReactTask,
        recursion: ReactRecursion,
        context: ReactContext,
        trace_id: str,
        message: ChatMessage,
        native_tool_calls: list[dict[str, Any]],
        token_counter: dict[str, int],
        token_meter_queue: asyncio.Queue[dict[str, Any]] | None,
        response: Response,
        eager_state: _EagerToolExecutionState | None = None,
        call_tool_message: str = "",
    ) -> tuple[ReactRecursion, dict[str, Any]]:
        """Execute native tool calls and build the recursion event.

        When ``eager_state`` is provided, tool calls that were already
        executed during streaming are reused instead of re-executed.
        """
        tool_call_requests = self._convert_native_tool_calls(native_tool_calls)

        # Separate eager-completed calls from pending ones.
        result_by_call_id: dict[str, dict[str, Any]] = {}
        if eager_state is not None:
            result_by_call_id = dict(eager_state.result_by_call_id)

        pending_calls = [
            tc for tc in tool_call_requests if tc.id not in result_by_call_id
        ]

        # Emit lifecycle events only for non-eagerly-started calls.
        if pending_calls:
            eager_started = (
                eager_state.started_call_ids if eager_state is not None else set()
            )
            if token_meter_queue is not None and not eager_started:
                await token_meter_queue.put(
                    {"type": "action", "action_type": "CALL_TOOL"}
                )
            await self._emit_tool_call(token_meter_queue, pending_calls)

            # Execute remaining tool calls.
            new_results = await self._execute_tool_calls_concurrent(
                pending_calls, token_meter_queue
            )
            for result_item in new_results:
                call_id = result_item.get("tool_call_id")
                if isinstance(call_id, str):
                    result_by_call_id[call_id] = result_item

        # Merge results in tool_call order.
        tool_results = [
            result_by_call_id[tc.id]
            for tc in tool_call_requests
            if tc.id in result_by_call_id
        ]

        # Extract multimodal blocks from results for next-iteration injection.
        for result_item in tool_results:
            if result_item.get("success") is not True:
                continue
            raw_result = result_item.get("result")
            if isinstance(raw_result, dict):
                multimodal_blocks = raw_result.pop("_pivot_multimodal_blocks", None)
                if isinstance(multimodal_blocks, list):
                    self._pending_multimodal_blocks.extend(multimodal_blocks)

        reconstructed_tool_calls = [tc.to_dict() for tc in tool_call_requests]
        action_output: dict[str, Any] = {"tool_calls": reconstructed_tool_calls}

        pending_user_action = self._extract_pivot_action_from_tool_results(
            tool_results, category_filter="approval"
        )

        # Check for approval → skip remaining calls if found.
        if pending_user_action:
            executed_ids = {
                r.get("tool_call_id") for r in tool_results if isinstance(r, dict)
            }
            for tc in tool_call_requests:
                if tc.id not in executed_ids:
                    skipped = {
                        "tool_call_id": tc.id,
                        "name": tc.name,
                        "arguments": tc.arguments,
                        "error": "Tool skipped because an earlier tool requested user action.",
                        "success": False,
                    }
                    tool_results.append(skipped)
                    if token_meter_queue is not None:
                        await token_meter_queue.put(
                            {"type": "tool_result", "tool_results": [skipped]}
                        )

        tokens_data = self.state_service.record_llm_decision(
            task=task,
            recursion=recursion,
            thinking=message.reasoning_content,
            action_type="CALL_TOOL",
            action_output=action_output,
            message=call_tool_message,
            token_counter=token_counter,
        )

        self.state_service.finalize_success(
            task=task,
            recursion=recursion,
            context=context,
            action_type="CALL_TOOL",
            action_output=action_output,
            message=call_tool_message,
            tool_results=tool_results,
            pending_user_action=pending_user_action,
        )

        assistant_content = message.content or ""

        event_data: dict[str, Any] = {
            "trace_id": trace_id,
            "action_type": "CALL_TOOL",
            "llm_response_id": response.id,
            "message": call_tool_message,
            "thinking": message.reasoning_content,
            "session_title": "",
            "output": action_output,
            "answer_attachments": [],
            "assistant_message": assistant_content,
            "tool_calls": reconstructed_tool_calls,
            "tool_results": tool_results,
            "pending_user_action": pending_user_action,
        }
        if tokens_data is not None:
            event_data["tokens"] = tokens_data
        return recursion, event_data

    # ------------------------------------------------------------------
    # Text action path (CLARIFY / ANSWER)
    # ------------------------------------------------------------------

    def _execute_text_action_recursion(
        self,
        *,
        task: ReactTask,
        recursion: ReactRecursion,
        context: ReactContext,
        trace_id: str,
        message: ChatMessage,
        decision: ParsedReactDecision,
        token_counter: dict[str, int],
        response: Response,
    ) -> tuple[ReactRecursion, dict[str, Any]]:
        """Handle a text-only action (CLARIFY / ANSWER)."""
        thinking = message.reasoning_content
        message_text = decision.message
        action = decision.action
        action_type = action.action_type
        action_output = dict(action.output)
        answer_attachments: list[dict[str, Any]] = []

        if action_type == "ANSWER":
            action_output, answer_attachments = self._persist_answer_attachments(
                task=task,
                action_output=action_output,
            )

        session_title = ""
        if action_type == "ANSWER":
            session_title = action_output.get("session_title") or ""

        tokens_data = self.state_service.record_llm_decision(
            task=task,
            recursion=recursion,
            thinking=thinking,
            action_type=action_type,
            action_output=action_output,
            message=message_text,
            token_counter=token_counter,
        )

        self.state_service.finalize_success(
            task=task,
            recursion=recursion,
            context=context,
            action_type=action_type,
            action_output=action_output,
            message=message_text,
            tool_results=[],
            pending_user_action=None,
        )
        persisted_session_title = self._persist_session_title(task, session_title)

        event_data: dict[str, Any] = {
            "trace_id": trace_id,
            "action_type": action_type,
            "llm_response_id": response.id,
            "message": message_text,
            "thinking": thinking,
            "session_title": persisted_session_title,
            "output": action_output,
            "answer_attachments": answer_attachments,
            "assistant_message": message.content or "{}",
            "tool_calls": [],
            "tool_results": [],
            "pending_user_action": None,
        }
        if tokens_data is not None:
            event_data["tokens"] = tokens_data
        return recursion, event_data

    async def run_task(
        self,
        task: ReactTask,
        max_context_tokens: int = 0,
        compact_threshold_percent: int = 0,
        emit_event: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        skills_metadata_json: str = "[]",
        mandatory_skills_json: str = "[]",
        workspace_guidance: str = "",
        task_bootstrap_prefix_blocks: list[str] | None = None,
        task_bootstrap_suffix_blocks: list[str] | None = None,
        turn_user_message: str | None = None,
        turn_files: list[FileAssetListItem] | None = None,
        turn_attachments: list[dict[str, Any]] | None = None,
        delegation_agents: str = "",
        channel_context: str = "",
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Execute complete ReAct task with streaming events.

        Args:
            task: The ReactTask to execute.
            max_context_tokens: Effective LLM context window for this task's
                resolved runtime configuration.
            compact_threshold_percent: Effective auto-compact threshold for this
                task's resolved runtime configuration.
            emit_event: Optional event publisher used for long-running internal
                phases that need to reach clients before this generator resumes.
            skills_metadata_json: Visible skill metadata JSON injected in the
                once-per-task bootstrap user prompt.
            mandatory_skills_json: Full mandatory skill payload JSON injected
                into the task bootstrap prompt when the user explicitly selects
                one or more skills for the current send.
            workspace_guidance: Full markdown workspace guidance injected into
                the task bootstrap prompt for the active runtime workspace.
            task_bootstrap_prefix_blocks: Extra prompt blocks injected before the
                standard task bootstrap body.
            task_bootstrap_suffix_blocks: Extra prompt blocks injected after the
                standard task bootstrap body.
            turn_user_message: User input of the current turn (used for chat history).
            turn_files: Uploaded file summaries for chat history and prompting.
            turn_attachments: Attachment path hints for the first iteration payload.
            delegation_agents: Markdown section listing delegatable agents.
            channel_context: Markdown section for channel environment awareness.

        Yields:
            Stream events for each recursion cycle

        Raises:
            asyncio.CancelledError: If the task is cancelled by client disconnect
        """
        max_context_tokens = max(int(max_context_tokens or 0), 0)
        compact_threshold_percent = max(int(compact_threshold_percent or 0), 0)
        system_prompt = build_runtime_system_prompt(
            skills=skills_metadata_json,
            delegation_agents=delegation_agents,
            channel_context=channel_context,
        )
        self._delegation_agents = delegation_agents

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

        # Resolve system timezone from DB settings for prompt rendering.
        from app.services.system_settings_service import SystemSettingsService

        _system_tz = SystemSettingsService(self.db).get_time_zone()

        runtime_state = self.runtime_service.initialize(
            task,
            system_prompt,
        )
        logged_message_count = len(runtime_state.messages)
        pending_turn_attachments = turn_attachments
        pending_tool_results: list[dict[str, Any]] | None = None

        if task.iteration == 0:
            task_bootstrap_message = build_runtime_task_bootstrap_message(
                build_runtime_user_prompt(
                    mandatory_skills=mandatory_skills_json,
                    workspace_guidance=workspace_guidance,
                    prefix_blocks=task_bootstrap_prefix_blocks,
                    suffix_blocks=task_bootstrap_suffix_blocks,
                    timezone_name=_system_tz,
                )
            )
            runtime_state, compact_events = await self._maybe_compact_runtime_window(
                task=task,
                runtime_state=runtime_state,
                system_prompt=system_prompt,
                max_context_tokens=max_context_tokens,
                threshold_percent=compact_threshold_percent,
                reason="task_start_threshold",
                preview_messages=[task_bootstrap_message],
                emit_event=emit_event,
            )
            for compact_event in compact_events:
                yield compact_event
            logged_message_count = len(runtime_state.messages)
            runtime_state = self.runtime_service.append_task_bootstrap_prompt(
                task,
                str(task_bootstrap_message["content"]),
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
        elif mandatory_skills_json != "[]" and turn_user_message is not None:
            runtime_state = self.runtime_service.append_task_bootstrap_prompt(
                task,
                build_runtime_user_prompt(
                    mandatory_skills=mandatory_skills_json,
                    workspace_guidance=workspace_guidance,
                    timezone_name=_system_tz,
                ),
            )
            self._log_messages_pretty(
                messages=runtime_state.messages,
                task_id=task.task_id,
                iteration=task.iteration + 1,
                trace_id="task-bootstrap-resume",
                phase="send",
                start_index=logged_message_count,
                iteration_message_start=0,
            )
            logged_message_count = len(runtime_state.messages)

        try:
            self._current_task_delegation_depth = task.delegation_depth
            self._current_task_id = task.task_id
            self._plan_pending_review = False
            self._prev_steps_json = ""
            self._steps_unchanged_count = 0
            while task.iteration < task.max_iteration:
                runtime_state = self.runtime_service.load(task)
                context = self.state_service.load_context(task)

                # Dequeue mid-task user input if available.
                user_intent_override: str | None = None
                if task.session_id and task.iteration > 0:
                    from app.services.session_task_queue_service import (
                        SessionTaskQueueService,
                    )

                    queue_svc = SessionTaskQueueService(self.db)
                    queue_item = queue_svc.dequeue_next(task.session_id)
                    if queue_item is not None and queue_item.source == "user_input":
                        user_intent_override = queue_item.prompt
                        queue_svc.mark_completed(queue_item)
                        yield {
                            "type": "user_input",
                            "task_id": task.task_id,
                            "iteration": task.iteration,
                            "data": {"message": user_intent_override},
                            "timestamp": datetime.now(UTC).isoformat(),
                        }

                preview_payload = build_recursion_user_payload(
                    task,
                    context,
                    runtime_state.pending_action_result,
                    attachments=pending_turn_attachments,
                    after_compaction=runtime_state.compact_result is not None,
                    user_intent_override=user_intent_override,
                    workspace_path=self.tool_execution_context.workspace_backend_path
                    if self.tool_execution_context
                    else None,
                    previous_steps_json=self._prev_steps_json or None,
                    system_feedback=(
                        "Steps have not been updated for 8 consecutive iterations"
                        if self._steps_unchanged_count >= 8
                        else None
                    ),
                )
                preview_content_blocks = (
                    list(self._pending_multimodal_blocks)
                    if self._pending_multimodal_blocks
                    else None
                )
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
                    preview_messages=[
                        build_runtime_payload_message(
                            preview_payload,
                            attachments=preview_content_blocks,
                        )
                    ],
                    emit_event=emit_event,
                )
                for compact_event in compact_events:
                    yield compact_event
                if compact_events:
                    logged_message_count = len(runtime_state.messages)
                    preview_payload = build_recursion_user_payload(
                        task,
                        context,
                        runtime_state.pending_action_result,
                        attachments=pending_turn_attachments,
                        after_compaction=runtime_state.compact_result is not None,
                        user_intent_override=user_intent_override,
                        workspace_path=self.tool_execution_context.workspace_backend_path
                        if self.tool_execution_context
                        else None,
                        previous_steps_json=self._prev_steps_json or None,
                        system_feedback=(
                            "Steps have not been updated for 8 consecutive iterations"
                            if self._steps_unchanged_count >= 8
                            else None
                        ),
                    )

                trace_id = str(uuid.uuid4())

                # Check if task was cancelled
                if self.cancelled or task.status == "cancelled":
                    logger.info(f"Task {task.task_id} cancelled, exiting loop")
                    self.state_service.mark_cancelled(task)
                    self.runtime_service.clear_task_state(task)
                    break

                # Yield recursion start event
                yield {
                    "type": "recursion_start",
                    "task_id": task.task_id,
                    "trace_id": trace_id,
                    "iteration": task.iteration,
                    "timestamp": datetime.now(UTC).isoformat(),
                }

                # Append iteration payload as a new user message.
                user_payload = preview_payload
                # Inject pending multimodal blocks from prior tool results
                multimodal_attachments: list[dict[str, Any]] | None = None
                if self._pending_multimodal_blocks:
                    multimodal_attachments = list(self._pending_multimodal_blocks)
                    self._pending_multimodal_blocks.clear()
                runtime_state = self.runtime_service.append_user_payload(
                    task,
                    user_payload,
                    attachments=multimodal_attachments,
                    tool_results=self._compact_tool_results(pending_tool_results),
                )
                input_message = dict(runtime_state.messages[-1])
                pending_turn_attachments = None
                pending_tool_results = None
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
                used_incremental_request_messages = False
                llm_chat_kwargs: dict[str, Any] = {
                    **self._build_iteration_llm_runtime_kwargs(task),
                    "_pivot_task_id": task.task_id,
                }
                if (
                    self._uses_incremental_request_messages()
                    and runtime_state.previous_response_id
                ):
                    used_incremental_request_messages = True
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
                        input_message=input_message,
                        messages=messages_for_llm,
                        llm_chat_kwargs=llm_chat_kwargs,
                        token_meter_queue=token_meter_queue,
                    )
                )

                cancelled_during_recursion = False
                last_meter_emit_at = perf_counter()
                last_estimated_completion_tokens = 0
                streamed_action = False
                streamed_resolved_tool_call = False
                streamed_tool_results = False
                while True:
                    if self.cancelled or task.status == "cancelled":
                        recursion_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await recursion_task
                        self.state_service.mark_cancelled(task)
                        self.runtime_service.clear_task_state(task)
                        cancelled_during_recursion = True
                        break

                    # Drain delegation events emitted by sub-agent execution.
                    for _ in range(self._delegation_event_queue.qsize()):
                        try:
                            _del_event = self._delegation_event_queue.get_nowait()
                            yield {
                                "type": _del_event["type"],
                                "task_id": task.task_id,
                                "trace_id": trace_id,
                                "iteration": task.iteration,
                                "data": _del_event.get("data", {}),
                                "timestamp": datetime.now(UTC).isoformat(),
                            }
                        except asyncio.QueueEmpty:
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

                    if meter_type == "action":
                        action_type_data = meter_data.get("action_type")
                        if (
                            isinstance(action_type_data, str)
                            and action_type_data
                            and not streamed_action
                        ):
                            streamed_action = True
                            yield {
                                "type": "action",
                                "task_id": task.task_id,
                                "trace_id": trace_id,
                                "iteration": task.iteration,
                                "delta": action_type_data,
                                "timestamp": datetime.now(UTC).isoformat(),
                            }
                        continue

                    if meter_type == "tool_call":
                        tool_calls_data = meter_data.get("tool_calls")
                        tool_results_data = meter_data.get("tool_results", [])
                        if isinstance(tool_calls_data, list):
                            streamed_resolved_tool_call = True
                            yield {
                                "type": "tool_call",
                                "task_id": task.task_id,
                                "trace_id": trace_id,
                                "iteration": task.iteration,
                                "data": {
                                    "tool_calls": tool_calls_data,
                                    "tool_results": (
                                        tool_results_data
                                        if isinstance(tool_results_data, list)
                                        else []
                                    ),
                                },
                                "timestamp": datetime.now(UTC).isoformat(),
                            }
                        continue

                    if meter_type == "tool_result":
                        tool_results_data = meter_data.get("tool_results")
                        if isinstance(tool_results_data, list):
                            streamed_tool_results = True
                            yield {
                                "type": "tool_result",
                                "task_id": task.task_id,
                                "trace_id": trace_id,
                                "iteration": task.iteration,
                                "data": {
                                    "tool_results": tool_results_data,
                                },
                                "timestamp": datetime.now(UTC).isoformat(),
                            }
                        continue

                    if meter_type == "tool_payload_delta":
                        yield {
                            "type": "tool_payload_delta",
                            "task_id": task.task_id,
                            "trace_id": trace_id,
                            "iteration": task.iteration,
                            "data": {
                                "tool_call_id": meter_data.get("tool_call_id", ""),
                                "tool_name": meter_data.get("tool_name", ""),
                                "argument_name": meter_data.get("argument_name", ""),
                                "payload_name": meter_data.get("payload_name", ""),
                                "delta": meter_data.get("delta", ""),
                                "is_final": meter_data.get("is_final", False),
                            },
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

                # Final drain: delegation events arriving just before the
                # recursion task completes may not have been yielded in the
                # loop above.
                while not self._delegation_event_queue.empty():
                    try:
                        _del_event = self._delegation_event_queue.get_nowait()
                        yield {
                            "type": _del_event["type"],
                            "task_id": task.task_id,
                            "trace_id": trace_id,
                            "iteration": task.iteration,
                            "data": _del_event.get("data", {}),
                            "timestamp": datetime.now(UTC).isoformat(),
                        }
                    except asyncio.QueueEmpty:
                        break

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
                    token_usage = event_data.get("tokens")
                    if not used_incremental_request_messages and isinstance(
                        token_usage, dict
                    ):
                        prompt_tokens = token_usage.get("prompt_tokens")
                        if isinstance(prompt_tokens, int) and prompt_tokens > 0:
                            runtime_state = (
                                self.runtime_service.set_exact_prompt_usage_baseline(
                                    task,
                                    prompt_tokens=prompt_tokens,
                                    message_count=len(runtime_state.messages),
                                )
                            )
                    assistant_message = event_data.get("assistant_message")
                    event_tool_calls = event_data.get("tool_calls")
                    has_tool_calls = (
                        isinstance(event_tool_calls, list) and event_tool_calls
                    )
                    if isinstance(assistant_message, str) and (
                        assistant_message or has_tool_calls
                    ):
                        runtime_state = self.runtime_service.append_assistant_message(
                            task,
                            assistant_message or "",
                            tool_calls=event_tool_calls if has_tool_calls else None,
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

                # Track tool results for next iteration's user message.
                if action_type == "CALL_TOOL":
                    raw_tool_results = event_data.get("tool_results")
                    pending_tool_results = (
                        raw_tool_results if isinstance(raw_tool_results, list) else None
                    )

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

                if recursion.message:
                    yield {
                        "type": "message",
                        "task_id": task.task_id,
                        "trace_id": event_data.get("trace_id"),
                        "iteration": task.iteration,
                        "delta": recursion.message,
                        "timestamp": datetime.now(UTC).isoformat(),
                        "created_at": recursion.created_at.isoformat(),
                        "updated_at": recursion.updated_at.isoformat(),
                        "tokens": event_data.get("tokens"),
                        "data": {
                            "session_title": event_data.get("session_title", ""),
                        },
                    }

                # Yield action event with type and token info. CALL_TOOL actions
                # may already have been emitted before live tool lifecycle events.
                if not streamed_action:
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

                    if not streamed_resolved_tool_call:
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
                    if not streamed_tool_results:
                        yield {
                            "type": "tool_result",
                            "task_id": task.task_id,
                            "trace_id": event_data.get("trace_id"),
                            "iteration": task.iteration,
                            "data": {
                                "tool_results": tool_results_data,
                            },
                            "timestamp": datetime.now(UTC).isoformat(),
                        }
                    parse_recovery_error = event_data.get("error")
                    if isinstance(parse_recovery_error, str) and parse_recovery_error:
                        yield {
                            "type": "error",
                            "task_id": task.task_id,
                            "trace_id": event_data.get("trace_id"),
                            "iteration": task.iteration,
                            "data": {
                                "error": parse_recovery_error,
                                "terminal": False,
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
                        # Build the payload dict for the pivot_action field.
                        payload = pending_user_action.get("payload")
                        if not isinstance(payload, dict):
                            # Legacy shape: construct payload from the top-level keys.
                            payload = {
                                k: v
                                for k, v in pending_user_action.items()
                                if k not in ("type", "category", "kind")
                            }
                        yield {
                            "type": "clarify",
                            "task_id": task.task_id,
                            "trace_id": event_data.get("trace_id"),
                            "iteration": task.iteration,
                            "data": {
                                "question": (
                                    question
                                    if isinstance(question, str)
                                    else "Approve this action?"
                                ),
                                "approval_request": approval_request
                                if isinstance(approval_request, dict)
                                else None,
                                "pivot_action": {
                                    "type": pending_user_action.get("type")
                                    or pending_user_action.get("kind", ""),
                                    "category": pending_user_action.get(
                                        "category",
                                        "approval",
                                    ),
                                    "payload": payload,
                                },
                            },
                            "timestamp": datetime.now(UTC).isoformat(),
                        }

                        self.state_service.advance_iteration(task)
                        break

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
                        "data": {
                            "error": error_msg,
                            "terminal": non_retryable_error,
                        },
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

                # Plan review: pause the loop for user approval of a new plan.
                if self._plan_pending_review:
                    self._plan_pending_review = False
                    from .plan_files import read_plan_text

                    workspace_path = (
                        self.tool_execution_context.workspace_backend_path
                        if self.tool_execution_context
                        else ""
                    )
                    plan_text = (
                        read_plan_text(workspace_path, task.task_id)
                        if workspace_path
                        else None
                    )

                    yield {
                        "type": "plan_review",
                        "task_id": task.task_id,
                        "trace_id": event_data.get("trace_id"),
                        "iteration": task.iteration,
                        "data": {
                            "plan_text": plan_text,
                        },
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                    self.state_service.advance_iteration(task)
                    # Store marker so supervisor can identify plan_review pause.
                    task.pending_user_action_json = json.dumps({"type": "plan_review"})
                    self.state_service._set_task_status(task, "waiting_input")
                    break

                # Update iteration count
                self.state_service.advance_iteration(task)

                # Track steps-unchanged streak for stale-step warning.
                if self.tool_execution_context and self._current_task_id:
                    _ws = self.tool_execution_context.workspace_backend_path
                    from .plan_files import plan_exists as _pe, read_steps as _rs

                    if _pe(_ws, self._current_task_id):
                        import json as _json

                        _cur = _json.dumps(
                            _rs(_ws, self._current_task_id), sort_keys=True
                        )
                        if _cur == self._prev_steps_json:
                            self._steps_unchanged_count += 1
                        else:
                            self._steps_unchanged_count = 0
                            self._prev_steps_json = _cur

            # Clean up stale user_input queue items now that the task is terminal.
            if task.session_id:
                from app.services.session_task_queue_service import (
                    SessionTaskQueueService,
                )

                _queue_svc = SessionTaskQueueService(self.db)
                for _stale in _queue_svc.get_pending_for_session(task.session_id):
                    if _stale.source == "user_input":
                        _queue_svc.mark_failed(
                            _stale, "Task completed before user_input was consumed"
                        )
                        yield {
                            "type": "user_input_discarded",
                            "task_id": task.task_id,
                            "iteration": task.iteration,
                            "data": {"message": _stale.prompt},
                            "timestamp": datetime.now(UTC).isoformat(),
                        }

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
                    "data": {
                        "error": "Maximum iteration reached",
                        "terminal": True,
                    },
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

            # Clean up stale user_input queue items on unexpected failure.
            if task.session_id:
                from app.services.session_task_queue_service import (
                    SessionTaskQueueService,
                )

                _queue_svc = SessionTaskQueueService(self.db)
                for _stale in _queue_svc.get_pending_for_session(task.session_id):
                    if _stale.source == "user_input":
                        _queue_svc.mark_failed(
                            _stale, "Task failed before user_input was consumed"
                        )

            yield {
                "type": "error",
                "task_id": task.task_id,
                "iteration": task.iteration,
                "data": {"error": error_message, "terminal": True},
                "timestamp": datetime.now(UTC).isoformat(),
            }
