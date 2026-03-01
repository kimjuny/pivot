"""ReAct Engine - Core execution engine for ReAct state machine.

This module implements the main execution loop for the ReAct agent,
handling recursion cycles, tool calling, and state management.
"""

import json
import logging
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

    def _normalize_assistant_message_json(self, content: str) -> str | None:
        """Normalize assistant content to strict JSON string for persistence.

        Args:
            content: Raw assistant content from LLM.

        Returns:
            Canonical JSON string if valid; otherwise None.
        """
        try:
            parsed = self._safe_load_json(content)
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
            parsed = self._safe_load_json(content)
        except ValueError:
            return content
        return json.dumps(parsed, ensure_ascii=False, indent=2)

    def _log_messages_pretty(
        self,
        messages: list[dict[str, Any]],
        task_id: str,
        iteration: int,
        trace_id: str,
    ) -> None:
        """Log full message history with readable per-message formatting.

        Args:
            messages: Full message history sent to LLM.
            task_id: Current task UUID.
            iteration: Current iteration index.
            trace_id: Current recursion trace ID.
        """
        rendered_lines = [
            (
                "LLM messages snapshot\n"
                f"task_id={task_id} iteration={iteration} trace_id={trace_id} "
                f"count={len(messages)}"
            )
        ]
        for idx, msg in enumerate(messages):
            role = msg.get("role", "unknown")
            if role == "system":
                continue
            raw_content = msg.get("content", "")
            content = raw_content if isinstance(raw_content, str) else str(raw_content)
            rendered_lines.append(f"[{idx}] role={role}")
            rendered_lines.append(self._format_message_content_for_log(content))

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

    def _clear_task_runtime_messages(self, task: ReactTask) -> None:
        """Clear ephemeral per-task message/action state after task completion.

        Args:
            task: Task whose runtime prompting state should be reset.
        """
        task.llm_messages = "[]"
        task.pending_action_result = None
        task.updated_at = datetime.now(timezone.utc)
        self.db.add(task)
        self.db.commit()

    def _build_current_plan_payload(self, context: ReactContext) -> list[dict[str, Any]]:
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
        self, task: ReactTask, context: ReactContext
    ) -> dict[str, Any]:
        """Build the per-recursion user payload appended to messages.

        Args:
            task: Current running task.
            context: Current context snapshot.

        Returns:
            Serializable payload for the recursion user message.
        """
        payload: dict[str, Any] = {
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

    async def execute_recursion(
        self,
        task: ReactTask,
        context: ReactContext,
        messages: list[dict[str, Any]],
    ) -> tuple[ReactRecursion, dict[str, Any]]:
        """
        Execute a single recursion cycle.

        Args:
            task: The ReactTask being executed
            context: Current context state
            messages: Message history for LLM

        Returns:
            Tuple of (ReactRecursion record, event data for streaming)
        """
        # Generate trace_id for this recursion
        trace_id = str(uuid.uuid4())
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
            self._log_messages_pretty(
                messages=messages,
                task_id=task.task_id,
                iteration=task.iteration,
                trace_id=trace_id,
            )
            response = await run_in_threadpool(self.llm.chat, messages=messages)  # type: ignore[arg-type]
            choice = response.first()
            message = choice.message

            # Parse JSON from content to get observe, thought, abstract, action_type
            content = message.content or "{}"
            assistant_message_json = self._normalize_assistant_message_json(content)

            # Use safe JSON parser to handle all common LLM formatting issues
            try:
                react_output = self._safe_load_json(content)
                logger.debug(f"Successfully parsed JSON (trace_id={trace_id})")
            except ValueError as e:
                # All parsing attempts failed, log and return error
                logger.error(
                    f"Failed to parse LLM response\n"
                    f"Trace ID: {trace_id}\n"
                    f"Task ID: {task.task_id}\n"
                    f"Iteration: {task.iteration}\n"
                    f"Error: {e}"
                )

                # Save token usage even on error (tokens were still consumed)
                tokens_data = None
                if response.usage:
                    recursion.prompt_tokens = response.usage.prompt_tokens
                    recursion.completion_tokens = response.usage.completion_tokens
                    recursion.total_tokens = response.usage.total_tokens
                    recursion.cached_input_tokens = response.usage.cached_input_tokens
                    task.total_prompt_tokens += response.usage.prompt_tokens
                    task.total_completion_tokens += response.usage.completion_tokens
                    task.total_tokens += response.usage.total_tokens
                    task.total_cached_input_tokens += response.usage.cached_input_tokens
                    tokens_data = {
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens,
                        "total_tokens": response.usage.total_tokens,
                        "cached_input_tokens": response.usage.cached_input_tokens,
                    }

                recursion.status = "error"
                recursion.error_log = str(e)
                recursion.updated_at = datetime.now(timezone.utc)
                self.db.commit()

                return recursion, {
                    "trace_id": trace_id,
                    "action_type": "ERROR",
                    "error": str(e),
                    "tokens": tokens_data,
                    "assistant_message": None,
                    "rollback_messages": True,
                }

            observe = react_output.get("observe", "")
            thought = react_output.get("thought", "")
            abstract = react_output.get("abstract", "")
            short_term_memory_append = react_output.get("short_term_memory_append", "")
            action = react_output.get("action", {})
            action_type = action.get("action_type", "")
            action_output = action.get("output", {})
            step_status_update = action.get("step_status_update", [])

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
                # Save token usage even on error (tokens were still consumed)
                tokens_data = None
                if response.usage:
                    recursion.prompt_tokens = response.usage.prompt_tokens
                    recursion.completion_tokens = response.usage.completion_tokens
                    recursion.total_tokens = response.usage.total_tokens
                    recursion.cached_input_tokens = response.usage.cached_input_tokens
                    task.total_prompt_tokens += response.usage.prompt_tokens
                    task.total_completion_tokens += response.usage.completion_tokens
                    task.total_tokens += response.usage.total_tokens
                    task.total_cached_input_tokens += response.usage.cached_input_tokens
                    tokens_data = {
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens,
                        "total_tokens": response.usage.total_tokens,
                        "cached_input_tokens": response.usage.cached_input_tokens,
                    }

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
                    "assistant_message": assistant_message_json,
                }

            # Handle CALL_TOOL with native function calling
            tool_results = []
            reconstructed_tool_calls = []

            if action_type == "CALL_TOOL":
                # Extract tool_calls from action.output (prompt-based approach)
                tool_calls_from_output = action_output.get("tool_calls", [])

                # Validate that tool_calls exist when action_type is CALL_TOOL
                if not tool_calls_from_output:
                    # Save token usage even on error (tokens were still consumed)
                    tokens_data = None
                    if response.usage:
                        recursion.prompt_tokens = response.usage.prompt_tokens
                        recursion.completion_tokens = response.usage.completion_tokens
                        recursion.total_tokens = response.usage.total_tokens
                        recursion.cached_input_tokens = (
                            response.usage.cached_input_tokens
                        )
                        task.total_prompt_tokens += response.usage.prompt_tokens
                        task.total_completion_tokens += response.usage.completion_tokens
                        task.total_tokens += response.usage.total_tokens
                        task.total_cached_input_tokens += (
                            response.usage.cached_input_tokens
                        )
                        tokens_data = {
                            "prompt_tokens": response.usage.prompt_tokens,
                            "completion_tokens": response.usage.completion_tokens,
                            "total_tokens": response.usage.total_tokens,
                            "cached_input_tokens": response.usage.cached_input_tokens,
                        }

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
                        "assistant_message": assistant_message_json,
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
            raw_step_updates = (
                [step_status_update]
                if isinstance(step_status_update, dict)
                else step_status_update
            )
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
                    step_id_to_update = raw_update.get("step_id")
                    status_to_update = raw_update.get("status")
                    if not isinstance(step_id_to_update, str) or not step_id_to_update:
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

            # Save token usage from LLM response
            if response.usage:
                recursion.prompt_tokens = response.usage.prompt_tokens
                recursion.completion_tokens = response.usage.completion_tokens
                recursion.total_tokens = response.usage.total_tokens
                recursion.cached_input_tokens = response.usage.cached_input_tokens

                # Update task-level token accumulation
                task.total_prompt_tokens += response.usage.prompt_tokens
                task.total_completion_tokens += response.usage.completion_tokens
                task.total_tokens += response.usage.total_tokens
                task.total_cached_input_tokens += response.usage.cached_input_tokens

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
                    general_goal = step_data.get("general_goal") or step_data.get(
                        "description", ""
                    )
                    specific_description = (
                        step_data.get("specific_description")
                        or step_data.get("description")
                        or general_goal
                    )
                    completion_criteria = (
                        step_data.get("completion_criteria")
                        or step_data.get("completionCriteria")
                        or ""
                    )
                    step = ReactPlanStep(
                        task_id=task.task_id,
                        react_task_id=task.id or 0,
                        step_id=step_data.get("step_id", ""),
                        # Legacy DB column: preserve the agent-facing detail text.
                        description=specific_description,
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
            for validated_update in step_status_updates_validated:
                step_id_to_update = validated_update["step_id"]
                status_to_update = validated_update["status"]

                plan_step_stmt = (
                    select(ReactPlanStep)
                    .where(ReactPlanStep.task_id == task.task_id)
                    .where(ReactPlanStep.step_id == step_id_to_update)
                )
                plan_step = self.db.exec(plan_step_stmt).first()
                if plan_step is None:
                    logger.warning(
                        "Ignoring step_status_update for unknown step_id. "
                        f"trace_id={trace_id}, task_id={task.task_id}, "
                        f"step_id={step_id_to_update}, status={status_to_update}"
                    )
                    continue

                plan_step.status = status_to_update
                plan_step.updated_at = datetime.now(timezone.utc)
                self.db.add(plan_step)
                self.db.commit()

                # Keep in-memory snapshot context aligned with DB status.
                for plan_step_ctx in context.context.get("plan", []):
                    if plan_step_ctx.get("step_id") == step_id_to_update:
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
                "observe": observe,
                "thought": thought,
                "abstract": abstract,
                "output": action_output,
                "assistant_message": assistant_message_json,
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
            if response.usage:
                event_data["tokens"] = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                    "cached_input_tokens": response.usage.cached_input_tokens,
                }

            return recursion, event_data

        except Exception as e:
            # Handle errors with detailed logging
            error_msg = str(e)
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

            return recursion, {
                "trace_id": trace_id,
                "action_type": "ERROR",
                "error": error_msg,
                "assistant_message": None,
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

        try:
            while task.iteration < task.max_iteration:
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
                    "iteration": task.iteration,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }

                # Append iteration payload as a new user message.
                user_payload = self._build_recursion_user_payload(task, context)
                runtime_messages.append(
                    {
                        "role": "user",
                        "content": json.dumps(user_payload, ensure_ascii=False),
                    }
                )
                self._persist_task_messages(task, runtime_messages)

                # Execute recursion against the fully accumulated message history.
                recursion, event_data = await self.execute_recursion(
                    task=task,
                    context=context,
                    messages=runtime_messages,
                )
                rollback_messages = bool(event_data.get("rollback_messages", False))
                if rollback_messages:
                    # Parse errors should be visible to users, but must not pollute
                    # persisted LLM messages. Roll back the just-appended user payload.
                    if runtime_messages and runtime_messages[-1].get("role") == "user":
                        runtime_messages.pop()
                    self._persist_task_messages(task, runtime_messages)
                else:
                    assistant_message = event_data.get("assistant_message")
                    if isinstance(assistant_message, str) and assistant_message:
                        runtime_messages.append(
                            {"role": "assistant", "content": assistant_message}
                        )
                        self._persist_task_messages(task, runtime_messages)

                action_type = event_data.get("action_type", "")
                next_action_result = self._build_next_pending_action_result(event_data)
                if next_action_result is not None:
                    self._set_pending_action_result(task, next_action_result)
                elif action_type != "ERROR":
                    # Keep previous action_result only when this recursion failed.
                    self._set_pending_action_result(task, None)
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
