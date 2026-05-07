"""Unit tests for aggregated Agent detail sidebar counts."""

from __future__ import annotations

import json
import sys
import unittest
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from sqlmodel import Session as DBSession, SQLModel, create_engine

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

import_module("app.models")

Agent = import_module("app.models.agent").Agent
User = import_module("app.models.user").User
AgentSidebarService = import_module(
    "app.services.agent_sidebar_service"
).AgentSidebarService


class AgentSidebarServiceTestCase(unittest.TestCase):
    """Validate compact selected/total sidebar summaries."""

    def setUp(self) -> None:
        """Create an isolated in-memory database per test."""
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.session = DBSession(self.engine)
        self.user = User(username="alice", password_hash="secret", role_id=1)
        self.agent = Agent(
            name="support-bot",
            llm_id=1,
            tool_ids=json.dumps(["search_docs"]),
            skill_ids=json.dumps(["summarize"]),
        )
        self.session.add(self.agent)
        self.session.commit()
        self.session.refresh(self.agent)
        self.service = AgentSidebarService(self.session)

    def tearDown(self) -> None:
        """Close the session after each test."""
        self.session.close()

    @patch("app.services.agent_sidebar_service.WebSearchService.list_agent_bindings")
    @patch("app.services.agent_sidebar_service.WebSearchService.list_catalog")
    @patch(
        "app.services.agent_sidebar_service.MediaGenerationService.list_agent_bindings"
    )
    @patch("app.services.agent_sidebar_service.MediaGenerationService.list_catalog")
    @patch("app.services.agent_sidebar_service.ChannelService.list_agent_bindings")
    @patch("app.services.agent_sidebar_service.ChannelService.list_catalog")
    @patch(
        "app.services.agent_sidebar_service.ExtensionService.get_installation_contribution_items"
    )
    @patch(
        "app.services.agent_sidebar_service.ExtensionService.list_agent_package_choices"
    )
    @patch("app.services.agent_sidebar_service.list_visible_skills")
    @patch("app.services.agent_sidebar_service.list_usable_tools")
    def test_get_sidebar_stats_aggregates_selected_and_total_counts(
        self,
        mock_list_usable_tools: Any,
        mock_list_visible_skills: Any,
        mock_list_agent_package_choices: Any,
        mock_get_installation_contribution_items: Any,
        mock_list_channel_catalog: Any,
        mock_list_channel_bindings: Any,
        mock_list_media_catalog: Any,
        mock_list_media_bindings: Any,
        mock_list_web_search_catalog: Any,
        mock_list_web_search_bindings: Any,
    ) -> None:
        """Sidebar stats should combine base resources with enabled extensions."""
        mock_list_usable_tools.return_value = [
            {"name": "search_docs"},
            {"name": "fetch_url"},
        ]
        mock_list_visible_skills.return_value = [
            {"name": "summarize"},
            {"name": "plan"},
        ]
        mock_list_agent_package_choices.return_value = [
            {
                "package_id": "@pivot/enabled",
                "selected_binding": SimpleNamespace(
                    enabled=True,
                    extension_installation_id=10,
                ),
                "versions": [SimpleNamespace(id=10)],
            },
            {
                "package_id": "@pivot/disabled",
                "selected_binding": SimpleNamespace(
                    enabled=False,
                    extension_installation_id=11,
                ),
                "versions": [SimpleNamespace(id=11)],
            },
            {
                "package_id": "@pivot/available",
                "selected_binding": None,
                "versions": [SimpleNamespace(id=12)],
            },
        ]
        mock_get_installation_contribution_items.return_value = [
            {"type": "tool", "name": "ext_tool_a"},
            {"type": "tool", "name": "ext_tool_b"},
            {"type": "skill", "name": "ext_skill_a"},
        ]
        mock_list_channel_catalog.return_value = [{}, {}, {}]
        mock_list_channel_bindings.return_value = [{}]
        mock_list_media_catalog.return_value = [{}, {}, {}, {}, {}]
        mock_list_media_bindings.return_value = [{}, {}]
        mock_list_web_search_catalog.return_value = [{}, {}, {}, {}]
        mock_list_web_search_bindings.return_value = [{}]

        stats = self.service.get_sidebar_stats(
            agent_id=self.agent.id or 0,
            user=self.user,
        )

        self.assertEqual(
            stats,
            {
                "tools": {"selected_count": 1, "total_count": 4},
                "skills": {"selected_count": 1, "total_count": 3},
                "extensions": {"selected_count": 2, "total_count": 3},
                "channels": {"selected_count": 1, "total_count": 3},
                "media": {"selected_count": 2, "total_count": 5},
                "web_search": {"selected_count": 1, "total_count": 4},
            },
        )


if __name__ == "__main__":
    unittest.main()
