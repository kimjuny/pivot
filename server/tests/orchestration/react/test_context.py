"""Unit tests for snapshot-first ReAct context loading."""

import json
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
ReactTask = import_module("app.models.react").ReactTask
ReactRecursionState = import_module("app.models.react").ReactRecursionState
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
        recursion = self.state_service.start_recursion(
            self.task,
            "trace-1",
            {"role": "user", "content": "{}"},
        )
        action_output = {
            "tool_calls": [
                {
                    "id": "call-1",
                    "name": "read_file",
                    "arguments": {"path": "/tmp/demo.txt"},
                }
            ]
        }
        self.state_service.record_llm_decision(
            task=self.task,
            recursion=recursion,
            thinking=None,
            action_type="CALL_TOOL",
            action_output=action_output,
            message="",
            token_counter={},
        )
        self.state_service.finalize_success(
            task=self.task,
            recursion=recursion,
            context=context,
            action_type="CALL_TOOL",
            action_output=action_output,
            message="",
            tool_results=[
                {
                    "tool_call_id": "call-1",
                    "name": "read_file",
                    "arguments": {"path": "/tmp/demo.txt"},
                    "result": "hello",
                    "success": True,
                }
            ],
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
        self.assertEqual(loaded.context["user_intent"], "hello")

    def test_from_task_falls_back_to_minimal_context_without_snapshot(self) -> None:
        """Tasks without snapshots should still expose a valid minimal context."""
        loaded = ReactContext.from_task(self.task, self.session)

        self.assertEqual(loaded.global_state["task_id"], self.task.task_id)
        self.assertEqual(loaded.context["user_intent"], "hello")
        self.assertEqual(loaded.context["constraints"], [])
        self.assertEqual(loaded.recursion_history, [])

    def test_from_task_preserves_constraints_from_snapshot(self) -> None:
        """Snapshot constraints should survive context reconstruction."""
        snapshot = ReactRecursionState(
            trace_id="trace-snap",
            task_id=self.task.task_id,
            iteration_index=1,
            current_state=json.dumps(
                {
                    "global": {"task_id": self.task.task_id},
                    "current_recursion": {},
                    "context": {
                        "user_intent": "Build the feature",
                        "constraints": ["No external APIs", "Must be fast"],
                    },
                    "recursion_history": [],
                },
                ensure_ascii=False,
            ),
        )
        self.session.add(snapshot)
        self.session.commit()

        loaded = ReactContext.from_task(self.task, self.session)

        self.assertEqual(loaded.context["user_intent"], "Build the feature")
        self.assertEqual(
            loaded.context["constraints"], ["No external APIs", "Must be fast"]
        )


if __name__ == "__main__":
    unittest.main()
