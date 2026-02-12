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
from app.models.react import ReactPlanStep, ReactRecursion, ReactTask
from app.orchestration.tool.manager import ToolManager
from sqlmodel import Session

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

    async def execute_recursion(
        self, task: ReactTask, context: ReactContext, messages: list[dict[str, Any]]
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

        # Build system prompt with current context and available tools
        system_prompt = build_system_prompt(context, self.tool_manager)

        # Update messages for this recursion
        # messages[0] = user message (fixed)
        # messages[1] = system prompt (updated each recursion)
        if len(messages) < 2:
            messages.append({"role": "system", "content": system_prompt})
        else:
            messages[1] = {"role": "system", "content": system_prompt}

        # Call LLM without tools parameter
        # We rely on the prompt to guide LLM to return JSON format with tool_calls
        # This ensures LLM always returns observe, thought, abstract, and action in JSON
        try:
            response = self.llm.chat(messages=messages, tools=None)  # type: ignore[arg-type]
            choice = response.first()
            message = choice.message

            # Log raw LLM response immediately after receiving it (before any processing)
            logger.info("=" * 80)
            logger.info(f"[ReAct Recursion {trace_id}] >>> LLM RAW RESPONSE START >>>")
            logger.info(f"Raw Input: {json.dumps(messages, ensure_ascii=False, indent=2)}")
            logger.info(f"Message Content Type: {type(message.content)}")
            logger.info(f"Message Content:\n{message.content}")
            logger.info(f"Message Tool Calls: {message.tool_calls}")
            logger.info(f"[ReAct Recursion {trace_id}] <<< LLM RAW RESPONSE END <<<")
            logger.info("=" * 80)

            # LLM should always return JSON format (since tools=None)
            # Parse JSON response from LLM
            if message.tool_calls:
                # This should not happen - log warning and treat as error
                logger.warning(
                    "LLM returned native tool_calls despite tools=None. "
                    "Treating as invalid response."
                )
                recursion.status = "error"
                recursion.error_log = (
                    "LLM returned native tool_calls instead of JSON format"
                )
                recursion.updated_at = datetime.now(timezone.utc)
                self.db.commit()

                return recursion, {
                    "trace_id": trace_id,
                    "action_type": "ERROR",
                    "error": "Invalid response format from LLM",
                }

            else:
                # Parse JSON response from LLM
                content = message.content or "{}"
                react_output = None
                
                try:
                    react_output = json.loads(content)
                except json.JSONDecodeError:
                    # Try to extract JSON from markdown code block
                    if react_output is None and "```json" in content:
                        json_start = content.find("```json") + 7
                        json_end = content.find("```", json_start)
                        json_content = content[json_start:json_end].strip()
                        try:
                            react_output = json.loads(json_content)
                        except json.JSONDecodeError:
                            logger.debug("Failed to parse JSON from markdown block")
                    
                    # If still failed, try to extract JSON from content
                    # LLM might add text before/after JSON
                    if react_output is None:
                        # Find first { and last }
                        first_brace = content.find("{")
                        last_brace = content.rfind("}")
                        
                        if first_brace != -1 and last_brace != -1 and first_brace < last_brace:
                            json_content = content[first_brace:last_brace + 1]
                            try:
                                react_output = json.loads(json_content)
                                logger.info(
                                    f"Successfully extracted JSON from position {first_brace} to {last_brace}"
                                )
                            except json.JSONDecodeError:
                                logger.debug("Failed to parse extracted JSON content")
                
                # If all attempts failed, raise error
                if react_output is None:
                    raise ValueError(
                        f"Failed to parse LLM response: {content}"
                    )

                observe = react_output.get("observe", "")
                thought = react_output.get("thought", "")
                abstract = react_output.get("abstract", "")
                action = react_output.get("action", {}).get("result", {})
                action_type = action.get("action_type", "")
                action_output = action.get("output", {})
                
                # Skip empty/invalid responses
                if not action_type:

                    # Mark recursion as error
                    recursion.status = "error"
                    recursion.error_log = "LLM returned empty action_type"
                    recursion.updated_at = datetime.now(timezone.utc)
                    self.db.commit()
                    
                    return recursion, {
                        "trace_id": trace_id,
                        "action_type": "ERROR",
                        "error": "Empty action_type from LLM",
                    }

                # Handle CALL_TOOL in JSON format
                tool_results = []
                reconstructed_tool_calls = []
                
                if action_type == "CALL_TOOL":
                    tool_calls_data = action_output.get("tool_calls", [])
                    
                    for tool_call_data in tool_calls_data:
                        func_name = ""
                        func_args = {}
                        tool_call_id = f"json-call-{uuid.uuid4()}"
                        
                        try:
                            func_name = tool_call_data.get("function", {}).get("name", "")
                            func_args = tool_call_data.get("function", {}).get("arguments", {})
                            
                            # Execute tool
                            result = self.tool_manager.execute(func_name, **func_args)
                            
                            tool_results.append({
                                "tool_call_id": tool_call_id,
                                "name": func_name,
                                "arguments": func_args,
                                "result": result,
                                "success": True,
                            })
                            
                            # Build tool_call for assistant message
                            reconstructed_tool_calls.append({
                                "id": tool_call_id,
                                "type": "function",
                                "function": {
                                    "name": func_name,
                                    "arguments": json.dumps(func_args),
                                }
                            })
                            
                        except Exception as e:
                            logger.error(f"Tool {func_name} execution failed: {e}")
                            error_msg = f"Tool execution failed: {e!s}"
                            tool_results.append({
                                "tool_call_id": tool_call_id,
                                "name": func_name,
                                "arguments": func_args,
                                "error": error_msg,
                                "success": False,
                            })

                # Save recursion
                recursion.observe = observe
                recursion.thought = thought
                recursion.abstract = abstract
                recursion.action_type = action_type
                recursion.action_output = json.dumps(action_output, ensure_ascii=False)
                
                # Save tool_call_results if any
                if tool_results:
                    tool_results_json = json.dumps(tool_results, ensure_ascii=False)
                    recursion.tool_call_results = tool_results_json
                
                recursion.status = "done"
                recursion.updated_at = datetime.now(timezone.utc)
                self.db.commit()

                # Handle RE_PLAN
                if action_type == "RE_PLAN":
                    plan_data = action_output.get("plan", [])
                    # Delete old plan steps
                    from sqlmodel import delete

                    delete_stmt = delete(ReactPlanStep).where(
                        ReactPlanStep.task_id == task.task_id
                    )
                    self.db.exec(delete_stmt)  # type: ignore[arg-type]

                    # Create new plan steps
                    for step_data in plan_data:
                        step = ReactPlanStep(
                            task_id=task.task_id,
                            react_task_id=task.id or 0,
                            step_id=step_data.get("step_id", ""),
                            description=step_data.get("description", ""),
                            status=step_data.get("status", "pending"),
                        )
                        self.db.add(step)
                    self.db.commit()

                # Do NOT add assistant messages to avoid confusing LLM
                # The state machine injection in next recursion's system prompt
                # will include tool_call_results in last_recursion
                # This is sufficient for LLM to understand what happened
                if action_type == "ANSWER":
                    # For ANSWER, don't add to messages as the task is complete
                    pass
                # For all other action types (CALL_TOOL, RE_PLAN, etc.),
                # we rely on the state machine context to convey the results
                # No need to append to messages

                return recursion, {
                    "trace_id": trace_id,
                    "action_type": action_type,
                    "observe": observe,
                    "thought": thought,
                    "abstract": abstract,
                    "output": action_output,
                    "tool_results": tool_results,  # Add tool_results for streaming
                }

        except Exception as e:
            # Handle errors
            recursion.status = "error"
            recursion.error_log = str(e)
            recursion.updated_at = datetime.now(timezone.utc)
            self.db.commit()

            return recursion, {
                "trace_id": trace_id,
                "action_type": "ERROR",
                "error": str(e),
            }

    async def run_task(
        self, task: ReactTask
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Execute complete ReAct task with streaming events.

        Args:
            task: The ReactTask to execute

        Yields:
            Stream events for each recursion cycle

        Raises:
            asyncio.CancelledError: If the task is cancelled by client disconnect
        """
        # Initialize messages
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": task.user_message}
        ]

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
                    task, context, messages
                )

                # Yield Observe, Thought, Action events
                if recursion.observe:
                    yield {
                        "type": "observe",
                        "task_id": task.task_id,
                        "trace_id": event_data.get("trace_id"),
                        "iteration": task.iteration,
                        "delta": recursion.observe,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }

                if recursion.thought:
                    yield {
                        "type": "thought",
                        "task_id": task.task_id,
                        "trace_id": event_data.get("trace_id"),
                        "iteration": task.iteration,
                        "delta": recursion.thought,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }

                if recursion.abstract:
                    yield {
                        "type": "abstract",
                        "task_id": task.task_id,
                        "trace_id": event_data.get("trace_id"),
                        "iteration": task.iteration,
                        "delta": recursion.abstract,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }

                # Yield action event with type
                action_type = event_data.get("action_type", "")
                yield {
                    "type": "action",
                    "task_id": task.task_id,
                    "trace_id": event_data.get("trace_id"),
                    "iteration": task.iteration,
                    "delta": action_type,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }

                # Yield recursion events
                if action_type == "CALL_TOOL":
                    # Get tool_calls from event_data (could be from native tool_calls or parsed JSON)
                    tool_calls_data = event_data.get("tool_calls", [])
                    tool_results_data = event_data.get("tool_results", [])
                    
                    # If tool_calls is empty but we have tool_results, reconstruct tool_calls
                    # This happens when LLM returns JSON format instead of native tool_calls
                    if not tool_calls_data and tool_results_data:
                        # Reconstruct tool_calls from results
                        tool_calls_data = [
                            {
                                "id": result.get("tool_call_id", ""),
                                "type": "function",
                                "function": {
                                    "name": result.get("name", ""),
                                    "arguments": json.dumps(result.get("arguments", {})),
                                }
                            }
                            for result in tool_results_data
                        ]
                    
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

                elif action_type == "ANSWER":
                    yield {
                        "type": "answer",
                        "task_id": task.task_id,
                        "trace_id": event_data.get("trace_id"),
                        "iteration": task.iteration,
                        "data": event_data.get("output"),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }

                    # Task complete
                    task.status = "completed"
                    task.updated_at = datetime.now(timezone.utc)
                    self.db.commit()

                    yield {
                        "type": "task_complete",
                        "task_id": task.task_id,
                        "iteration": task.iteration,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    break

                elif action_type == "ERROR":
                    yield {
                        "type": "error",
                        "task_id": task.task_id,
                        "iteration": task.iteration,
                        "data": {"error": event_data.get("error", "Unknown error")},
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }

                    task.status = "failed"
                    task.updated_at = datetime.now(timezone.utc)
                    self.db.commit()
                    break

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
