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
        last_recursion: Previous recursion's output (observe, thought, action)
    """

    global_state: dict[str, Any]
    current_recursion: dict[str, Any]
    context: dict[str, Any]
    last_recursion: dict[str, Any] | None = None

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
            "last_recursion": self.last_recursion,
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
            "memory": {"short_term": [], "long_term_refs": []},
        }

        # Add plan steps to context
        for step in plan_steps:
            plan_step = {
                "step_id": step.step_id,
                "description": step.description,
                "status": step.status,
                "recursions": [],
            }

            # Find recursions associated with this step (by matching in action_output)
            for rec in recursions:
                if rec.status in ["done", "error"]:
                    recursion_entry = {
                        "trace_id": rec.trace_id,
                        "status": rec.status,
                        "result": rec.action_output if rec.status == "done" else "",
                        "error_log": rec.error_log if rec.status == "error" else None,
                    }
                    plan_step["recursions"].append(recursion_entry)

            context_dict["plan"].append(plan_step)

        # Build last recursion from most recent completed recursion
        last_recursion = None
        if recursions:
            latest = recursions[-1]
            if latest.status in ["done", "error"]:
                last_recursion_dict: dict[str, Any] = {
                    "trace_id": latest.trace_id,
                    "observe": latest.observe or "",
                    "thought": latest.thought or "",
                    "action": {
                        "result": {
                            "action_type": latest.action_type or "",
                            "output": (
                                json.loads(latest.action_output)
                                if latest.action_output
                                else {}
                            ),
                        }
                    },
                }

                # Add tool_call_results if this was a CALL_TOOL action
                if latest.action_type == "CALL_TOOL" and latest.tool_call_results:
                    tool_results = json.loads(latest.tool_call_results)
                    last_recursion_dict["tool_call_results"] = tool_results

                last_recursion = last_recursion_dict

        return cls(
            global_state=global_state,
            current_recursion=current_recursion,
            context=context_dict,
            last_recursion=last_recursion,
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
