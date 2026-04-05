"""Unit tests for clarify-resume behavior in the ReAct task supervisor."""

import asyncio
import json
import sys
import unittest
from importlib import import_module
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

from sqlmodel import Session as DBSession, SQLModel, create_engine

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

Agent = import_module("app.models.agent").Agent
AgentRelease = import_module("app.models.agent_release").AgentRelease
LLM = import_module("app.models.llm").LLM
ReactTask = import_module("app.models.react").ReactTask
SessionModel = import_module("app.models.session").Session
User = import_module("app.models.user").User
Workspace = import_module("app.models.workspace").Workspace
ReactTaskLaunchRequest = import_module(
    "app.services.react_task_supervisor"
).ReactTaskLaunchRequest
ReactTaskSupervisor = import_module(
    "app.services.react_task_supervisor"
).ReactTaskSupervisor
ToolExecutionContext = import_module(
    "app.orchestration.tool.manager"
).ToolExecutionContext
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

        llm = LLM(
            name="llm-live",
            endpoint="https://example.com/v1",
            model="live-model",
            api_key="secret",
            max_context=5000,
        )
        release_llm = LLM(
            name="llm-release",
            endpoint="https://example.com/v1",
            model="release-model",
            api_key="secret",
            max_context=9000,
        )
        self.session.add(llm)
        self.session.add(release_llm)
        self.session.commit()
        self.session.refresh(llm)
        self.session.refresh(release_llm)
        self.llm = llm
        self.release_llm = release_llm

        agent = Agent(
            name="agent-1",
            llm_id=llm.id,
            max_iteration=30,
            tool_ids='["live_tool"]',
            skill_ids='["live_skill"]',
            sandbox_timeout_seconds=25,
        )
        self.session.add(agent)
        self.session.commit()
        self.session.refresh(agent)
        self.agent = agent

        user = User(username="alice", password_hash="hash")
        self.session.add(user)
        self.session.commit()

        release = AgentRelease(
            agent_id=agent.id or 0,
            version=1,
            snapshot_json=json.dumps(
                {
                    "schema_version": 1,
                    "agent": {
                        "id": agent.id,
                        "name": agent.name,
                        "description": None,
                        "llm_id": release_llm.id,
                        "skill_resolution_llm_id": None,
                        "session_idle_timeout_minutes": 15,
                        "sandbox_timeout_seconds": 90,
                        "compact_threshold_percent": 60,
                        "is_active": True,
                        "max_iteration": 7,
                        "tool_ids": ["release_tool"],
                        "skill_ids": ["release_skill"],
                    },
                    "scenes": [],
                    "channel_bindings": [],
                    "web_search_bindings": [],
                },
                ensure_ascii=False,
            ),
            snapshot_hash="hash-release",
            change_summary_json="[]",
        )
        self.session.add(release)
        self.session.commit()
        self.session.refresh(release)
        self.release = release

        workspace = Workspace(
            workspace_id="workspace-1",
            agent_id=agent.id or 0,
            user="alice",
            scope="session_private",
            session_id="session-1",
        )
        self.session.add(workspace)
        session = SessionModel(
            session_id="session-1",
            agent_id=agent.id or 0,
            release_id=release.id or 0,
            user="alice",
            workspace_id="workspace-1",
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
        task = ReactTask(
            task_id="task-1",
            agent_id=1,
            user="alice",
            user_message="Help me",
            user_intent="Help me",
            status="pending",
            iteration=0,
        )

        self.assertTrue(_should_run_skill_resolution(task=task, resolver_llm_id=2))

    def test_skips_skill_resolution_for_waiting_input_resume(self) -> None:
        """Clarify resumes should continue the task instead of matching skills again."""
        task = ReactTask(
            task_id="task-clarify",
            agent_id=1,
            user="alice",
            user_message="Help me export",
            user_intent="Help me export",
            status="waiting_input",
            iteration=1,
        )

        self.assertFalse(_should_run_skill_resolution(task=task, resolver_llm_id=2))

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
        self.assertEqual(task.max_iteration, 7)
        self.assertGreater(refreshed_session.updated_at, original_updated_at)

    def test_run_task_uses_release_runtime_settings(self) -> None:
        """Execution should read tool and timeout settings from the pinned release."""
        task = ReactTask(
            task_id="task-release",
            session_id="session-1",
            agent_id=self.agent.id or 0,
            user="alice",
            user_message="Run released config",
            user_intent="Run released config",
            status="pending",
            iteration=0,
            max_iteration=7,
        )
        self.session.add(task)
        self.session.commit()

        captured: dict[str, object] = {}

        class DummyEngine:
            """Minimal async engine stub for release-runtime capture."""

            def __init__(self, **kwargs: object) -> None:
                tool_execution_context = kwargs["tool_execution_context"]
                if not isinstance(tool_execution_context, ToolExecutionContext):
                    raise AssertionError("Expected a ToolExecutionContext instance")
                captured["tool_execution_context"] = tool_execution_context
                self.cancelled = False

            async def run_task(self, **kwargs: object):
                if False:
                    yield kwargs

        with (
            patch.object(
                self.supervisor,
                "_build_request_tool_manager",
                return_value=MagicMock(),
            ) as build_tool_manager,
            patch.object(
                react_task_supervisor_module,
                "create_llm_from_config",
                return_value=object(),
            ),
            patch.object(
                react_task_supervisor_module,
                "list_visible_skills",
                return_value=[],
            ),
            patch.object(
                react_task_supervisor_module,
                "build_skill_mounts",
                return_value=[],
            ),
            patch.object(
                react_task_supervisor_module,
                "ReactEngine",
                DummyEngine,
            ),
            patch.object(
                self.supervisor,
                "_publish_event",
                new=AsyncMock(return_value=None),
            ),
        ):
            asyncio.run(
                self.supervisor._run_task(
                    task_id="task-release",
                    launch=ReactTaskLaunchRequest(
                        agent_id=self.agent.id or 0,
                        message="Run released config",
                        username="alice",
                        session_id="session-1",
                        file_ids=[],
                    ),
                )
            )

        build_tool_manager.assert_called_once()
        build_tool_manager_kwargs = build_tool_manager.call_args.kwargs
        self.assertEqual(build_tool_manager_kwargs["username"], "alice")
        self.assertEqual(build_tool_manager_kwargs["agent_id"], self.agent.id or 0)
        self.assertEqual(
            build_tool_manager_kwargs["raw_tool_ids"],
            '["release_tool"]',
        )
        self.assertIn("tool_execution_context", captured)
        tool_execution_context = captured["tool_execution_context"]
        self.assertIsInstance(tool_execution_context, ToolExecutionContext)
        if not isinstance(tool_execution_context, ToolExecutionContext):
            self.fail("Expected a ToolExecutionContext instance")
        self.assertEqual(
            cast(Any, tool_execution_context).sandbox_timeout_seconds,
            90,
        )

    def test_prepare_task_rejects_text_reply_for_structured_pending_action(
        self,
    ) -> None:
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

    def test_submit_pending_user_action_resumes_task_with_structured_result(
        self,
    ) -> None:
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

        with (
            patch.object(
                react_task_supervisor_module,
                "apply_skill_change_submission",
                return_value={
                    "submission_id": 42,
                    "skill_name": "planning-kit",
                    "status": "applied",
                    "message": "Applied private skill 'planning-kit'.",
                },
            ),
            patch.object(
                self.supervisor,
                "_run_task",
                new=AsyncMock(return_value=None),
            ),
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
