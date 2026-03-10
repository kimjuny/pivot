"""Integration-style tests for ReAct state persistence service."""

import json
import sys
import unittest
from importlib import import_module
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine, select

# The backend code imports from the ``app`` package root. unittest discovery
# does not add ``server/`` to sys.path automatically, so tests do it explicitly.
SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

import_module("app.models.llm")
Agent = import_module("app.models.agent").Agent
ReactPlanStep = import_module("app.models.react").ReactPlanStep
ReactRecursion = import_module("app.models.react").ReactRecursion
ReactRecursionState = import_module("app.models.react").ReactRecursionState
ReactTask = import_module("app.models.react").ReactTask
ReactStateService = import_module("app.services.react_state_service").ReactStateService


class ReactStateServiceTestCase(unittest.TestCase):
    """Validate recursion, plan, and snapshot persistence behavior."""

    def setUp(self) -> None:
        """Create an isolated in-memory database per test."""
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)

        agent = Agent(name="agent-1", llm_id=None)
        self.session.add(agent)
        self.session.commit()
        self.session.refresh(agent)

        self.task = ReactTask(
            task_id="task-1",
            agent_id=agent.id or 0,
            user="alice",
            user_message="hello",
            user_intent="hello",
        )
        self.session.add(self.task)
        self.session.commit()
        self.session.refresh(self.task)

        self.service = ReactStateService(self.session)

    def tearDown(self) -> None:
        """Close the session after each test."""
        self.session.close()

    def test_finalize_success_replan_persists_plan_and_snapshot(self) -> None:
        """RE_PLAN should replace plan rows and write a snapshot."""
        context = self.service.load_context(self.task)
        context.update_for_new_recursion("trace-1")
        recursion = self.service.start_recursion(self.task, "trace-1")

        tokens = self.service.finalize_success(
            task=self.task,
            recursion=recursion,
            context=context,
            observe="observe",
            thinking="provider thinking",
            thought="thought",
            abstract="abstract",
            action_type="RE_PLAN",
            action_output={
                "plan": [
                    {
                        "step_id": "1",
                        "general_goal": "Goal",
                        "specific_description": "Do work",
                        "completion_criteria": "Done",
                        "status": "pending",
                    }
                ]
            },
            action_step_id=None,
            step_status_updates=[],
            progress_update="",
            tool_results=[],
            token_counter={
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
                "cached_input_tokens": 2,
            },
        )

        self.session.refresh(self.task)
        self.session.refresh(recursion)
        plan_steps = self.session.exec(
            select(ReactPlanStep).where(ReactPlanStep.task_id == self.task.task_id)
        ).all()
        snapshot = self.session.exec(
            select(ReactRecursionState).where(
                ReactRecursionState.trace_id == recursion.trace_id
            )
        ).one()
        snapshot_payload = json.loads(snapshot.current_state)

        self.assertEqual(tokens["total_tokens"], 15)  # type: ignore[index]
        self.assertEqual(self.task.total_tokens, 15)
        self.assertEqual(recursion.status, "done")
        self.assertEqual(recursion.thinking, "provider thinking")
        self.assertEqual(len(plan_steps), 1)
        self.assertEqual(plan_steps[0].step_id, "1")
        self.assertEqual(snapshot_payload["context"]["plan"][0]["step_id"], "1")

    def test_finalize_success_call_tool_updates_step_and_snapshot(self) -> None:
        """CALL_TOOL should persist step updates, memory, and enriched snapshot data."""
        existing_step = ReactPlanStep(
            task_id=self.task.task_id,
            react_task_id=self.task.id or 0,
            step_id="1",
            general_goal="Goal",
            specific_description="Do work",
            completion_criteria="Done",
            status="pending",
        )
        self.session.add(existing_step)
        self.session.commit()

        context = self.service.load_context(self.task)
        context.update_for_new_recursion("trace-2")
        recursion = self.service.start_recursion(self.task, "trace-2")

        self.service.finalize_success(
            task=self.task,
            recursion=recursion,
            context=context,
            observe="observe",
            thinking=None,
            thought="thought",
            abstract="abstract",
            action_type="CALL_TOOL",
            action_output={
                "tool_calls": [
                    {
                        "id": "call-1",
                        "name": "read_file",
                        "arguments": {"path": "/tmp/demo.txt"},
                    }
                ]
            },
            action_step_id="1",
            step_status_updates=[{"step_id": "1", "status": "done"}],
            progress_update="Working through the file analysis",
            tool_results=[
                {
                    "tool_call_id": "call-1",
                    "name": "read_file",
                    "arguments": {"path": "/tmp/demo.txt"},
                    "result": "hello",
                    "success": True,
                }
            ],
            token_counter={},
        )

        self.session.refresh(recursion)
        updated_step = self.session.exec(
            select(ReactPlanStep).where(ReactPlanStep.task_id == self.task.task_id)
        ).one()
        snapshot = self.session.exec(
            select(ReactRecursionState).where(
                ReactRecursionState.trace_id == recursion.trace_id
            )
        ).one()
        snapshot_payload = json.loads(snapshot.current_state)
        plan_entry = snapshot_payload["context"]["plan"][0]
        rec_entry = plan_entry["recursion_history"][0]

        self.assertEqual(updated_step.status, "done")
        self.assertEqual(recursion.plan_step_id, "1")
        self.assertIsNotNone(recursion.tool_call_results)
        self.assertEqual(recursion.progress_update, "Working through the file analysis")
        self.assertEqual(
            rec_entry["progress_update"],
            "Working through the file analysis",
        )
        self.assertEqual(
            rec_entry["action"]["output"]["tool_calls"][0]["result"], "hello"
        )
        self.assertTrue(rec_entry["action"]["output"]["tool_calls"][0]["success"])

    def test_finalize_error_and_task_lifecycle_helpers(self) -> None:
        """Error finalization and lifecycle helpers should persist task state."""
        recursion = self.service.start_recursion(self.task, "trace-3")
        tokens = self.service.finalize_error(
            task=self.task,
            recursion=recursion,
            error_log="boom",
            token_counter={
                "prompt_tokens": 2,
                "completion_tokens": 1,
                "total_tokens": 3,
                "cached_input_tokens": 0,
            },
        )

        self.session.refresh(self.task)
        self.session.refresh(recursion)
        self.assertEqual(tokens["total_tokens"], 3)  # type: ignore[index]
        self.assertEqual(recursion.status, "error")
        self.assertEqual(recursion.error_log, "boom")
        self.assertEqual(self.task.total_tokens, 3)

        self.service.mark_running(self.task)
        self.assertEqual(self.task.status, "running")
        self.service.advance_iteration(self.task)
        self.assertEqual(self.task.iteration, 1)
        self.service.mark_failed(self.task)
        self.assertEqual(self.task.status, "failed")


if __name__ == "__main__":
    unittest.main()
