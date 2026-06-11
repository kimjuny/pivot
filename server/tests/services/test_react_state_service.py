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
ReactRecursion = import_module("app.models.react").ReactRecursion
ReactRecursionState = import_module("app.models.react").ReactRecursionState
ReactTask = import_module("app.models.react").ReactTask
SessionModel = import_module("app.models.session").Session
ReactStateService = import_module("app.services.react_state_service").ReactStateService


class ReactStateServiceTestCase(unittest.TestCase):
    """Validate recursion and snapshot persistence behavior."""

    def setUp(self) -> None:
        """Create an isolated in-memory database per test."""
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)

        agent = Agent(name="agent-1", llm_id=None)
        self.session.add(agent)
        self.session.commit()
        self.session.refresh(agent)

        self.session.add(
            SessionModel(
                session_id="session-1",
                agent_id=agent.id or 0,
                user="alice",
                chat_history=json.dumps({"version": 1, "messages": []}),
                react_llm_messages="[]",
                react_llm_cache_state="{}",
            )
        )
        self.session.commit()

        self.task = ReactTask(
            task_id="task-1",
            session_id="session-1",
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

    def test_finalize_success_call_tool_persists_snapshot(self) -> None:
        """CALL_TOOL should persist tool results, memory, and enriched snapshot data."""
        context = self.service.load_context(self.task)
        context.update_for_new_recursion("trace-2")
        recursion = self.service.start_recursion(
            self.task,
            "trace-2",
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
        self.service.record_llm_decision(
            task=self.task,
            recursion=recursion,
            thinking=None,
            action_type="CALL_TOOL",
            action_output=action_output,
            message="Working through the file analysis",
            token_counter={},
        )
        self.session.refresh(recursion)
        self.assertEqual(recursion.status, "running")
        self.assertEqual(recursion.action_type, "CALL_TOOL")
        self.assertIsNone(recursion.tool_call_results)

        self.service.finalize_success(
            task=self.task,
            recursion=recursion,
            context=context,
            action_type="CALL_TOOL",
            action_output=action_output,
            message="Working through the file analysis",
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

        self.session.refresh(recursion)
        snapshot = self.session.exec(
            select(ReactRecursionState).where(
                ReactRecursionState.trace_id == recursion.trace_id
            )
        ).one()
        snapshot_payload = json.loads(snapshot.current_state)
        rec_entry = snapshot_payload["recursion_history"][0]

        self.assertIsNotNone(recursion.tool_call_results)
        self.assertEqual(recursion.message, "Working through the file analysis")
        self.assertEqual(
            rec_entry["message"],
            "Working through the file analysis",
        )
        self.assertEqual(
            rec_entry["action"]["output"]["tool_calls"][0]["result"], "hello"
        )
        self.assertTrue(rec_entry["action"]["output"]["tool_calls"][0]["success"])

    def test_finalize_error_and_task_lifecycle_helpers(self) -> None:
        """Error finalization and lifecycle helpers should persist task state."""
        recursion = self.service.start_recursion(
            self.task,
            "trace-3",
            {"role": "user", "content": "{}"},
        )
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

    def test_task_status_helpers_sync_session_runtime_status(self) -> None:
        """Session runtime status should track the task lifecycle helpers."""
        session = self.session.exec(
            select(SessionModel).where(SessionModel.session_id == "session-1")
        ).one()

        self.assertEqual(session.runtime_status, "idle")

        self.service.mark_running(self.task)
        self.session.refresh(session)
        self.assertEqual(session.runtime_status, "running")

        self.service.mark_completed(self.task)
        self.session.refresh(session)
        self.assertEqual(session.runtime_status, "idle")


if __name__ == "__main__":
    unittest.main()
