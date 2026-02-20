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
from app.orchestration.tool.manager import ToolManager
from app.services.session_memory_service import SessionMemoryService
from sqlmodel import Session, select

from .context import ReactContext
from .prompt_template import build_system_prompt

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
        self, llm: AbstractLLM, tool_manager: ToolManager, db: Session
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

    async def execute_recursion(
        self,
        task: ReactTask,
        context: ReactContext,
        messages: list[dict[str, Any]],
        session_memory: dict[str, Any] | None = None,
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

        # Build system prompt with current context, available tools, and session memory
        system_prompt = build_system_prompt(context, self.tool_manager, session_memory)

        # Update system message at index 0 (MUST be first for most LLMs)
        # messages[0] = system prompt (updated each recursion)
        # messages[1] = user message (fixed)
        # messages[2+] = conversation history (assistant responses, tool results, etc.)
        messages[0] = {"role": "system", "content": system_prompt}

        # Call LLM WITHOUT tools parameter (using prompt-based approach)
        # Tools are described in the system prompt, and LLM returns tool calls in action.output
        try:
            response = self.llm.chat(messages=messages)  # type: ignore[arg-type]
            choice = response.first()
            message = choice.message

            # Parse JSON from content to get observe, thought, abstract, action_type
            content = message.content or "{}"
            logger.info(f"LLM response: {content}")

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
                    task.total_prompt_tokens += response.usage.prompt_tokens
                    task.total_completion_tokens += response.usage.completion_tokens
                    task.total_tokens += response.usage.total_tokens
                    tokens_data = {
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens,
                        "total_tokens": response.usage.total_tokens,
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
                }

            observe = react_output.get("observe", "")
            thought = react_output.get("thought", "")
            abstract = react_output.get("abstract", "")
            short_term_memory_append = react_output.get("short_term_memory_append", "")
            action = react_output.get("action", {})
            action_type = action.get("action_type", "")
            action_output = action.get("output", {})

            # Extract the plan step this recursion belongs to.
            # The LLM returns action.step_id when executing as part of a plan.
            # We must validate its presence when a plan exists, but never abort — a
            # missing step_id should only surface as a warning so the task can continue.
            action_step_id: str | None = action.get("step_id") or None

            # Extract session memory related fields (only used when action_type == ANSWER)
            session_memory_delta = react_output.get("session_memory_delta", {})
            session_subject = react_output.get("session_subject", {})
            session_object = react_output.get("session_object", {})
            task_summary = react_output.get("task_summary", {})

            # Skip empty/invalid responses
            if not action_type:
                # Save token usage even on error (tokens were still consumed)
                tokens_data = None
                if response.usage:
                    recursion.prompt_tokens = response.usage.prompt_tokens
                    recursion.completion_tokens = response.usage.completion_tokens
                    recursion.total_tokens = response.usage.total_tokens
                    task.total_prompt_tokens += response.usage.prompt_tokens
                    task.total_completion_tokens += response.usage.completion_tokens
                    task.total_tokens += response.usage.total_tokens
                    tokens_data = {
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens,
                        "total_tokens": response.usage.total_tokens,
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
                }

            # Handle CALL_TOOL with native function calling
            tool_results = []
            reconstructed_tool_calls = []

            if action_type == "CALL_TOOL":
                # Extract tool_calls from action.output (prompt-based approach)
                tool_calls_from_output = action_output.get("tool_calls", [])
                logger.info(
                    f"Tool calls from action.output: {json.dumps(tool_calls_from_output, ensure_ascii=False, indent=2)}"
                )

                # Validate that tool_calls exist when action_type is CALL_TOOL
                if not tool_calls_from_output:
                    # Save token usage even on error (tokens were still consumed)
                    tokens_data = None
                    if response.usage:
                        recursion.prompt_tokens = response.usage.prompt_tokens
                        recursion.completion_tokens = response.usage.completion_tokens
                        recursion.total_tokens = response.usage.total_tokens
                        task.total_prompt_tokens += response.usage.prompt_tokens
                        task.total_completion_tokens += response.usage.completion_tokens
                        task.total_tokens += response.usage.total_tokens
                        tokens_data = {
                            "prompt_tokens": response.usage.prompt_tokens,
                            "completion_tokens": response.usage.completion_tokens,
                            "total_tokens": response.usage.total_tokens,
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
                        # Execute tool
                        result = self.tool_manager.execute(func_name, **func_args)

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

                # Update task-level token accumulation
                task.total_prompt_tokens += response.usage.prompt_tokens
                task.total_completion_tokens += response.usage.completion_tokens
                task.total_tokens += response.usage.total_tokens

            recursion.status = "done"
            recursion.updated_at = datetime.now(timezone.utc)
            self.db.commit()

            # Save current_state snapshot for this recursion
            # This enables state recovery, debugging, and historical analysis

            # Append current recursion to context.recursions for the state snapshot.
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
                "trace_id": trace_id,
                "observe": observe,
                "thought": thought,
                "action": {
                    "action_type": action_type,
                    "output": action_output,
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
                context.context["memory"]["short_term"].append({
                    "trace_id": trace_id,
                    "memory": short_term_memory_append
                })

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
                    step = ReactPlanStep(
                        task_id=task.task_id,
                        react_task_id=task.id or 0,
                        step_id=step_data.get("step_id", ""),
                        description=step_data.get("description", ""),
                        status=step_data.get("status", "pending"),
                    )
                    self.db.add(step)
                    
                    # Update in-memory context so the snapshot captures the new plan
                    new_plan_context.append({
                        "step_id": step.step_id,
                        "description": step.description,
                        "status": step.status,
                        "recursions": [],
                    })
                self.db.commit()
                context.context["plan"] = new_plan_context

            # --- 2. LINK TARGET RECURSION ---
            # Sync the current recursion into its matching plan step for the snapshot
            # (Matches what `context.py` from_task does on reload).
            added_to_plan = False
            if action_step_id:
                for plan_step in context.context.get("plan", []):
                    if plan_step.get("step_id") == action_step_id:
                        plan_step["recursions"].append(current_rec_dict)
                        added_to_plan = True
                        break

            # If it doesn't belong to a plan step, keep it in the top-level list
            if not added_to_plan:
                context.recursions.append(current_rec_dict)

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

            # Do NOT add assistant messages to avoid confusing LLM
            # The state machine injection in next recursion's system prompt
            # will include tool_call_results in last_recursion
            # This is sufficient for LLM to understand what happened
            if action_type == "ANSWER":
                # For ANSWER, don't add to messages as the task is complete
                # Task status will be updated to 'completed' in run_task
                pass

            if action_type == "CLARIFY":
                # For CLARIFY, we update task status to 'waiting_input'
                # The run_task loop will handle the break
                task.status = "waiting_input"
                task.updated_at = datetime.now(timezone.utc)
                self.db.commit()

            # For all other action types (CALL_TOOL, RE_PLAN, etc.),
            # we rely on the state machine context to convey the results
            # No need to append to messages

            # Prepare event data
            event_data = {
                "trace_id": trace_id,
                "action_type": action_type,
                "observe": observe,
                "thought": thought,
                "abstract": abstract,
                "output": action_output,
                "tool_calls": reconstructed_tool_calls,  # Native tool_calls
                "tool_results": tool_results,  # Tool execution results
                # Session memory related fields (for ANSWER action)
                "session_memory_delta": session_memory_delta,
                "session_subject": session_subject,
                "session_object": session_object,
                "task_summary": task_summary,
            }

            # Add token usage if available
            if response.usage:
                event_data["tokens"] = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
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
            }

    async def run_task(self, task: ReactTask) -> AsyncIterator[dict[str, Any]]:
        """
        Execute complete ReAct task with streaming events.

        Args:
            task: The ReactTask to execute

        Yields:
            Stream events for each recursion cycle

        Raises:
            asyncio.CancelledError: If the task is cancelled by client disconnect
        """
        # Initialize messages with system placeholder first (will be filled in first recursion)
        # System message MUST be at index 0 for most LLMs
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": ""},  # Placeholder, updated each recursion
            {"role": "user", "content": task.user_message},
        ]

        # Load session memory if session_id is provided
        session_memory_dict: dict[str, Any] | None = None
        if task.session_id:
            session_service = SessionMemoryService(self.db)
            session_memory_dict = session_service.get_full_session_memory_dict(
                task.session_id
            )
            # Update chat history with user input
            session_service.update_chat_history(
                task.session_id, "user", task.user_message
            )

        # Update task status
        task.status = "running"
        task.updated_at = datetime.now(timezone.utc)
        self.db.commit()

        try:
            while task.iteration < task.max_iteration:
                # Check if task was cancelled
                if self.cancelled:
                    logger.info(f"Task {task.task_id} cancelled, exiting loop")
                    task.status = "cancelled"
                    task.updated_at = datetime.now(timezone.utc)
                    self.db.commit()
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

                # Execute recursion
                recursion, event_data = await self.execute_recursion(
                    task, context, messages, session_memory_dict
                )

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
                action_type = event_data.get("action_type", "")
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
                            session_memory_delta=event_data.get("session_memory_delta", {}),
                            session_subject=event_data.get("session_subject", {}),
                            session_object=event_data.get("session_object", {}),
                            agent_answer=answer_output.get("answer", ""),
                            task_summary=event_data.get("task_summary", {}),
                        )

                    # Task complete
                    task.status = "completed"
                    task.updated_at = datetime.now(timezone.utc)
                    self.db.commit()

                    yield {
                        "type": "task_complete",
                        "task_id": task.task_id,
                        "iteration": task.iteration,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "total_tokens": {
                            "prompt_tokens": task.total_prompt_tokens,
                            "completion_tokens": task.total_completion_tokens,
                            "total_tokens": task.total_tokens,
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

                    # Increment iteration and continue (retry)
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

            yield {
                "type": "error",
                "task_id": task.task_id,
                "iteration": task.iteration,
                "data": {"error": str(e)},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
