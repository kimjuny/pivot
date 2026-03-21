"""Tests for session history plan snapshots."""

import json
import sys
import unittest
from importlib import import_module
from pathlib import Path

from sqlmodel import Session as DBSession, SQLModel, create_engine

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

import_module("app.models.llm")
Agent = import_module("app.models.agent").Agent
ReactPlanStep = import_module("app.models.react").ReactPlanStep
ReactRecursionState = import_module("app.models.react").ReactRecursionState
ReactTask = import_module("app.models.react").ReactTask
Session = import_module("app.models.session").Session
SessionService = import_module("app.services.session_service").SessionService


class SessionServiceTestCase(unittest.TestCase):
    """Validate session history payloads that power the chat UI."""

    def setUp(self) -> None:
        """Create an isolated in-memory database per test."""
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.session = DBSession(self.engine)

        agent = Agent(name="agent-1", llm_id=None)
        self.session.add(agent)
        self.session.commit()
        self.session.refresh(agent)
        self.agent = agent

        session = Session(
            session_id="session-1",
            agent_id=agent.id or 0,
            user="alice",
            chat_history=json.dumps({"version": 1, "messages": []}),
            react_llm_messages="[]",
            react_llm_cache_state="{}",
        )
        self.session.add(session)
        self.session.commit()
        self.session.refresh(session)

        self.service = SessionService(self.session)

    def tearDown(self) -> None:
        """Close the session after each test."""
        self.session.close()

    def test_full_history_uses_latest_snapshot_current_plan(self) -> None:
        """History payload should expose the latest persisted current-plan snapshot."""
        task = ReactTask(
            task_id="task-1",
            session_id="session-1",
            agent_id=self.agent.id or 0,
            user="alice",
            user_message="Inspect the repo",
            user_intent="Inspect the repo",
            status="running",
        )
        self.session.add(task)
        self.session.commit()
        self.session.refresh(task)

        snapshot = ReactRecursionState(
            trace_id="trace-1",
            task_id=task.task_id,
            iteration_index=2,
            current_state=json.dumps(
                {
                    "global": {"task_id": task.task_id},
                    "current_recursion": {},
                    "context": {
                        "plan": [
                            {
                                "step_id": "1",
                                "general_goal": "Inspect the repository",
                                "specific_description": "Review the current files",
                                "completion_criteria": "Context is collected",
                                "status": "done",
                                "recursion_history": [
                                    {
                                        "iteration": 2,
                                        "summary": "Repository inspection is complete",
                                    }
                                ],
                            },
                            {
                                "step_id": "2",
                                "general_goal": "Ship the fix",
                                "specific_description": "Patch the bug",
                                "completion_criteria": "Change is merged",
                                "status": "running",
                                "recursion_history": [],
                            },
                        ]
                    },
                    "recursion_history": [],
                },
                ensure_ascii=False,
            ),
        )
        self.session.add(snapshot)
        self.session.commit()

        history = self.service.get_full_session_history("session-1")

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["current_plan"][0]["status"], "done")
        self.assertEqual(history[0]["current_plan"][1]["status"], "running")
        self.assertEqual(
            history[0]["current_plan"][0]["recursion_history"][0]["summary"],
            "Repository inspection is complete",
        )

    def test_full_history_falls_back_to_plan_rows_without_snapshot(self) -> None:
        """Plan rows should still surface when no snapshot has been written yet."""
        task = ReactTask(
            task_id="task-2",
            session_id="session-1",
            agent_id=self.agent.id or 0,
            user="alice",
            user_message="Plan the work",
            user_intent="Plan the work",
            status="running",
        )
        self.session.add(task)
        self.session.commit()
        self.session.refresh(task)

        self.session.add(
            ReactPlanStep(
                task_id=task.task_id,
                react_task_id=task.id or 0,
                step_id="1",
                general_goal="Inspect the repository",
                specific_description="Review the current files",
                completion_criteria="Context is collected",
                status="pending",
            )
        )
        self.session.commit()

        history = self.service.get_full_session_history("session-1")

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["current_plan"][0]["step_id"], "1")
        self.assertEqual(history[0]["current_plan"][0]["status"], "pending")
        self.assertEqual(history[0]["current_plan"][0]["recursion_history"], [])

    def test_update_session_metadata_does_not_pin_when_only_renaming(self) -> None:
        """Renaming a session should not implicitly toggle its pin state."""
        before = self.service.get_session("session-1")
        if before is None:
            self.fail("Expected session-1 to exist")

        original_updated_at = before.updated_at
        updated_session = self.service.update_session_metadata(
            "session-1",
            title="Renamed thread",
        )

        if updated_session is None:
            self.fail("Expected renamed session row")

        self.assertEqual(updated_session.title, "Renamed thread")
        self.assertFalse(updated_session.is_pinned)
        self.assertGreater(updated_session.updated_at, original_updated_at)

    def test_update_session_metadata_only_changes_pin_when_requested(self) -> None:
        """Pin toggles should remain explicit so sidebar actions stay predictable."""
        updated_session = self.service.update_session_metadata(
            "session-1",
            is_pinned=True,
        )

        if updated_session is None:
            self.fail("Expected pinned session row")

        self.assertTrue(updated_session.is_pinned)
