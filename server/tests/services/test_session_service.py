"""Tests for session history plan snapshots."""

import json
import sys
import tempfile
import unittest
from importlib import import_module
from pathlib import Path
from typing import Any, cast

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
AgentSnapshotService = import_module(
    "app.services.agent_snapshot_service"
).AgentSnapshotService
SessionService = import_module("app.services.session_service").SessionService
TaskAttachmentService = import_module(
    "app.services.task_attachment_service"
).TaskAttachmentService
workspace_service = import_module("app.services.workspace_service")


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

        second_agent = Agent(name="agent-2", llm_id=None)
        self.session.add(second_agent)
        self.session.commit()
        self.session.refresh(second_agent)
        self.second_agent = second_agent

        session = Session(
            session_id="session-1",
            agent_id=agent.id or 0,
            user="alice",
            chat_history=json.dumps({"version": 1, "messages": []}),
            react_llm_messages="[]",
            react_llm_cache_state="{}",
        )
        self.session.add(session)
        self.session.add(
            Session(
                session_id="session-2",
                agent_id=second_agent.id or 0,
                user="alice",
                chat_history=json.dumps({"version": 1, "messages": []}),
                react_llm_messages="[]",
                react_llm_cache_state="{}",
            )
        )
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

    def test_full_history_includes_assistant_attachments(self) -> None:
        """Full history should expose persisted assistant artifacts beside the answer."""
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        workspace_module = cast(Any, workspace_service)
        original_workspace_root = workspace_module._WORKSPACE_ROOT
        workspace_module._WORKSPACE_ROOT = Path(temp_dir.name)
        self.addCleanup(
            setattr,
            workspace_module,
            "_WORKSPACE_ROOT",
            original_workspace_root,
        )

        task = ReactTask(
            task_id="task-attachments",
            session_id="session-1",
            agent_id=self.agent.id or 0,
            user="alice",
            user_message="Create a report",
            user_intent="Create a report",
            status="completed",
        )
        self.session.add(task)
        self.session.commit()

        source_file = (
            workspace_module.ensure_agent_workspace("alice", self.agent.id or 0)
            / "outputs"
            / "report.md"
        )
        source_file.parent.mkdir(parents=True, exist_ok=True)
        source_file.write_text("# Report", encoding="utf-8")

        TaskAttachmentService(self.session).create_from_answer_paths(
            username="alice",
            agent_id=self.agent.id or 0,
            task_id=task.task_id,
            session_id="session-1",
            paths=["/workspace/outputs/report.md"],
        )

        history = self.service.get_full_session_history("session-1")

        self.assertEqual(len(history), 1)
        self.assertEqual(
            history[0]["assistant_attachments"][0].display_name,
            "report.md",
        )

    def test_update_chat_history_accepts_attachment_dict_payloads(self) -> None:
        """Chat history should accept public attachment dicts from the streaming layer."""
        success = self.service.update_chat_history(
            "session-1",
            "assistant",
            "Done",
            attachments=[
                {
                    "attachment_id": "attachment-1",
                    "display_name": "report.md",
                    "original_name": "report.md",
                    "mime_type": "text/markdown",
                    "extension": "md",
                    "size_bytes": 128,
                    "render_kind": "markdown",
                    "workspace_relative_path": "outputs/report.md",
                    "created_at": "2026-03-30T00:00:00Z",
                }
            ],
        )

        self.assertTrue(success)

        history = self.service.get_chat_history("session-1")
        self.assertEqual(history[-1]["attachments"][0]["attachment_id"], "attachment-1")
        self.assertEqual(history[-1]["attachments"][0]["display_name"], "report.md")

    def test_create_session_pins_active_release_id(self) -> None:
        """New sessions should freeze the agent's current active release."""
        self.agent.active_release_id = 7
        self.session.add(self.agent)
        self.session.commit()

        created = self.service.create_session(agent_id=self.agent.id or 0, user="alice")

        self.assertEqual(created.release_id, 7)
        self.assertEqual(created.agent_id, self.agent.id or 0)

    def test_create_session_rejects_unpublished_agent(self) -> None:
        """End users should not start sessions before an agent is published."""
        self.agent.active_release_id = None
        self.session.add(self.agent)
        self.session.commit()

        with self.assertRaisesRegex(
            ValueError,
            "not published for end users yet",
        ):
            self.service.create_session(agent_id=self.agent.id or 0, user="alice")

    def test_create_session_rejects_disabled_agent(self) -> None:
        """Serving-disabled agents should refuse new interactive sessions."""
        self.agent.active_release_id = 3
        self.agent.serving_enabled = False
        self.session.add(self.agent)
        self.session.commit()

        with self.assertRaisesRegex(
            ValueError,
            "disabled for end users",
        ):
            self.service.create_session(agent_id=self.agent.id or 0, user="alice")

    def test_create_studio_test_session_pins_frozen_snapshot(self) -> None:
        """Studio Test should create sessions from a frozen working-copy snapshot."""
        snapshot = AgentSnapshotService(self.session).create_test_snapshot(
            self.agent.id or 0,
            working_copy_snapshot={
                "schema_version": 1,
                "agent": {
                    "name": "agent-1 draft",
                    "description": "Draft",
                    "llm_id": None,
                    "skill_resolution_llm_id": None,
                    "session_idle_timeout_minutes": 15,
                    "sandbox_timeout_seconds": 60,
                    "compact_threshold_percent": 60,
                    "is_active": True,
                    "max_iteration": 30,
                    "tool_ids": None,
                    "skill_ids": None,
                },
                "scenes": [],
            },
            created_by="alice",
        )

        created = self.service.create_session(
            agent_id=self.agent.id or 0,
            user="alice",
            session_type="studio_test",
            test_snapshot_id=snapshot.id,
        )

        self.assertEqual(created.type, "studio_test")
        self.assertIsNone(created.release_id)
        self.assertEqual(created.test_snapshot_id, snapshot.id)

    def test_get_sessions_by_user_filters_by_session_type(self) -> None:
        """Studio and Consumer session listings should stay isolated."""
        snapshot = AgentSnapshotService(self.session).create_test_snapshot(
            self.agent.id or 0,
            working_copy_snapshot={
                "schema_version": 1,
                "agent": {
                    "name": "agent-1 draft",
                    "description": None,
                    "llm_id": None,
                    "skill_resolution_llm_id": None,
                    "session_idle_timeout_minutes": 15,
                    "sandbox_timeout_seconds": 60,
                    "compact_threshold_percent": 60,
                    "is_active": True,
                    "max_iteration": 30,
                    "tool_ids": None,
                    "skill_ids": None,
                },
                "scenes": [],
            },
            created_by="alice",
        )
        self.session.add(
            Session(
                session_id="session-3",
                agent_id=self.agent.id or 0,
                type="studio_test",
                test_snapshot_id=snapshot.id,
                user="alice",
                chat_history=json.dumps({"version": 1, "messages": []}),
                react_llm_messages="[]",
                react_llm_cache_state="{}",
            )
        )
        self.session.commit()

        sessions = self.service.get_sessions_by_user(
            user="alice",
            session_type="studio_test",
            limit=10,
        )

        self.assertEqual([session.session_id for session in sessions], ["session-3"])

    def test_get_sessions_by_user_supports_multiple_agent_ids(self) -> None:
        """Multi-agent filters keep Consumer listings inside the requested scope."""
        sessions = self.service.get_sessions_by_user(
            user="alice",
            agent_ids=[self.second_agent.id or 0],
            limit=10,
        )

        self.assertEqual([session.session_id for session in sessions], ["session-2"])
