"""Unit tests for consumer-visible agent filtering."""

import sys
import unittest
from importlib import import_module
from pathlib import Path

from sqlmodel import Session as DBSession, SQLModel, create_engine

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

Agent = import_module("app.models.agent").Agent
AgentService = import_module("app.services.agent_service").AgentService


class AgentServiceTestCase(unittest.TestCase):
    """Validate Consumer visibility rules for agents."""

    def setUp(self) -> None:
        """Create an isolated in-memory database per test."""
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.session = DBSession(self.engine)

        visible_agent = Agent(
            name="visible-agent",
            llm_id=1,
            active_release_id=11,
            serving_enabled=True,
        )
        unpublished_agent = Agent(
            name="draft-agent",
            llm_id=1,
            active_release_id=None,
            serving_enabled=True,
        )
        disabled_agent = Agent(
            name="disabled-agent",
            llm_id=1,
            active_release_id=12,
            serving_enabled=False,
        )
        self.session.add(visible_agent)
        self.session.add(unpublished_agent)
        self.session.add(disabled_agent)
        self.session.commit()
        self.session.refresh(visible_agent)
        self.visible_agent = visible_agent
        self.service = AgentService(self.session)

    def tearDown(self) -> None:
        """Close the session after each test."""
        self.session.close()

    def test_list_consumer_visible_agents_returns_only_serving_published_agents(
        self,
    ) -> None:
        """Consumer agent lists should expose only published serving agents."""
        agents = self.service.list_consumer_visible_agents()

        self.assertEqual([agent.name for agent in agents], ["visible-agent"])

    def test_require_consumer_visible_agent_rejects_hidden_agent(self) -> None:
        """Consumer should not load unpublished or disabled agents."""
        with self.assertRaisesRegex(ValueError, "not available to end users"):
            self.service.require_consumer_visible_agent(999)


if __name__ == "__main__":
    unittest.main()
