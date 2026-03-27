"""Tests for persisted agent draft and release snapshots."""

from __future__ import annotations

import sys
import unittest
from importlib import import_module
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

import_module("app.models")

Agent = import_module("app.models.agent").Agent
Scene = import_module("app.models.agent").Scene
Subscene = import_module("app.models.agent").Subscene
Connection = import_module("app.models.agent").Connection
AgentChannelBinding = import_module("app.models.channel").AgentChannelBinding
AgentWebSearchBinding = import_module("app.models.web_search").AgentWebSearchBinding
AgentSnapshotService = import_module(
    "app.services.agent_snapshot_service"
).AgentSnapshotService


class AgentSnapshotServiceTestCase(unittest.TestCase):
    """Validate persisted draft/release snapshots for one agent."""

    def setUp(self) -> None:
        """Create an isolated in-memory database for each test."""
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.service = AgentSnapshotService(self.session)

        self.agent = Agent(
            name="support-bot",
            description="Handles customer support.",
            llm_id=1,
            is_active=True,
            max_iteration=8,
        )
        self.session.add(self.agent)
        self.session.commit()
        self.session.refresh(self.agent)

        scene = Scene(
            name="triage",
            description="Initial routing scene",
            agent_id=self.agent.id,
        )
        self.session.add(scene)
        self.session.commit()
        self.session.refresh(scene)

        subscene = Subscene(
            name="start",
            type="start",
            state="inactive",
            description="Entry node",
            mandatory=True,
            objective="Collect the issue",
            scene_id=scene.id,
        )
        self.session.add(subscene)
        self.session.commit()
        self.session.refresh(subscene)

        connection = Connection(
            name="loop",
            condition="need_more_info",
            from_subscene="start",
            to_subscene="start",
            scene_id=scene.id,
        )
        self.session.add(connection)
        self.session.commit()

    def tearDown(self) -> None:
        """Close the database session after each test."""
        self.session.close()

    def test_save_draft_and_publish_roundtrip(self) -> None:
        """Publishing should create an immutable release and clear pending diff."""
        saved_draft = self.service.save_draft(
            self.agent.id or 0,
            saved_by="alice",
        )
        self.assertEqual(saved_draft.saved_by, "alice")

        initial_state = self.service.get_draft_state(self.agent.id or 0)
        self.assertTrue(initial_state["has_publishable_changes"])
        self.assertIn(
            "Initial release from saved draft",
            initial_state["publish_summary"],
        )

        published_state = self.service.publish_saved_draft(
            self.agent.id or 0,
            release_note="Initial launch",
            published_by="alice",
        )
        self.assertFalse(published_state["has_publishable_changes"])
        latest_release = published_state["latest_release"]
        self.assertIsNotNone(latest_release)
        assert latest_release is not None
        self.assertEqual(latest_release["version"], 1)
        self.assertEqual(latest_release["release_note"], "Initial launch")
        self.assertEqual(len(published_state["release_history"]), 1)
        self.session.refresh(self.agent)
        self.assertEqual(self.agent.active_release_id, latest_release["id"])

    def test_saved_draft_diff_survives_binding_changes(self) -> None:
        """Saved draft vs latest release should capture persisted binding edits."""
        self.service.save_draft(self.agent.id or 0, saved_by="alice")
        self.service.publish_saved_draft(
            self.agent.id or 0,
            release_note="Initial launch",
            published_by="alice",
        )

        web_search_binding = AgentWebSearchBinding(
            agent_id=self.agent.id or 0,
            provider_key="tavily",
            enabled=True,
            auth_config='{"api_key":"secret"}',
            runtime_config='{"search_depth":"advanced"}',
        )
        channel_binding = AgentChannelBinding(
            agent_id=self.agent.id or 0,
            channel_key="telegram",
            name="Telegram Support",
            enabled=True,
            auth_config='{"bot_token":"123:abc"}',
            runtime_config="{}",
        )
        self.session.add(web_search_binding)
        self.session.add(channel_binding)
        self.session.commit()

        self.service.save_draft(self.agent.id or 0, saved_by="alice")
        draft_state = self.service.get_draft_state(self.agent.id or 0)

        self.assertTrue(draft_state["has_publishable_changes"])
        self.assertTrue(
            any(
                summary.startswith("Channel bindings added:")
                for summary in draft_state["publish_summary"]
            )
        )
        self.assertTrue(
            any(
                summary.startswith("Web search providers added:")
                for summary in draft_state["publish_summary"]
            )
        )
