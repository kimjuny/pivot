"""ReAct context loading utilities built around persisted snapshots."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from app.models.react import ReactPlanStep, ReactRecursionState, ReactTask
from sqlmodel import Session, desc, select

logger = logging.getLogger(__name__)


@dataclass
class ReactContext:
    """Dynamic state machine context for ReAct execution.

    This class represents the complete state of a ReAct task execution,
    following the structure defined in context_template.md.

    Attributes:
        global_state: Global task information (task_id, iteration, status, etc.)
        current_recursion: Current recursion state (trace_id, status, etc.)
        context: Task context including user_intent, constraints, plan, and memory
        recursion_history: History of previous recursions
    """

    global_state: dict[str, Any]
    current_recursion: dict[str, Any]
    context: dict[str, Any]
    recursion_history: list[dict[str, Any]]

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
            "recursion_history": self.recursion_history,
        }

    @classmethod
    def from_task(cls, task: ReactTask, db: Session) -> ReactContext:
        """
        Create ReactContext from a database task.

        Args:
            task: The ReactTask to load context from
            db: Database session for loading related data

        Returns:
            ReactContext instance initialized with task data
        """
        latest_state_stmt = (
            select(ReactRecursionState)
            .where(ReactRecursionState.task_id == task.task_id)
            .order_by(desc(ReactRecursionState.iteration_index))
        )
        latest_state = db.exec(latest_state_stmt).first()

        if latest_state and latest_state.current_state:
            snapshot_context = cls._from_snapshot_payload(
                task=task,
                snapshot_payload=latest_state.current_state,
            )
            if snapshot_context is not None:
                return snapshot_context

        return cls._build_fallback_context(task, db)

    @classmethod
    def _from_snapshot_payload(
        cls,
        task: ReactTask,
        snapshot_payload: str,
    ) -> ReactContext | None:
        """Build context from the latest persisted snapshot.

        Args:
            task: Live task row whose metadata should override snapshot globals.
            snapshot_payload: Serialized snapshot JSON.

        Returns:
            A reconstructed context when the snapshot is valid, otherwise `None`.
        """
        try:
            parsed_snapshot = json.loads(snapshot_payload)
        except json.JSONDecodeError:
            logger.warning(
                "Invalid recursion snapshot JSON detected; falling back to minimal context. task_id=%s",
                task.task_id,
            )
            return None

        if not isinstance(parsed_snapshot, dict):
            logger.warning(
                "Invalid recursion snapshot payload type; falling back to minimal context. task_id=%s",
                task.task_id,
            )
            return None

        raw_context = parsed_snapshot.get("context")
        context_dict = (
            cls._normalize_context_dict(task, raw_context)
            if isinstance(raw_context, dict)
            else cls._default_context_dict(task)
        )

        raw_recursion_history = parsed_snapshot.get("recursion_history")
        recursion_history = (
            raw_recursion_history if isinstance(raw_recursion_history, list) else []
        )

        return cls(
            global_state=cls._build_global_state(task),
            current_recursion=cls._build_current_recursion(task),
            context=context_dict,
            recursion_history=recursion_history,
        )

    @classmethod
    def _build_fallback_context(cls, task: ReactTask, db: Session) -> ReactContext:
        """Build a minimal context when no valid snapshot exists.

        Args:
            task: Task whose fallback context should be built.
            db: Database session used to load plan steps.

        Returns:
            A minimal but valid ReAct context.
        """
        plan_steps_stmt = (
            select(ReactPlanStep)
            .where(ReactPlanStep.task_id == task.task_id)
            .order_by(ReactPlanStep.step_id)
        )
        plan_steps = db.exec(plan_steps_stmt).all()

        context_dict = cls._default_context_dict(task)
        for step in plan_steps:
            context_dict["plan"].append(
                {
                    "step_id": step.step_id,
                    "general_goal": step.general_goal,
                    "specific_description": step.specific_description,
                    "completion_criteria": step.completion_criteria,
                    "status": step.status,
                    "recursion_history": [],
                }
            )

        return cls(
            global_state=cls._build_global_state(task),
            current_recursion=cls._build_current_recursion(task),
            context=context_dict,
            recursion_history=[],
        )

    @staticmethod
    def _build_global_state(task: ReactTask) -> dict[str, Any]:
        """Build the live global-state section from the task row.

        Args:
            task: Task whose current metadata should be serialized.

        Returns:
            The global-state dictionary.
        """
        return {
            "task_id": task.task_id,
            "iteration": task.iteration,
            "max_iteration": task.max_iteration,
            "status": task.status,
            "created_at": task.created_at.isoformat(),
            "updated_at": task.updated_at.isoformat(),
        }

    @staticmethod
    def _build_current_recursion(task: ReactTask) -> dict[str, Any]:
        """Build the pending current-recursion section for the next loop.

        Args:
            task: Task whose current iteration should seed the recursion state.

        Returns:
            The current-recursion dictionary.
        """
        return {
            "trace_id": "",
            "iteration_index": task.iteration,
            "status": "pending",
        }

    @staticmethod
    def _default_context_dict(task: ReactTask) -> dict[str, Any]:
        """Build the minimal default context section.

        Args:
            task: Task whose intent seeds the context.

        Returns:
            A default context dictionary with empty plan and memory.
        """
        return {
            "user_intent": task.user_intent,
            "constraints": [],
            "plan": [],
            "memory": {"short_term": []},
        }

    @classmethod
    def _normalize_context_dict(
        cls,
        task: ReactTask,
        raw_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Normalize snapshot context to a stable minimum shape.

        Args:
            task: Task whose live user_intent should be authoritative.
            raw_context: Raw context object from the persisted snapshot.

        Returns:
            A normalized context dictionary.
        """
        normalized = cls._default_context_dict(task)
        user_intent = raw_context.get("user_intent")
        if isinstance(user_intent, str) and user_intent:
            normalized["user_intent"] = user_intent

        constraints = raw_context.get("constraints")
        if isinstance(constraints, list):
            normalized["constraints"] = constraints

        plan = raw_context.get("plan")
        if isinstance(plan, list):
            normalized["plan"] = plan

        memory = raw_context.get("memory")
        if isinstance(memory, dict):
            short_term = memory.get("short_term")
            normalized["memory"] = {
                "short_term": short_term if isinstance(short_term, list) else []
            }

        return normalized

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
