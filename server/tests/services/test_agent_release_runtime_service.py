"""Unit tests for release-pinned runtime configuration resolution."""

import json
import sys
import unittest
from importlib import import_module
from pathlib import Path

from sqlmodel import Session as DBSession, SQLModel, create_engine

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

Agent = import_module("app.models.agent").Agent
AgentRelease = import_module("app.models.agent_release").AgentRelease
AgentTestSnapshot = import_module("app.models.agent_release").AgentTestSnapshot
SessionModel = import_module("app.models.session").Session
AgentReleaseRuntimeService = import_module(
    "app.services.agent_release_runtime_service"
).AgentReleaseRuntimeService


class AgentReleaseRuntimeServiceTestCase(unittest.TestCase):
    """Validate release-aware runtime resolution for end-user sessions."""

    def setUp(self) -> None:
        """Create an isolated in-memory database per test."""
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.session = DBSession(self.engine)

        agent = Agent(
            name="agent-1",
            llm_id=99,
            session_idle_timeout_minutes=21,
            sandbox_timeout_seconds=33,
            compact_threshold_percent=77,
            max_iteration=12,
            tool_ids='["live_tool"]',
            skill_ids='["live_skill"]',
        )
        self.session.add(agent)
        self.session.commit()
        self.session.refresh(agent)
        self.agent = agent

        release = AgentRelease(
            agent_id=agent.id or 0,
            version=1,
            snapshot_json=json.dumps(
                {
                    "schema_version": 1,
                    "agent": {
                        "id": agent.id,
                        "name": agent.name,
                        "description": "Released description",
                        "llm_id": 3,
                        "session_idle_timeout_minutes": 45,
                        "sandbox_timeout_seconds": 90,
                        "compact_threshold_percent": 55,
                        "is_active": True,
                        "max_iteration": 6,
                        "tool_ids": ["release_tool", "web_search"],
                        "skill_ids": ["release_skill"],
                    },
                    "channel_bindings": [],
                    "web_search_bindings": [],
                },
                ensure_ascii=False,
            ),
            snapshot_hash="hash-1",
            change_summary_json="[]",
        )
        self.session.add(release)
        self.session.commit()
        self.session.refresh(release)
        self.release = release

        session_row = SessionModel(
            session_id="session-1",
            agent_id=agent.id or 0,
            release_id=release.id or 0,
            user="alice",
            chat_history='{"version": 1, "messages": []}',
            react_llm_messages="[]",
            react_llm_cache_state="{}",
        )
        self.session.add(session_row)
        self.session.commit()
        self.session.refresh(session_row)
        self.session_row = session_row

        self.service = AgentReleaseRuntimeService(self.session)

    def tearDown(self) -> None:
        """Close the session after each test."""
        self.session.close()

    def test_resolve_for_session_prefers_release_snapshot(self) -> None:
        """Pinned sessions should use the published release snapshot values."""
        runtime_config = self.service.resolve_for_session("session-1")

        self.assertEqual(runtime_config.source, "release")
        self.assertEqual(runtime_config.release_id, self.release.id or 0)
        self.assertEqual(runtime_config.llm_id, 3)
        self.assertEqual(runtime_config.session_idle_timeout_minutes, 45)
        self.assertEqual(runtime_config.sandbox_timeout_seconds, 90)
        self.assertEqual(runtime_config.compact_threshold_percent, 55)
        self.assertEqual(runtime_config.max_iteration, 6)
        self.assertEqual(runtime_config.raw_tool_ids, '["release_tool","web_search"]')
        self.assertEqual(runtime_config.raw_skill_ids, '["release_skill"]')

    def test_resolve_for_session_falls_back_to_live_agent_for_legacy_rows(self) -> None:
        """Legacy sessions without release pinning should still remain usable."""
        self.session_row.release_id = None
        self.session.add(self.session_row)
        self.session.commit()

        runtime_config = self.service.resolve_for_session("session-1")

        self.assertEqual(runtime_config.source, "live")
        self.assertIsNone(runtime_config.release_id)
        self.assertEqual(runtime_config.llm_id, 99)
        self.assertEqual(runtime_config.max_iteration, 12)
        self.assertEqual(runtime_config.raw_tool_ids, '["live_tool"]')

    def test_resolve_for_session_prefers_studio_test_snapshot(self) -> None:
        """Studio test sessions should use their frozen working-copy snapshot."""
        test_snapshot = AgentTestSnapshot(
            agent_id=self.agent.id or 0,
            snapshot_json=json.dumps(
                {
                    "schema_version": 1,
                    "agent": {
                        "id": self.agent.id,
                        "name": "Draft agent",
                        "description": "Working copy",
                        "llm_id": 88,
                        "session_idle_timeout_minutes": 19,
                        "sandbox_timeout_seconds": 44,
                        "compact_threshold_percent": 61,
                        "is_active": True,
                        "max_iteration": 9,
                        "tool_ids": ["draft_tool"],
                        "skill_ids": ["draft_skill"],
                    },
                    "channel_bindings": [],
                    "web_search_bindings": [],
                },
                ensure_ascii=False,
            ),
            snapshot_hash="test-hash",
            workspace_hash="workspace-hash",
            created_by="alice",
        )
        self.session.add(test_snapshot)
        self.session.commit()
        self.session.refresh(test_snapshot)

        self.session_row.release_id = None
        self.session_row.type = "studio_test"
        self.session_row.test_snapshot_id = test_snapshot.id
        self.session.add(self.session_row)
        self.session.commit()

        runtime_config = self.service.resolve_for_session("session-1")

        self.assertEqual(runtime_config.source, "studio_test")
        self.assertIsNone(runtime_config.release_id)
        self.assertEqual(runtime_config.llm_id, 88)
        self.assertEqual(runtime_config.max_iteration, 9)
        self.assertEqual(runtime_config.raw_tool_ids, '["draft_tool"]')
        self.assertEqual(runtime_config.raw_skill_ids, '["draft_skill"]')


if __name__ == "__main__":
    unittest.main()
