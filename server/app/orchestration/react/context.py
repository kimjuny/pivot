"""ReAct Context management for maintaining state machine state.

This module provides the ReactContext class which represents the dynamic state
machine as described in context_template.md.
"""

import json
from dataclasses import dataclass
from typing import Any

from app.models.react import ReactPlanStep, ReactRecursion, ReactTask
from sqlmodel import Session, select


@dataclass
class ReactContext:
    """Dynamic state machine context for ReAct execution.

    This class represents the complete state of a ReAct task execution,
    following the structure defined in context_template.md.

    Attributes:
        global_state: Global task information (task_id, iteration, status, etc.)
        current_recursion: Current recursion state (trace_id, status, etc.)
        context: Task context including objective, constraints, plan, and memory
        recursions: History of previous recursions
    """

    global_state: dict[str, Any]
    current_recursion: dict[str, Any]
    context: dict[str, Any]
    recursions: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize context to dictionary for JSON serialization.

        Returns:
            Dictionary representation of the complete state machine.
        """
        return {
            "global": self.global_state,
            "current_recursion": self.current_recursion,
            "context": self.context,
            "recursions": self.recursions,
        }

    @classmethod
    def from_task(cls, task: ReactTask, db: Session) -> "ReactContext":
        """
        Create ReactContext from a database task.

        Args:
            task: The ReactTask to load context from
            db: Database session for loading related data

        Returns:
            ReactContext instance initialized with task data
        """
        # Load all recursions for this task
        recursions_stmt = (
            select(ReactRecursion)
            .where(ReactRecursion.task_id == task.task_id)
            .order_by(ReactRecursion.iteration_index)
        )
        recursions = db.exec(recursions_stmt).all()

        # Load plan steps
        plan_steps_stmt = (
            select(ReactPlanStep)
            .where(ReactPlanStep.task_id == task.task_id)
            .order_by(ReactPlanStep.step_id)
        )
        plan_steps = db.exec(plan_steps_stmt).all()

        # Build global state
        global_state = {
            "task_id": task.task_id,
            "iteration": task.iteration,
            "max_iteration": task.max_iteration,
            "status": task.status,
            "created_at": task.created_at.isoformat(),
            "updated_at": task.updated_at.isoformat(),
        }

        # Build current recursion state (will be updated when starting new recursion)
        current_recursion = {
            "trace_id": "",
            "iteration_index": task.iteration,
            "status": "pending",
        }

        # Build context
        context_dict: dict[str, Any] = {
            "objective": task.objective,
            "constraints": [],  # Can be extended
            "plan": [],
            "memory": {"short_term": []},
        }

        # Build short_term memory from recursions
        for rec in recursions:
            if rec.short_term_memory:
                context_dict["memory"]["short_term"].append(
                    {
                        "trace_id": rec.trace_id,
                        "memory": rec.short_term_memory,
                    }
                )

        # Initialize plan steps
        for step in plan_steps:
            plan_step = {
                "step_id": step.step_id,
                "description": step.description,
                "status": step.status,
                "recursions": [],
            }
            context_dict["plan"].append(plan_step)

        # Build recursion history and assign to either plan steps or global list
        recursions_list: list[dict[str, Any]] = []
        for rec in recursions:
            if rec.status in ["done", "error"] or (
                rec.status == "running" and rec.action_type == "CLARIFY"
            ):
                # Careful with JSON decoding errors if data is corrupted
                try:
                    action_output = (
                        json.loads(rec.action_output) if rec.action_output else {}
                    )
                except json.JSONDecodeError:
                    action_output = {}

                rec_dict = {
                    "trace_id": rec.trace_id,
                    "observe": rec.observe or "",
                    "thought": rec.thought or "",
                    "action": {
                        "action_type": rec.action_type or "",
                        "output": action_output,
                    },
                }

                # For CALL_TOOL recursions, merge execution results (result, success)
                # directly into each tool_calls[n] entry.
                if rec.action_type == "CALL_TOOL" and rec.tool_call_results:
                    try:
                        tool_results: list[dict[str, Any]] = json.loads(
                            rec.tool_call_results
                        )
                        result_by_id = {
                            r["tool_call_id"]: r
                            for r in tool_results
                            if "tool_call_id" in r
                        }
                        tool_calls = action_output.get("tool_calls", [])
                        for tc in tool_calls:
                            matched = result_by_id.get(tc.get("id", ""))
                            if matched is not None:
                                tc["result"] = matched.get("result", "")
                                tc["success"] = matched.get("success", False)
                    except json.JSONDecodeError:
                        pass

                # Route to the matching plan step if plan_step_id is provided
                added_to_plan = False
                if rec.plan_step_id:
                    for plan_step in context_dict["plan"]:
                        if plan_step["step_id"] == rec.plan_step_id:
                            plan_step["recursions"].append(rec_dict)
                            added_to_plan = True
                            break
                
                # If it doesn't belong to a plan step (or the step was deleted), 
                # keep it in the top-level recursion list.
                if not added_to_plan:
                    recursions_list.append(rec_dict)

        return cls(
            global_state=global_state,
            current_recursion=current_recursion,
            context=context_dict,
            recursions=recursions_list,
        )

    def update_for_new_recursion(self, trace_id: str) -> None:
        """
        Update context for a new recursion cycle.

        Args:
            trace_id: UUID for the new recursion
        """
        self.current_recursion = {
            "trace_id": trace_id,
            "iteration_index": self.global_state["iteration"],
            "status": "running",
        }
