"""Unit tests for snapshot-first ReAct context loading."""

import sys
import unittest
from importlib import import_module
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

# The backend code imports from the ``app`` package root. unittest discovery
# does not add ``server/`` to sys.path automatically, so tests do it explicitly.
SERVER_ROOT = Path(__file__).resolve().parents[3]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

import_module("app.models.llm")
Agent = import_module("app.models.agent").Agent
ReactPlanStep = import_module("app.models.react").ReactPlanStep
ReactTask = import_module("app.models.react").ReactTask
ReactContext = import_module("app.orchestration.react.context").ReactContext
ReactStateService = import_module("app.services.react_state_service").ReactStateService


class ReactContextTestCase(unittest.TestCase):
    """Validate snapshot-first context reconstruction behavior."""

    def setUp(self) -> None:
        """Create an isolated in-memory database per test."""
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)

        agent = Agent(name="agent-ctx", llm_id=None)
        self.session.add(agent)
        self.session.commit()
        self.session.refresh(agent)

        self.task = ReactTask(
            task_id="task-ctx",
            agent_id=agent.id or 0,
            user="alice",
            user_message="hello",
            user_intent="hello",
        )
        self.session.add(self.task)
        self.session.commit()
        self.session.refresh(self.task)

        self.state_service = ReactStateService(self.session)

    def tearDown(self) -> None:
        """Close the session after each test."""
        self.session.close()

    def test_from_task_uses_latest_snapshot_but_refreshes_global_state(self) -> None:
        """Snapshot data should drive context, while live task metadata stays current."""
        context = self.state_service.load_context(self.task)
        context.update_for_new_recursion("trace-1")
        recursion = self.state_service.start_recursion(self.task, "trace-1")
        self.state_service.finalize_success(
            task=self.task,
            recursion=recursion,
            context=context,
            observe="observe",
            thinking=None,
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
            token_counter={},
        )

        self.task.iteration = 3
        self.task.status = "waiting_input"
        self.session.add(self.task)
        self.session.commit()
        self.session.refresh(self.task)

        loaded = ReactContext.from_task(self.task, self.session)

        self.assertEqual(loaded.global_state["iteration"], 3)
        self.assertEqual(loaded.global_state["status"], "waiting_input")
        self.assertEqual(loaded.current_recursion["iteration_index"], 3)
        self.assertEqual(loaded.context["plan"][0]["step_id"], "1")

    def test_from_task_falls_back_to_plan_rows_without_snapshot(self) -> None:
        """Tasks without snapshots should still expose persisted plan steps."""
        step = ReactPlanStep(
            task_id=self.task.task_id,
            react_task_id=self.task.id or 0,
            step_id="1",
            general_goal="Goal",
            specific_description="Do work",
            completion_criteria="Done",
            status="running",
        )
        self.session.add(step)
        self.session.commit()

        loaded = ReactContext.from_task(self.task, self.session)

        self.assertEqual(loaded.global_state["task_id"], self.task.task_id)
        self.assertEqual(loaded.context["plan"][0]["step_id"], "1")
        self.assertEqual(loaded.context["plan"][0]["status"], "running")
        self.assertEqual(loaded.recursion_history, [])


if __name__ == "__main__":
    unittest.main()
