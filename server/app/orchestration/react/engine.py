"""ReAct Engine - Core execution engine for ReAct state machine.

This module implements the main execution loop for the ReAct agent,
handling recursion cycles, tool calling, and state management.
"""

import asyncio
import json
import logging
import re
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from time import perf_counter
from typing import TYPE_CHECKING, Any

from app.llm.abstract_llm import AbstractLLM, ChatMessage, Choice, Response, UsageInfo
from app.llm.token_estimator import estimate_messages_tokens, estimate_text_tokens
from app.models.react import (
    ReactRecursion,
    ReactTask,
)
from app.orchestration.tool.manager import ToolExecutionContext, ToolManager
from app.schemas.file import FileAssetListItem
from app.services.react_runtime_service import ReactRuntimeService
from app.services.react_state_service import ReactStateService
from app.services.session_memory_service import SessionMemoryService
from fastapi.concurrency import run_in_threadpool
from sqlmodel import Session

from .context import ReactContext
from .parser import PARSE_RETRY_INSTRUCTION, PARSE_RETRY_LIMIT, parse_react_output
from .prompt_template import build_runtime_system_prompt

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
        """Accumulate usage fields into ``token_counter``.

        Args:
            token_counter: Mutable token tally shared by one recursion.
            usage: Usage object returned by LLM response (may be None).
        """
        if usage is None:
            return

        token_counter["prompt_tokens"] += int(getattr(usage, "prompt_tokens", 0) or 0)
        token_counter["completion_tokens"] += int(
            getattr(usage, "completion_tokens", 0) or 0
        )
        token_counter["total_tokens"] += int(getattr(usage, "total_tokens", 0) or 0)
        token_counter["cached_input_tokens"] += int(
            getattr(usage, "cached_input_tokens", 0) or 0
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
        attempt_start_prompt = token_counter["prompt_tokens"]
        attempt_start_completion = token_counter["completion_tokens"]
        attempt_start_total = token_counter["total_tokens"]

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

            self._accumulate_usage(token_counter, stream_chunk.usage)

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

        # Usage fallback: estimate prompt/completion when provider does not return usage.
        attempt_prompt_delta = token_counter["prompt_tokens"] - attempt_start_prompt
        attempt_completion_delta = (
            token_counter["completion_tokens"] - attempt_start_completion
        )
        attempt_total_delta = token_counter["total_tokens"] - attempt_start_total

        if (
            attempt_prompt_delta == 0
            and attempt_completion_delta == 0
            and attempt_total_delta == 0
        ):
            estimated_prompt_tokens = estimate_messages_tokens(messages)
            token_counter["prompt_tokens"] += estimated_prompt_tokens
            token_counter["completion_tokens"] += estimated_completion_tokens
            token_counter["total_tokens"] += (
                estimated_prompt_tokens + estimated_completion_tokens
            )
        elif attempt_total_delta <= 0 and (
            attempt_prompt_delta > 0 or attempt_completion_delta > 0
        ):
            token_counter["total_tokens"] += (
                attempt_prompt_delta + attempt_completion_delta
            )

        self._ensure_total_tokens(token_counter)

        full_content = "".join(content_parts)
        full_reasoning = "".join(reasoning_parts) or None
        usage_info = (
            UsageInfo(
                prompt_tokens=token_counter["prompt_tokens"],
                completion_tokens=token_counter["completion_tokens"],
                total_tokens=token_counter["total_tokens"],
                cached_input_tokens=token_counter["cached_input_tokens"],
            )
            if token_counter["total_tokens"] > 0
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

        logger.info("\n%s", "\n".join(rendered_lines))

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
        for step in context.context.get("plan", []):
            if not isinstance(step, dict):
                continue
            step_id = step.get("step_id")
            if not isinstance(step_id, str):
                continue
            current_plan.append(
                {
                    "step_id": step_id,
                    "general_goal": step.get("general_goal", ""),
                    "specific_description": step.get("specific_description", ""),
                    "completion_criteria": step.get("completion_criteria", ""),
                    "status": step.get("status", "pending"),
                }
            )
        return current_plan

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
        # Tools are described in the system prompt, and LLM returns tool calls
        # in action.output.
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

                # Parse JSON from content to get observe, thought, abstract, action_type
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
            thought = decision.thought
            abstract = decision.abstract
            progress_update = decision.progress_update
            action = decision.action
            action_type = action.action_type
            action_output = dict(action.output)

            # Extract the plan step this recursion belongs to.
            # The LLM returns action.step_id when executing as part of a plan.
            # We must validate its presence when a plan exists, but never abort — a
            # missing step_id should only surface as a warning so the task can continue.
            action_step_id = action.step_id

            # Extract session memory related fields (only used when action_type == ANSWER)
            session_memory_delta = decision.session_memory_delta
            session_subject = decision.session_subject
            session_goal = decision.session_goal
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
            tokens_data = self.state_service.finalize_success(
                task=task,
                recursion=recursion,
                context=context,
                observe=observe,
                thinking=thinking,
                thought=thought,
                abstract=abstract,
                action_type=action_type,
                action_output=action_output,
                action_step_id=action_step_id,
                step_status_updates=step_status_updates_validated,
                progress_update=progress_update,
                tool_results=tool_results,
                token_counter=token_counter,
            )

            # Prepare event data
            event_data = {
                "trace_id": trace_id,
                "action_type": action_type,
                "llm_response_id": response.id,
                "observe": observe,
                "thinking": thinking,
                "thought": thought,
                "abstract": abstract,
                "progress_update": progress_update,
                "output": action_output,
                "assistant_message": assistant_message_raw,
                "tool_calls": reconstructed_tool_calls,  # Native tool_calls
                "tool_results": tool_results,  # Tool execution results
                # Session memory related fields (for ANSWER action)
                "session_memory_delta": session_memory_delta,
                "session_subject": session_subject,
                "session_goal": session_goal,
                "task_summary": task_summary,
                "step_status_update": step_status_updates_validated,
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
            selected_skills_text: Selected skill markdown block injected in system prompt.
            turn_user_message: User input of the current turn (used for chat history).
            turn_files: Uploaded file summaries for chat history and prompting.
            turn_file_blocks: Neutral multimodal content blocks for this turn.

        Yields:
            Stream events for each recursion cycle

        Raises:
            asyncio.CancelledError: If the task is cancelled by client disconnect
        """
        # Load session memory if session_id is provided
        session_memory_dict: dict[str, Any] | None = None
        if task.session_id:
            session_service = SessionMemoryService(self.db)
            session_memory_dict = session_service.get_full_session_memory_dict(
                task.session_id
            )
            # Update chat history with user input
            session_service.update_chat_history(
                task.session_id,
                "user",
                turn_user_message or task.user_message,
                files=turn_files,
            )

        self.state_service.mark_running(task)

        runtime_state = self.runtime_service.initialize(
            task,
            build_runtime_system_prompt(
                tool_manager=self.tool_manager,
                session_memory=session_memory_dict,
                skills=selected_skills_text,
            ),
        )
        logged_message_count = len(runtime_state.messages)
        pending_turn_file_blocks = turn_file_blocks

        try:
            while task.iteration < task.max_iteration:
                trace_id = str(uuid.uuid4())

                # Check if task was cancelled
                if self.cancelled:
                    logger.info(f"Task {task.task_id} cancelled, exiting loop")
                    self.state_service.mark_cancelled(task)
                    self.runtime_service.clear(task)
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
                llm_chat_kwargs: dict[str, Any] = {"_pivot_task_id": task.task_id}
                if (
                    self._uses_incremental_request_messages()
                    and runtime_state.previous_response_id
                ):
                    llm_chat_kwargs["_pivot_previous_response_id"] = (
                        runtime_state.previous_response_id
                    )
                    messages_for_llm = runtime_state.messages[-1:]

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

                if token_meter_queue is not None:
                    last_meter_emit_at = perf_counter()
                    last_estimated_completion_tokens = 0
                    while not recursion_task.done() or not token_meter_queue.empty():
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
                            float(raw_rate)
                            if isinstance(raw_rate, int | float)
                            else 0.0
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

                recursion, event_data = await recursion_task
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
                next_action_result = self._build_next_pending_action_result(event_data)
                if next_action_result is not None:
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

                # Yield Observe, Thought, Action events with token info
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

                if recursion.thought:
                    yield {
                        "type": "thought",
                        "task_id": task.task_id,
                        "trace_id": event_data.get("trace_id"),
                        "iteration": task.iteration,
                        "delta": recursion.thought,
                        "timestamp": datetime.now(UTC).isoformat(),
                        "created_at": recursion.created_at.isoformat(),
                        "updated_at": recursion.updated_at.isoformat(),
                        "tokens": event_data.get("tokens"),
                    }

                if recursion.abstract:
                    yield {
                        "type": "abstract",
                        "task_id": task.task_id,
                        "trace_id": event_data.get("trace_id"),
                        "iteration": task.iteration,
                        "delta": recursion.abstract,
                        "timestamp": datetime.now(UTC).isoformat(),
                        "created_at": recursion.created_at.isoformat(),
                        "updated_at": recursion.updated_at.isoformat(),
                        "tokens": event_data.get("tokens"),
                    }

                if recursion.progress_update:
                    yield {
                        "type": "progress_update",
                        "task_id": task.task_id,
                        "trace_id": event_data.get("trace_id"),
                        "iteration": task.iteration,
                        "delta": recursion.progress_update,
                        "timestamp": datetime.now(UTC).isoformat(),
                        "created_at": recursion.created_at.isoformat(),
                        "updated_at": recursion.updated_at.isoformat(),
                        "tokens": event_data.get("tokens"),
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

                    # Process session memory updates if session_id is provided
                    if task.session_id:
                        session_service = SessionMemoryService(self.db)
                        answer_output = event_data.get("output", {})

                        session_service.process_answer_updates(
                            session_id=task.session_id,
                            task=task,
                            session_memory_delta=event_data.get(
                                "session_memory_delta", {}
                            ),
                            session_subject=event_data.get("session_subject", {}),
                            session_goal=event_data.get("session_goal", {}),
                            agent_answer=answer_output.get("answer", ""),
                            task_summary=event_data.get("task_summary", {}),
                        )

                    # Task complete
                    self.state_service.mark_completed(task)
                    self.runtime_service.clear(task)

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
                        self.runtime_service.clear(task)
                        break

                    # For malformed JSON we roll back this recursion from the LLM
                    # conversation and retry without consuming iteration budget.
                    if not rollback_messages:
                        self.state_service.advance_iteration(task)
                    continue

                # Update iteration count
                self.state_service.advance_iteration(task)

            # Max iteration reached
            if task.iteration >= task.max_iteration and task.status == "running":
                self.state_service.mark_failed(task)
                self.runtime_service.clear(task)

                yield {
                    "type": "error",
                    "task_id": task.task_id,
                    "iteration": task.iteration,
                    "data": {"error": "Maximum iteration reached"},
                    "timestamp": datetime.now(UTC).isoformat(),
                }

        except Exception as e:
            logger.exception(
                "run_task failed unexpectedly task_id=%s iteration=%s",
                task.task_id,
                task.iteration,
            )
            self.state_service.mark_failed(task)
            self.runtime_service.clear(task)
            error_message = str(e) or repr(e)

            yield {
                "type": "error",
                "task_id": task.task_id,
                "iteration": task.iteration,
                "data": {"error": error_message},
                "timestamp": datetime.now(UTC).isoformat(),
            }
