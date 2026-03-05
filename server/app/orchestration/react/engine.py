"""ReAct Engine - Core execution engine for ReAct state machine.

This module implements the main execution loop for the ReAct agent,
handling recursion cycles, tool calling, and state management.
"""

import json
import logging
import re
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

from app.llm.abstract_llm import AbstractLLM
from app.models.react import (
    ReactPlanStep,
    ReactRecursion,
    ReactRecursionState,
    ReactTask,
)
from app.orchestration.tool.manager import ToolExecutionContext, ToolManager
from app.services.session_memory_service import SessionMemoryService
from fastapi.concurrency import run_in_threadpool
from sqlmodel import Session, select

from .context import ReactContext
from .prompt_template import build_runtime_system_prompt

# Get logger for this module
logger = logging.getLogger(__name__)

ALLOWED_ACTION_TYPES = {"CALL_TOOL", "RE_PLAN", "REFLECT", "CLARIFY", "ANSWER"}
PAYLOAD_SENTINEL_SUFFIX = "6F2D9C1A"
PAYLOAD_NAME_PATTERN = r"[A-Za-z_][A-Za-z0-9_]{0,63}"
PAYLOAD_BEGIN_RE = re.compile(
    rf"(?m)^<<<PIVOT_PAYLOAD:({PAYLOAD_NAME_PATTERN}):BEGIN_{PAYLOAD_SENTINEL_SUFFIX}>>>$"
)
PAYLOAD_REF_KEY = "$payload_ref"
PARSE_RETRY_LIMIT = 1
PARSE_RETRY_INSTRUCTION = (
    "Your previous response could not be parsed.\n"
    "Output the same decision again using the required format only.\n"
    "Rules:\n"
    "1) The first block must be a valid JSON object.\n"
    '2) For CALL_TOOL, every argument value must be {"$payload_ref":"<name>"}.\n'
    "3) Append payload blocks after the JSON when action_type is CALL_TOOL.\n"
    "4) Do not include markdown fences or any extra commentary."
)


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
        self.cancelled = False  # Flag to signal cancellation

    def _safe_load_json(self, json_str: str) -> dict[str, Any]:
        """
        Parse JSON string from LLM response.

        The only allowed fix is stripping markdown code block markers
        (```json ... ```) that some LLMs add despite instructions not to.
        All other invalid JSON will raise an error for easier debugging.

        Args:
            json_str: JSON string from LLM

        Returns:
            Parsed dictionary

        Raises:
            ValueError: If JSON cannot be parsed
        """
        # Strip leading/trailing whitespace
        json_str = json_str.strip()

        # Strip markdown code block markers if present
        # Simple approach: check start/end and strip
        if json_str.startswith("```json"):
            json_str = json_str[7:]  # Remove ```json
        elif json_str.startswith("```"):
            json_str = json_str[3:]  # Remove ```

        if json_str.endswith("```"):
            json_str = json_str[:-3]  # Remove trailing ```

        # Strip again after removing markers
        json_str = json_str.strip()

        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Failed to parse JSON {e.msg} at position {e.pos}: {json_str}"
            ) from e

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

    def _persist_accumulated_usage(
        self, task: ReactTask, recursion: ReactRecursion, token_counter: dict[str, int]
    ) -> dict[str, int] | None:
        """Persist accumulated token usage to recursion/task rows.

        Args:
            task: Task receiving aggregate token increments.
            recursion: Recursion row receiving per-recursion totals.
            token_counter: Aggregated usage across parse attempts.

        Returns:
            Persisted token payload for event output, or None if empty.
        """
        if token_counter["total_tokens"] <= 0:
            return None

        recursion.prompt_tokens = token_counter["prompt_tokens"]
        recursion.completion_tokens = token_counter["completion_tokens"]
        recursion.total_tokens = token_counter["total_tokens"]
        recursion.cached_input_tokens = token_counter["cached_input_tokens"]

        task.total_prompt_tokens += token_counter["prompt_tokens"]
        task.total_completion_tokens += token_counter["completion_tokens"]
        task.total_tokens += token_counter["total_tokens"]
        task.total_cached_input_tokens += token_counter["cached_input_tokens"]
        return dict(token_counter)

    def _split_json_and_payload_sections(self, content: str) -> tuple[str, str | None]:
        """Split model output into JSON section and optional payload section.

        Args:
            content: Raw LLM assistant content.

        Returns:
            A tuple of (json_section, payload_section_or_none).

        Raises:
            ValueError: If payload markers appear without a JSON section.
        """
        normalized = content.strip()
        begin_match = PAYLOAD_BEGIN_RE.search(normalized)
        if begin_match is None:
            return normalized, None

        json_section = normalized[: begin_match.start()].strip()
        if not json_section:
            raise ValueError("Missing JSON section before payload blocks.")
        payload_section = normalized[begin_match.start() :]
        return json_section, payload_section

    def _parse_payload_blocks(self, payload_section: str) -> dict[str, str]:
        """Parse payload blocks declared after the main JSON section.

        Args:
            payload_section: Raw text starting from first payload begin marker.

        Returns:
            Mapping from payload name to raw payload content.

        Raises:
            ValueError: If payload markers are malformed, duplicated, or truncated.
        """
        payloads: dict[str, str] = {}
        text = payload_section.strip()
        cursor = 0

        while cursor < len(text):
            while cursor < len(text) and text[cursor].isspace():
                cursor += 1
            if cursor >= len(text):
                break

            begin_match = PAYLOAD_BEGIN_RE.match(text, cursor)
            if begin_match is None:
                snippet = text[cursor : cursor + 120]
                raise ValueError(f"Invalid payload block marker near: {snippet}")

            payload_name = begin_match.group(1)
            if payload_name in payloads:
                raise ValueError(f"Duplicate payload name: {payload_name}")

            content_start = begin_match.end()
            if content_start < len(text) and text[content_start] == "\n":
                content_start += 1

            end_re = re.compile(
                rf"(?m)^<<<PIVOT_PAYLOAD:{re.escape(payload_name)}:END_{PAYLOAD_SENTINEL_SUFFIX}>>>$"
            )
            end_match = end_re.search(text, content_start)
            if end_match is None:
                raise ValueError(f"Missing END marker for payload: {payload_name}")

            payloads[payload_name] = text[content_start : end_match.start()]
            cursor = end_match.end()

        return payloads

    def _extract_payload_ref_name(self, value: Any, path: str) -> str:
        """Extract payload reference name from one argument value.

        Args:
            value: Argument value under ``tool_call.arguments.<arg_name>``.
            path: Human-readable path used in error messages.

        Returns:
            Referenced payload name.

        Raises:
            ValueError: If value is not a valid payload reference object.
        """
        if not isinstance(value, dict):
            raise ValueError(
                f"Invalid argument at {path}: every CALL_TOOL argument must be a "
                f"payload reference object with {PAYLOAD_REF_KEY}."
            )
        if len(value) != 1 or PAYLOAD_REF_KEY not in value:
            raise ValueError(
                f"Invalid payload reference object at {path}: "
                f"{PAYLOAD_REF_KEY} must be the only key."
            )

        raw_ref_name = value.get(PAYLOAD_REF_KEY)
        if not isinstance(raw_ref_name, str):
            raise ValueError(
                f"Invalid payload reference at {path}: "
                f"{PAYLOAD_REF_KEY} must be a string."
            )
        if not re.fullmatch(PAYLOAD_NAME_PATTERN, raw_ref_name):
            raise ValueError(f"Invalid payload name '{raw_ref_name}' at {path}.")
        return raw_ref_name

    def _decode_payload_value(self, payload_text: str) -> Any:
        """Decode payload text into tool argument value.

        Behavior:
        - If payload is valid JSON literal/object/array, return parsed JSON value.
        - Otherwise return payload as raw string.

        Args:
            payload_text: Raw payload content between BEGIN/END markers.

        Returns:
            Decoded argument value.
        """
        candidate = payload_text.strip()
        if not candidate:
            return payload_text
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return payload_text

    def _resolve_tool_payload_references(
        self, react_output: dict[str, Any], payloads: dict[str, str]
    ) -> dict[str, Any]:
        """Resolve CALL_TOOL payload references and validate payload integrity.

        Validation rules:
        - payload names are unique (enforced while parsing blocks)
        - every CALL_TOOL argument value must be a ``$payload_ref`` object
        - every ``$payload_ref`` points to an existing payload
        - every payload block is used at least once

        Args:
            react_output: Parsed top-level recursion JSON.
            payloads: Parsed payload block mapping.

        Returns:
            ``react_output`` with resolved tool arguments.

        Raises:
            ValueError: If payload section is inconsistent with JSON references.
        """
        action = react_output.get("action", {})
        action_type = ""
        action_output: Any = {}
        if isinstance(action, dict):
            raw_action_type = action.get("action_type", "")
            if isinstance(raw_action_type, str):
                action_type = raw_action_type.strip()
            action_output = action.get("output", {})

        if payloads and action_type != "CALL_TOOL":
            raise ValueError(
                "Payload blocks are only allowed when action_type=CALL_TOOL."
            )

        if action_type != "CALL_TOOL":
            return react_output

        if not payloads:
            raise ValueError(
                "CALL_TOOL requires payload blocks after the JSON section."
            )
        if not isinstance(action_output, dict):
            raise ValueError("CALL_TOOL action.output must be an object.")

        used_payloads: set[str] = set()
        tool_calls = action_output.get("tool_calls", [])
        if not isinstance(tool_calls, list):
            raise ValueError("CALL_TOOL action.output.tool_calls must be a list.")

        for index, tool_call in enumerate(tool_calls):
            if not isinstance(tool_call, dict):
                raise ValueError(
                    f"CALL_TOOL action.output.tool_calls[{index}] must be an object."
                )
            raw_arguments = tool_call.get("arguments", {})
            if not isinstance(raw_arguments, dict):
                raise ValueError(
                    f"CALL_TOOL action.output.tool_calls[{index}].arguments must be an object."
                )

            resolved_arguments: dict[str, Any] = {}
            for arg_name, raw_arg_value in raw_arguments.items():
                ref_name = self._extract_payload_ref_name(
                    raw_arg_value,
                    path=f"action.output.tool_calls[{index}].arguments.{arg_name}",
                )
                if ref_name not in payloads:
                    raise ValueError(
                        f"Payload reference '{ref_name}' in tool_calls[{index}]."
                        f"arguments.{arg_name} is not defined."
                    )
                used_payloads.add(ref_name)
                resolved_arguments[arg_name] = self._decode_payload_value(
                    payloads[ref_name]
                )
            tool_call["arguments"] = resolved_arguments

        unused_payloads = sorted(set(payloads) - used_payloads)
        if unused_payloads:
            raise ValueError(
                "Unused payload blocks detected: " + ", ".join(unused_payloads)
            )

        return react_output

    def _safe_load_react_output(self, content: str) -> dict[str, Any]:
        """Parse assistant output with strict JSON + optional payload blocks.

        Args:
            content: Raw assistant response.

        Returns:
            Parsed recursion output dictionary with resolved payload references.

        Raises:
            ValueError: If JSON parsing or payload validation fails.
        """
        json_section, payload_section = self._split_json_and_payload_sections(content)
        react_output = self._safe_load_json(json_section)
        payloads = (
            self._parse_payload_blocks(payload_section)
            if payload_section is not None
            else {}
        )
        return self._resolve_tool_payload_references(react_output, payloads)

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

    def _normalize_assistant_message_json(self, content: str) -> str | None:
        """Normalize assistant content to strict JSON string for persistence.

        Args:
            content: Raw assistant content from LLM.

        Returns:
            Canonical JSON string if valid; otherwise None.
        """
        try:
            parsed = self._safe_load_react_output(content)
        except ValueError:
            return None
        return json.dumps(parsed, ensure_ascii=False)

    def _format_message_content_for_log(self, content: str) -> str:
        """Format one message content for human-readable logging.

        Args:
            content: Raw message content.

        Returns:
            Pretty-printed string for log output.
        """
        try:
            parsed = self._safe_load_react_output(content)
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

    def _load_task_messages(self, task: ReactTask) -> list[dict[str, str]]:
        """Load persisted task-level LLM messages from database.

        Args:
            task: Task containing serialized message history.

        Returns:
            Sanitized OpenAI-style message list.
        """
        if not task.llm_messages:
            return []

        try:
            raw_messages = json.loads(task.llm_messages)
        except json.JSONDecodeError:
            logger.warning(
                "Invalid llm_messages JSON detected; resetting task messages. task_id=%s",
                task.task_id,
            )
            return []

        if not isinstance(raw_messages, list):
            logger.warning(
                "Invalid llm_messages payload type; expected list. task_id=%s",
                task.task_id,
            )
            return []

        normalized: list[dict[str, str]] = []
        for item in raw_messages:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = item.get("content")
            if (
                isinstance(role, str)
                and role in {"system", "user", "assistant"}
                and isinstance(content, str)
            ):
                normalized.append({"role": role, "content": content})
        return normalized

    def _persist_task_messages(
        self, task: ReactTask, messages: list[dict[str, str]]
    ) -> None:
        """Persist full task-level LLM message history.

        Args:
            task: Task to update.
            messages: Full OpenAI-style message list.
        """
        task.llm_messages = json.dumps(messages, ensure_ascii=False)
        task.updated_at = datetime.now(timezone.utc)
        self.db.add(task)
        self.db.commit()

    def _load_pending_action_result(
        self, task: ReactTask
    ) -> list[dict[str, Any]] | None:
        """Load pending action_result payload for next recursion user message.

        Args:
            task: Task containing serialized pending action result.

        Returns:
            Parsed action result list, or None if absent/invalid.
        """
        if not task.pending_action_result:
            return None

        try:
            payload = json.loads(task.pending_action_result)
        except json.JSONDecodeError:
            logger.warning(
                "Invalid pending_action_result JSON; dropping it. task_id=%s",
                task.task_id,
            )
            return None

        if not isinstance(payload, list):
            return None
        normalized_results: list[dict[str, Any]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            normalized_item: dict[str, Any] = {}
            item_id = item.get("id")
            if isinstance(item_id, str) and item_id:
                normalized_item["id"] = item_id
            if "result" in item:
                normalized_item["result"] = item["result"]
            elif "error" in item:
                normalized_item["error"] = item["error"]
            if normalized_item:
                normalized_results.append(normalized_item)
        return normalized_results

    def _set_pending_action_result(
        self, task: ReactTask, action_result: list[dict[str, Any]] | None
    ) -> None:
        """Update pending action result payload persisted on task.

        Args:
            task: Task to update.
            action_result: Payload list to persist; None clears the value.
        """
        task.pending_action_result = (
            json.dumps(action_result, ensure_ascii=False)
            if action_result is not None
            else None
        )

    def _load_llm_cache_state(self, task: ReactTask) -> dict[str, Any]:
        """Load protocol-specific LLM cache runtime state from task.

        Args:
            task: Task containing serialized cache state.

        Returns:
            Parsed cache state dictionary. Invalid payloads become empty dict.
        """
        if not task.llm_cache_state:
            return {}
        try:
            payload = json.loads(task.llm_cache_state)
        except json.JSONDecodeError:
            logger.warning(
                "Invalid llm_cache_state JSON detected; resetting. task_id=%s",
                task.task_id,
            )
            return {}
        if not isinstance(payload, dict):
            return {}
        return payload

    def _set_llm_cache_state(self, task: ReactTask, state: dict[str, Any]) -> None:
        """Persist protocol-specific LLM cache runtime state to task."""
        task.llm_cache_state = json.dumps(state, ensure_ascii=False)

    def _clear_task_runtime_messages(self, task: ReactTask) -> None:
        """Clear ephemeral per-task message/action state after task completion.

        Args:
            task: Task whose runtime prompting state should be reset.
        """
        task.llm_messages = "[]"
        task.pending_action_result = None
        task.llm_cache_state = "{}"
        task.updated_at = datetime.now(timezone.utc)
        self.db.add(task)
        self.db.commit()

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
        self, task: ReactTask, context: ReactContext, trace_id: str
    ) -> dict[str, Any]:
        """Build the per-recursion user payload appended to messages.

        Args:
            task: Current running task.
            context: Current context snapshot.
            trace_id: Server-generated recursion trace ID for this iteration.

        Returns:
            Serializable payload for the recursion user message.
        """
        payload: dict[str, Any] = {
            "trace_id": trace_id,
            "iteration": task.iteration + 1,
            "user_intent": task.user_intent,
            "current_plan": self._build_current_plan_payload(context),
        }
        pending_action_result = self._load_pending_action_result(task)
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

    def _normalize_step_status_update_payload(self, raw_value: Any) -> list[Any]:
        """Normalize raw step status updates into a list for validation.

        Why: model outputs are not guaranteed to keep a stable shape. Some
        responses emit a single object or a JSON string instead of a list. We
        normalize these variants to avoid silently dropping valid plan updates.

        Args:
            raw_value: Raw payload from model output.

        Returns:
            A list of raw update items. Invalid input returns an empty list.
        """
        if isinstance(raw_value, list):
            return raw_value
        if isinstance(raw_value, dict):
            return [raw_value]
        if isinstance(raw_value, str):
            try:
                parsed_value = json.loads(raw_value)
            except json.JSONDecodeError:
                return []
            if isinstance(parsed_value, list):
                return parsed_value
            if isinstance(parsed_value, dict):
                return [parsed_value]
        return []

    async def execute_recursion(
        self,
        task: ReactTask,
        context: ReactContext,
        trace_id: str,
        messages: list[dict[str, Any]],
        llm_chat_kwargs: dict[str, Any] | None = None,
    ) -> tuple[ReactRecursion, dict[str, Any]]:
        """
        Execute a single recursion cycle.

        Args:
            task: The ReactTask being executed
            context: Current context state
            messages: Message history for LLM
            llm_chat_kwargs: Extra runtime kwargs passed to LLM chat call.

        Returns:
            Tuple of (ReactRecursion record, event data for streaming)
        """
        # Use server-generated trace_id from this recursion cycle.
        context.update_for_new_recursion(trace_id)

        # Create recursion record
        recursion = ReactRecursion(
            trace_id=trace_id,
            task_id=task.task_id,
            react_task_id=task.id or 0,
            iteration_index=task.iteration,
            status="running",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        self.db.add(recursion)
        self.db.commit()
        self.db.refresh(recursion)

        # Call LLM WITHOUT tools parameter (using prompt-based approach).
        # Tools are described in the system prompt, and LLM returns tool calls
        # in action.output.
        try:
            token_counter = self._new_token_counter()
            response = None
            assistant_message_raw: str | None = None
            react_output: dict[str, Any] | None = None
            parse_error: ValueError | None = None
            request_messages = messages

            for parse_attempt in range(PARSE_RETRY_LIMIT + 1):
                response = await run_in_threadpool(
                    self.llm.chat,
                    messages=request_messages,
                    **(llm_chat_kwargs or {}),
                )  # type: ignore[arg-type]
                self._accumulate_usage(token_counter, response.usage)

                choice = response.first()
                message = choice.message

                # Parse JSON from content to get observe, thought, abstract, action_type
                content = message.content or "{}"
                assistant_message_raw = content

                try:
                    react_output = self._safe_load_react_output(content)
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

            if response is None or react_output is None:
                tokens_data = self._persist_accumulated_usage(
                    task, recursion, token_counter
                )
                recursion.status = "error"
                recursion.error_log = str(parse_error or "Failed to parse LLM output")
                recursion.updated_at = datetime.now(timezone.utc)
                self.db.commit()

                return recursion, {
                    "trace_id": trace_id,
                    "action_type": "ERROR",
                    "error": str(parse_error or "Failed to parse LLM output"),
                    "tokens": tokens_data,
                    "assistant_message": None,
                    "rollback_messages": True,
                    "llm_response_id": response.id if response is not None else None,
                }

            # Authoritative trace_id is generated by backend and injected in the
            # user payload. Ignore model-supplied trace_id to avoid drift/random IDs.
            react_output["trace_id"] = trace_id

            observe = react_output.get("observe", "")
            thought = react_output.get("thought", "")
            abstract = react_output.get("abstract", "")
            short_term_memory_append = react_output.get("short_term_memory_append", "")
            action = react_output.get("action", {})
            action_type = action.get("action_type", "")
            if isinstance(action_type, str):
                action_type = action_type.strip()
            action_output = action.get("output", {})
            # LLMs may place step_status_update in different locations.
            # We accept all known variants and normalize later.
            step_status_update = self._normalize_step_status_update_payload(
                action.get("step_status_update")
            )
            if not step_status_update:
                step_status_update = self._normalize_step_status_update_payload(
                    react_output.get("step_status_update")
                )
            if not step_status_update and isinstance(action_output, dict):
                step_status_update = self._normalize_step_status_update_payload(
                    action_output.get("step_status_update")
                )

            # Extract the plan step this recursion belongs to.
            # The LLM returns action.step_id when executing as part of a plan.
            # We must validate its presence when a plan exists, but never abort — a
            # missing step_id should only surface as a warning so the task can continue.
            action_step_id: str | None = action.get("step_id") or None

            # Extract session memory related fields (only used when action_type == ANSWER)
            session_memory_delta = react_output.get("session_memory_delta", {})
            session_subject = react_output.get("session_subject", {})
            session_goal = react_output.get("session_goal", {})
            task_summary = react_output.get("task_summary", {})

            # Skip empty/invalid responses
            if not action_type:
                tokens_data = self._persist_accumulated_usage(
                    task, recursion, token_counter
                )

                # Mark recursion as error
                recursion.status = "error"
                recursion.error_log = "LLM returned empty action_type"
                recursion.updated_at = datetime.now(timezone.utc)
                self.db.commit()

                return recursion, {
                    "trace_id": trace_id,
                    "action_type": "ERROR",
                    "error": "Empty action_type from LLM",
                    "tokens": tokens_data,
                    "assistant_message": assistant_message_raw,
                }

            if action_type not in ALLOWED_ACTION_TYPES:
                tokens_data = self._persist_accumulated_usage(
                    task, recursion, token_counter
                )

                recursion.status = "error"
                recursion.error_log = (
                    "LLM returned unsupported action_type: "
                    f"{action_type}. Allowed: {sorted(ALLOWED_ACTION_TYPES)}"
                )
                recursion.observe = observe
                recursion.thought = thought
                recursion.abstract = abstract
                recursion.updated_at = datetime.now(timezone.utc)
                self.db.commit()

                return recursion, {
                    "trace_id": trace_id,
                    "action_type": "ERROR",
                    "error": (
                        f"Unsupported action_type: {action_type}. "
                        f"Allowed values: {sorted(ALLOWED_ACTION_TYPES)}"
                    ),
                    "tokens": tokens_data,
                    "assistant_message": assistant_message_raw,
                }

            # Handle CALL_TOOL with native function calling
            tool_results = []
            reconstructed_tool_calls = []

            if action_type == "CALL_TOOL":
                # Extract tool_calls from action.output (prompt-based approach)
                tool_calls_from_output = action_output.get("tool_calls", [])

                # Validate that tool_calls exist when action_type is CALL_TOOL
                if not tool_calls_from_output:
                    tokens_data = self._persist_accumulated_usage(
                        task, recursion, token_counter
                    )

                    recursion.status = "error"
                    recursion.error_log = (
                        "action_type is CALL_TOOL but no tool_calls in action.output"
                    )
                    recursion.observe = observe
                    recursion.thought = thought
                    recursion.abstract = abstract
                    recursion.action_type = action_type
                    recursion.updated_at = datetime.now(timezone.utc)
                    self.db.commit()

                    return recursion, {
                        "trace_id": trace_id,
                        "action_type": "ERROR",
                        "error": "CALL_TOOL requires tool_calls in action.output",
                        "tokens": tokens_data,
                        "assistant_message": assistant_message_raw,
                    }

                # Process tool_calls from action.output
                for tool_call in tool_calls_from_output:
                    # tool_call format from LLM: {id, name, arguments}
                    # arguments is already a dict, not a JSON string
                    tool_call_id = tool_call.get("id", "")
                    func_name = tool_call.get("name", "")
                    func_args = tool_call.get("arguments", {})

                    # Validate arguments is dict
                    if not isinstance(func_args, dict):
                        # Try to parse if it's a string
                        try:
                            func_args = json.loads(func_args)
                        except (json.JSONDecodeError, TypeError):
                            func_args = {}
                            logger.warning(
                                f"Failed to parse tool arguments: {func_args}"
                            )

                    try:
                        # Execute tool asynchronously via thread pool
                        result = await run_in_threadpool(
                            self.tool_manager.execute,
                            func_name,
                            context=self.tool_execution_context,
                            **func_args,
                        )

                        tool_results.append(
                            {
                                "tool_call_id": tool_call_id,
                                "name": func_name,
                                "arguments": func_args,
                                "result": result,
                                "success": True,
                            }
                        )

                        # Keep tool_call in reconstructed format for event data
                        reconstructed_tool_calls.append(
                            {
                                "id": tool_call_id,
                                "name": func_name,
                                "arguments": func_args,
                            }
                        )

                    except Exception as e:
                        logger.error(f"Tool {func_name} execution failed: {e}")
                        # Provide helpful error message with available tools
                        if "not found in registry" in str(e):
                            available_tools = self.tool_manager.list_tools()
                            tool_names = [tool.name for tool in available_tools]
                            error_msg = (
                                f"Tool '{func_name}' not found. "
                                f"Available tools: {', '.join(tool_names)}"
                            )
                        else:
                            error_msg = f"Tool execution failed: {e!s}"
                        tool_results.append(
                            {
                                "tool_call_id": tool_call_id,
                                "name": func_name,
                                "arguments": func_args,
                                "error": error_msg,
                                "success": False,
                            }
                        )
                        # Always record the call attempt so the frontend knows
                        # which function was invoked and with what arguments,
                        # regardless of whether execution succeeded or failed.
                        reconstructed_tool_calls.append(
                            {
                                "id": tool_call_id,
                                "name": func_name,
                                "arguments": func_args,
                            }
                        )

            # Save recursion
            recursion.observe = observe
            recursion.thought = thought
            recursion.abstract = abstract
            recursion.action_type = action_type
            recursion.action_output = json.dumps(action_output, ensure_ascii=False)

            # Resolve plan_step_id: validate presence in plan mode, then persist.
            # Load current plan steps to determine whether a plan is active.
            existing_plan_steps = self.db.exec(
                select(ReactPlanStep).where(ReactPlanStep.task_id == task.task_id)
            ).all()
            plan_is_active = len(existing_plan_steps) > 0

            if plan_is_active and not action_step_id:
                # The LLM forgot to declare which step it's executing — log the
                # anomaly but do NOT abort; the recursion result will simply be
                # unassociated with any step (plan_step_id stays None).
                logger.error(
                    f"Action returned without step_id while a plan is active. "
                    f"The recursion result will NOT be attributed to any plan step. "
                    f"trace_id={trace_id}, task_id={task.task_id}, "
                    f"action_type={action_type}, iteration={task.iteration}"
                )
            elif action_step_id:
                # Validate that the declared step_id actually exists in the plan.
                known_step_ids = {s.step_id for s in existing_plan_steps}
                if action_step_id not in known_step_ids:
                    logger.error(
                        f"LLM returned unknown step_id='{action_step_id}' "
                        f"(known: {sorted(known_step_ids)}). "
                        f"Saving as-is for debugging; it will not match any plan step. "
                        f"trace_id={trace_id}, task_id={task.task_id}"
                    )

            recursion.plan_step_id = action_step_id

            # Validate optional step status updates requested by the LLM.
            raw_step_updates = step_status_update
            step_status_updates_validated: list[dict[str, str]] = []
            if raw_step_updates and isinstance(raw_step_updates, list):
                allowed_step_statuses = {"pending", "running", "done", "error"}
                for raw_update in raw_step_updates:
                    if not isinstance(raw_update, dict):
                        logger.warning(
                            "Ignoring invalid step_status_update item (not object). "
                            f"trace_id={trace_id}, task_id={task.task_id}, payload={raw_update}"
                        )
                        continue
                    raw_step_id = raw_update.get("step_id")
                    raw_status = raw_update.get("status")
                    if isinstance(raw_step_id, str):
                        step_id_to_update = raw_step_id.strip()
                    elif isinstance(raw_step_id, int):
                        # Some providers may coerce IDs to numbers.
                        step_id_to_update = str(raw_step_id)
                    else:
                        step_id_to_update = ""

                    status_to_update = (
                        raw_status.strip().lower()
                        if isinstance(raw_status, str)
                        else ""
                    )

                    if not step_id_to_update:
                        logger.warning(
                            "Ignoring invalid step_status_update with missing/invalid step_id. "
                            f"trace_id={trace_id}, task_id={task.task_id}, payload={raw_update}"
                        )
                        continue
                    if (
                        not isinstance(status_to_update, str)
                        or status_to_update not in allowed_step_statuses
                    ):
                        logger.warning(
                            "Ignoring invalid step_status_update with unsupported status. "
                            f"trace_id={trace_id}, task_id={task.task_id}, payload={raw_update}"
                        )
                        continue
                    step_status_updates_validated.append(
                        {"step_id": step_id_to_update, "status": status_to_update}
                    )

            # Save short_term_memory if any
            if short_term_memory_append:
                recursion.short_term_memory = short_term_memory_append

            # Save tool_call_results if any
            if tool_results:
                tool_results_json = json.dumps(tool_results, ensure_ascii=False)
                recursion.tool_call_results = tool_results_json

            # Persist usage totals (including any parse-retry attempt).
            tokens_data = self._persist_accumulated_usage(
                task, recursion, token_counter
            )

            recursion.status = "done"
            recursion.updated_at = datetime.now(timezone.utc)
            self.db.commit()

            # Save current_state snapshot for this recursion
            # This enables state recovery, debugging, and historical analysis

            # Append current recursion to context.recursion_history for the state snapshot.
            # Tool execution results are merged directly into action_output.tool_calls[n]
            # as `result` and `success` fields (§5.5 of context_template.md), rather
            # than stored in a separate top-level `tool_call_results` list.
            if tool_results:
                result_by_id = {
                    r["tool_call_id"]: r for r in tool_results if "tool_call_id" in r
                }
                for tc in action_output.get("tool_calls", []):
                    matched = result_by_id.get(tc.get("id", ""))
                    if matched is not None:
                        tc["result"] = matched.get("result", "")
                        tc["success"] = matched.get("success", False)

            current_rec_dict = {
                "iteration": task.iteration,
                "trace_id": trace_id,
                "observe": observe,
                "thought": thought,
                "action": {
                    "action_type": action_type,
                    "output": action_output,
                    "step_status_update": step_status_updates_validated,
                },
            }

            # --- 1. UPDATE IN-MEMORY STATE BEfORE SNAPSHOT ---
            # A snapshot must reflect all mutations (RE_PLAN, memory) that occurred
            # in this recursion cycle so that the state snapshot is consistent.

            # Sync short-term memory to memory context if present
            if short_term_memory_append:
                if "short_term" not in context.context.get("memory", {}):
                    if "memory" not in context.context:
                        context.context["memory"] = {}
                    context.context["memory"]["short_term"] = []
                context.context["memory"]["short_term"].append(
                    {"trace_id": trace_id, "memory": short_term_memory_append}
                )

            # Sync RE_PLAN updates to database and memory context
            if action_type == "RE_PLAN":
                plan_data = action_output.get("plan", [])

                # Delete old plan steps in DB
                from sqlmodel import delete

                delete_stmt = delete(ReactPlanStep).where(
                    ReactPlanStep.task_id == task.task_id
                )
                self.db.exec(delete_stmt)  # type: ignore[arg-type]

                # Create new plan steps in DB and rebuild memory representation
                new_plan_context = []
                for step_data in plan_data:
                    general_goal = step_data.get("general_goal", "")
                    specific_description = step_data.get("specific_description", "")
                    completion_criteria = step_data.get("completion_criteria", "")
                    step = ReactPlanStep(
                        task_id=task.task_id,
                        react_task_id=task.id or 0,
                        step_id=step_data.get("step_id", ""),
                        general_goal=general_goal,
                        specific_description=specific_description,
                        completion_criteria=completion_criteria,
                        status=step_data.get("status", "pending"),
                    )
                    self.db.add(step)

                    # Update in-memory context so the snapshot captures the new plan
                    new_plan_context.append(
                        {
                            "step_id": step.step_id,
                            "general_goal": general_goal,
                            "specific_description": specific_description,
                            "completion_criteria": completion_criteria,
                            "status": step.status,
                            "recursion_history": [],
                        }
                    )
                self.db.commit()
                context.context["plan"] = new_plan_context

            # Sync explicit step status update from LLM to task state.
            plan_step_rows = self.db.exec(
                select(ReactPlanStep).where(ReactPlanStep.task_id == task.task_id)
            ).all()
            plan_step_by_normalized_id = {
                step.step_id.strip(): step
                for step in plan_step_rows
                if isinstance(step.step_id, str)
            }

            for validated_update in step_status_updates_validated:
                step_id_to_update = validated_update["step_id"]
                status_to_update = validated_update["status"]

                plan_step = plan_step_by_normalized_id.get(step_id_to_update.strip())
                if plan_step is None:
                    logger.warning(
                        "Ignoring step_status_update for unknown step_id. "
                        f"trace_id={trace_id}, task_id={task.task_id}, "
                        f"step_id={step_id_to_update}, status={status_to_update}, "
                        f"known_step_ids={sorted(plan_step_by_normalized_id.keys())}"
                    )
                    continue

                plan_step.status = status_to_update
                plan_step.updated_at = datetime.now(timezone.utc)
                self.db.add(plan_step)
                self.db.commit()

                # Keep in-memory snapshot context aligned with DB status.
                for plan_step_ctx in context.context.get("plan", []):
                    plan_step_ctx_id = plan_step_ctx.get("step_id")
                    if (
                        isinstance(plan_step_ctx_id, str)
                        and plan_step_ctx_id.strip() == step_id_to_update.strip()
                    ):
                        plan_step_ctx["status"] = status_to_update
                        break

            # --- 2. LINK TARGET RECURSION ---
            # Sync the current recursion into its matching plan step for the snapshot
            # (Matches what `context.py` from_task does on reload).
            added_to_plan = False
            if action_step_id:
                for plan_step in context.context.get("plan", []):
                    if plan_step.get("step_id") == action_step_id:
                        plan_step["recursion_history"].append(current_rec_dict)
                        added_to_plan = True
                        break

            # If it doesn't belong to a plan step, keep it in the top-level list
            if not added_to_plan:
                context.recursion_history.append(current_rec_dict)

            # --- 3. GENERATE CURRENT STATE SNAPSHOT ---
            current_state_json = json.dumps(context.to_dict(), ensure_ascii=False)
            recursion_state = ReactRecursionState(
                trace_id=trace_id,
                task_id=task.task_id,
                iteration_index=task.iteration,
                current_state=current_state_json,
                created_at=datetime.now(timezone.utc),
            )
            self.db.add(recursion_state)
            self.db.commit()

            # Runtime LLM messages are managed in run_task, where each recursion
            # appends one user payload and one assistant JSON response.
            if action_type == "ANSWER":
                # ANSWER task finalization is handled in run_task.
                pass

            if action_type == "CLARIFY":
                # For CLARIFY, we update task status to 'waiting_input'
                # The run_task loop will handle the break
                task.status = "waiting_input"
                task.updated_at = datetime.now(timezone.utc)
                self.db.commit()

            # Prepare event data
            event_data = {
                "trace_id": trace_id,
                "action_type": action_type,
                "llm_response_id": response.id,
                "observe": observe,
                "thought": thought,
                "abstract": abstract,
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
            logger.error(
                f"Recursion execution failed for trace_id={trace_id}\n"
                f"Error type: {type(e).__name__}\n"
                f"Error message: {error_msg}\n"
                f"Task ID: {task.task_id}\n"
                f"Iteration: {task.iteration}"
            )

            recursion.status = "error"
            recursion.error_log = error_msg
            recursion.updated_at = datetime.now(timezone.utc)
            self.db.commit()

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
                "rollback_messages": rollback_messages,
            }

    async def run_task(
        self,
        task: ReactTask,
        selected_skills_text: str = "",
        turn_user_message: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Execute complete ReAct task with streaming events.

        Args:
            task: The ReactTask to execute.
            selected_skills_text: Selected skill markdown block injected in system prompt.
            turn_user_message: User input of the current turn (used for chat history).

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
            )

        # Update task status
        task.status = "running"
        task.updated_at = datetime.now(timezone.utc)
        self.db.commit()

        runtime_messages = self._load_task_messages(task)
        if not runtime_messages:
            runtime_messages = [
                {
                    "role": "system",
                    "content": build_runtime_system_prompt(
                        tool_manager=self.tool_manager,
                        session_memory=session_memory_dict,
                        skills=selected_skills_text,
                    ),
                }
            ]
            self._persist_task_messages(task, runtime_messages)
        logged_message_count = len(runtime_messages)
        llm_cache_state = self._load_llm_cache_state(task)

        try:
            while task.iteration < task.max_iteration:
                trace_id = str(uuid.uuid4())

                # Check if task was cancelled
                if self.cancelled:
                    logger.info(f"Task {task.task_id} cancelled, exiting loop")
                    task.status = "cancelled"
                    task.updated_at = datetime.now(timezone.utc)
                    self.db.commit()
                    self._clear_task_runtime_messages(task)
                    break
                # Load current context
                context = ReactContext.from_task(task, self.db)

                # Yield recursion start event
                yield {
                    "type": "recursion_start",
                    "task_id": task.task_id,
                    "trace_id": trace_id,
                    "iteration": task.iteration,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }

                # Append iteration payload as a new user message.
                user_payload = self._build_recursion_user_payload(
                    task,
                    context,
                    trace_id,
                )
                runtime_messages.append(
                    {
                        "role": "user",
                        "content": json.dumps(user_payload, ensure_ascii=False),
                    }
                )
                self._persist_task_messages(task, runtime_messages)
                self._log_messages_pretty(
                    messages=runtime_messages,
                    task_id=task.task_id,
                    iteration=task.iteration + 1,
                    trace_id="pending",
                    phase="send",
                    start_index=logged_message_count,
                    iteration_message_start=1,
                )
                logged_message_count = len(runtime_messages)

                messages_for_llm = runtime_messages
                llm_chat_kwargs: dict[str, Any] = {"_pivot_task_id": task.task_id}
                if self._uses_incremental_request_messages():
                    previous_response_id = llm_cache_state.get("previous_response_id")
                    if isinstance(previous_response_id, str) and previous_response_id:
                        llm_chat_kwargs["_pivot_previous_response_id"] = (
                            previous_response_id
                        )
                        messages_for_llm = runtime_messages[-1:]

                # Execute recursion against the fully accumulated message history.
                recursion, event_data = await self.execute_recursion(
                    task=task,
                    context=context,
                    trace_id=trace_id,
                    messages=messages_for_llm,
                    llm_chat_kwargs=llm_chat_kwargs,
                )
                rollback_messages = bool(event_data.get("rollback_messages", False))
                if rollback_messages:
                    # Parse errors should be visible to users, but must not pollute
                    # persisted LLM messages. Roll back the just-appended user payload.
                    if runtime_messages and runtime_messages[-1].get("role") == "user":
                        runtime_messages.pop()
                    self._persist_task_messages(task, runtime_messages)
                    logged_message_count = len(runtime_messages)
                    if self._uses_incremental_request_messages():
                        # Drop chained cache linkage so malformed outputs do not keep
                        # poisoning subsequent retries.
                        llm_cache_state.pop("previous_response_id", None)
                else:
                    assistant_message = event_data.get("assistant_message")
                    if isinstance(assistant_message, str) and assistant_message:
                        runtime_messages.append(
                            {"role": "assistant", "content": assistant_message}
                        )
                        self._persist_task_messages(task, runtime_messages)
                        self._log_messages_pretty(
                            messages=runtime_messages,
                            task_id=task.task_id,
                            iteration=task.iteration + 1,
                            trace_id=str(event_data.get("trace_id", "")),
                            phase="receive",
                            start_index=logged_message_count,
                            iteration_message_start=2,
                        )
                        logged_message_count = len(runtime_messages)
                    if self._uses_incremental_request_messages():
                        response_id = event_data.get("llm_response_id")
                        if isinstance(response_id, str) and response_id:
                            llm_cache_state["previous_response_id"] = response_id

                action_type = event_data.get("action_type", "")
                if isinstance(action_type, str):
                    action_type = action_type.strip()
                next_action_result = self._build_next_pending_action_result(event_data)
                if next_action_result is not None:
                    self._set_pending_action_result(task, next_action_result)
                elif action_type != "ERROR":
                    # Keep previous action_result only when this recursion failed.
                    self._set_pending_action_result(task, None)
                self._set_llm_cache_state(task, llm_cache_state)
                self.db.add(task)
                self.db.commit()

                # Yield Observe, Thought, Action events with token info
                if recursion.observe:
                    yield {
                        "type": "observe",
                        "task_id": task.task_id,
                        "trace_id": event_data.get("trace_id"),
                        "iteration": task.iteration,
                        "delta": recursion.observe,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
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
                        "timestamp": datetime.now(timezone.utc).isoformat(),
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
                        "timestamp": datetime.now(timezone.utc).isoformat(),
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
                    "timestamp": datetime.now(timezone.utc).isoformat(),
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
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }

                elif action_type == "RE_PLAN":
                    plan_output = event_data.get("output")
                    yield {
                        "type": "plan_update",
                        "task_id": task.task_id,
                        "trace_id": event_data.get("trace_id"),
                        "iteration": task.iteration,
                        "data": plan_output,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
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
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }

                elif action_type == "CLARIFY":
                    yield {
                        "type": "clarify",
                        "task_id": task.task_id,
                        "trace_id": event_data.get("trace_id"),
                        "iteration": task.iteration,
                        "data": event_data.get("output"),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }

                    # Increment iteration before breaking so next run starts at next iteration
                    task.iteration += 1
                    task.updated_at = datetime.now(timezone.utc)
                    self.db.commit()

                    # Break loop as task is waiting for input
                    break

                elif action_type == "ANSWER":
                    yield {
                        "type": "answer",
                        "task_id": task.task_id,
                        "trace_id": event_data.get("trace_id"),
                        "iteration": task.iteration,
                        "data": event_data.get("output"),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
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
                    task.status = "completed"
                    task.updated_at = datetime.now(timezone.utc)
                    self.db.commit()
                    self._clear_task_runtime_messages(task)

                    yield {
                        "type": "task_complete",
                        "task_id": task.task_id,
                        "iteration": task.iteration,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
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
                    logger.warning(
                        f"Recursion error at iteration {task.iteration}, retrying... "
                        f"Error: {error_msg}"
                    )

                    yield {
                        "type": "error",
                        "task_id": task.task_id,
                        "trace_id": event_data.get("trace_id"),
                        "iteration": task.iteration,
                        "data": {"error": error_msg},
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }

                    # For malformed JSON we roll back this recursion from the LLM
                    # conversation and retry without consuming iteration budget.
                    if not rollback_messages:
                        task.iteration += 1
                        task.updated_at = datetime.now(timezone.utc)
                        self.db.commit()
                    continue

                # Update iteration count
                task.iteration += 1
                task.updated_at = datetime.now(timezone.utc)
                self.db.commit()

            # Max iteration reached
            if task.iteration >= task.max_iteration and task.status == "running":
                task.status = "failed"
                task.updated_at = datetime.now(timezone.utc)
                self.db.commit()
                self._clear_task_runtime_messages(task)

                yield {
                    "type": "error",
                    "task_id": task.task_id,
                    "iteration": task.iteration,
                    "data": {"error": "Maximum iteration reached"},
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }

        except Exception as e:
            task.status = "failed"
            task.updated_at = datetime.now(timezone.utc)
            self.db.commit()
            self._clear_task_runtime_messages(task)

            yield {
                "type": "error",
                "task_id": task.task_id,
                "iteration": task.iteration,
                "data": {"error": str(e)},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
