"""Unit tests for clarify-resume behavior in the ReAct task supervisor."""

import asyncio
import json
import sys
import unittest
from importlib import import_module
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlmodel import Session as DBSession, SQLModel, create_engine

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

Agent = import_module("app.models.agent").Agent
ReactTask = import_module("app.models.react").ReactTask
SessionModel = import_module("app.models.session").Session
User = import_module("app.models.user").User
ReactTaskLaunchRequest = import_module(
    "app.services.react_task_supervisor"
).ReactTaskLaunchRequest
ReactTaskSupervisor = import_module(
    "app.services.react_task_supervisor"
).ReactTaskSupervisor
_should_run_skill_resolution = import_module(
    "app.services.react_task_supervisor"
)._should_run_skill_resolution
react_task_supervisor_module = import_module("app.services.react_task_supervisor")


class ReactTaskSupervisorTestCase(unittest.TestCase):
    """Validate clarify-resume launch behavior."""

    def setUp(self) -> None:
        """Create an isolated in-memory database for launch tests."""
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.session = DBSession(self.engine)

        agent = Agent(name="agent-1", llm_id=1)
        self.session.add(agent)
        self.session.commit()
        self.session.refresh(agent)
        self.agent = agent

        user = User(username="alice", password_hash="hash")
        self.session.add(user)
        self.session.commit()

        session = SessionModel(
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
        self.get_engine_patch = patch.object(
            react_task_supervisor_module,
            "get_engine",
            return_value=self.engine,
        )
        self.get_engine_patch.start()
        self.supervisor = ReactTaskSupervisor()

    def tearDown(self) -> None:
        """Release the in-memory database after each test."""
        self.get_engine_patch.stop()
        self.session.close()

    def test_runs_skill_resolution_for_new_task(self) -> None:
        """Fresh tasks should keep the pre-task skill matcher enabled."""
        agent = Agent(name="agent-1", llm_id=1, skill_resolution_llm_id=2)
        task = ReactTask(
            task_id="task-1",
            agent_id=1,
            user="alice",
            user_message="Help me",
            user_intent="Help me",
            status="pending",
            iteration=0,
        )

        self.assertTrue(_should_run_skill_resolution(task=task, agent=agent))

    def test_skips_skill_resolution_for_waiting_input_resume(self) -> None:
        """Clarify resumes should continue the task instead of matching skills again."""
        agent = Agent(name="agent-1", llm_id=1, skill_resolution_llm_id=2)
        task = ReactTask(
            task_id="task-clarify",
            agent_id=1,
            user="alice",
            user_message="Help me export",
            user_intent="Help me export",
            status="waiting_input",
            iteration=1,
        )

        self.assertFalse(_should_run_skill_resolution(task=task, agent=agent))

    def test_prepare_task_updates_session_activity_for_new_turns(self) -> None:
        """Launching a fresh turn should let the backend own sidebar ordering."""
        session = self.session.get(SessionModel, 1)
        if session is None:
            self.fail("Expected persisted session row")

        original_updated_at = session.updated_at
        task, _cursor = self.supervisor._prepare_task(
            db=self.session,
            launch=ReactTaskLaunchRequest(
                agent_id=self.agent.id or 0,
                message="Start fresh work",
                username="alice",
                session_id="session-1",
                file_ids=[],
            ),
        )

        refreshed_session = self.session.get(SessionModel, session.id)
        if refreshed_session is None:
            self.fail("Expected refreshed session row")

        self.assertEqual(task.session_id, "session-1")
        self.assertGreater(refreshed_session.updated_at, original_updated_at)

    def test_prepare_task_rejects_text_reply_for_structured_pending_action(self) -> None:
        """Structured waiting actions should not be resumable through freeform text."""
        task = ReactTask(
            task_id="task-approval",
            session_id="session-1",
            agent_id=self.agent.id or 0,
            user="alice",
            user_message="Build a skill",
            user_intent="Build a skill",
            status="waiting_input",
            iteration=1,
            pending_user_action_json=json.dumps(
                {
                    "kind": "skill_change_approval",
                    "approval_request": {
                        "submission_id": 42,
                        "skill_name": "planning-kit",
                        "change_type": "create",
                        "question": "Approve?",
                    },
                }
            ),
        )
        self.session.add(task)
        self.session.commit()

        with self.assertRaisesRegex(ValueError, "structured user action"):
            self.supervisor._prepare_task(
                db=self.session,
                launch=ReactTaskLaunchRequest(
                    agent_id=self.agent.id or 0,
                    message="Approve it",
                    username="alice",
                    session_id="session-1",
                    file_ids=[],
                    task_id="task-approval",
                ),
            )

    def test_submit_pending_user_action_resumes_task_with_structured_result(self) -> None:
        """Approving one waiting action should enqueue a structured action_result."""
        task = ReactTask(
            task_id="task-approval",
            session_id="session-1",
            agent_id=self.agent.id or 0,
            user="alice",
            user_message="Build a skill",
            user_intent="Build a skill",
            status="waiting_input",
            iteration=1,
            pending_user_action_json=json.dumps(
                {
                    "kind": "skill_change_approval",
                    "approval_request": {
                        "submission_id": 42,
                        "skill_name": "planning-kit",
                        "change_type": "create",
                        "question": "Approve?",
                    },
                }
            ),
        )
        self.session.add(task)
        self.session.commit()

        with patch.object(
            react_task_supervisor_module,
            "apply_skill_change_submission",
            return_value={
                "submission_id": 42,
                "skill_name": "planning-kit",
                "status": "applied",
                "message": "Applied private skill 'planning-kit'.",
            },
        ), patch.object(
            self.supervisor,
            "_run_task",
            new=AsyncMock(return_value=None),
        ):
            launch_result = asyncio.run(
                self.supervisor.submit_pending_user_action(
                    task_id="task-approval",
                    username="alice",
                    decision="approve",
                )
            )

        refreshed_task = self.session.get(ReactTask, task.id)
        refreshed_session = self.session.get(SessionModel, 1)
        if refreshed_task is None or refreshed_session is None:
            self.fail("Expected refreshed task and session rows")

        pending_action_result = json.loads(
            refreshed_session.react_pending_action_result or "null"
        )
        self.assertEqual(launch_result.task_id, "task-approval")
        self.assertEqual(refreshed_task.status, "pending")
        self.assertEqual(
            pending_action_result,
            [
                {
                    "result": {
                        "kind": "skill_change_result",
                        "decision": "approve",
                        "submission_id": 42,
                        "skill_name": "planning-kit",
                        "status": "applied",
                        "message": "Applied private skill 'planning-kit'.",
                    }
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
