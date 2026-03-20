"""Tests for web-search bindings and provider resolution."""

from __future__ import annotations

import sys
import unittest
from importlib import import_module
from pathlib import Path
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

import_module("app.models")

Agent = import_module("app.models.agent").Agent
service_module = import_module("app.services.web_search_service")
types_module = import_module("app.orchestration.web_search.types")


class WebSearchServiceTestCase(unittest.TestCase):
    """Validate binding persistence and runtime provider selection."""

    def setUp(self) -> None:
        """Create an isolated in-memory database for each test."""
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.service = service_module.WebSearchService(self.session)

        self.agent = Agent(name="search-bot", is_active=True, max_iteration=6)
        self.session.add(self.agent)
        self.session.commit()
        self.session.refresh(self.agent)

    def tearDown(self) -> None:
        """Close the database session after each test."""
        self.session.close()

    def test_create_binding_rejects_duplicate_provider_for_agent(self) -> None:
        """One agent should not persist the same provider twice."""
        self.service.create_binding(
            agent_id=self.agent.id or 0,
            provider_key="tavily",
            enabled=True,
            auth_config={"api_key": "tvly-1"},
            runtime_config={},
        )

        with self.assertRaisesRegex(ValueError, "already configured"):
            self.service.create_binding(
                agent_id=self.agent.id or 0,
                provider_key="tavily",
                enabled=True,
                auth_config={"api_key": "tvly-2"},
                runtime_config={},
            )

    def test_execute_search_requires_explicit_provider_when_multiple_are_enabled(
        self,
    ) -> None:
        """Ambiguous multi-provider agent config should fail loudly."""
        self.service.create_binding(
            agent_id=self.agent.id or 0,
            provider_key="tavily",
            enabled=True,
            auth_config={"api_key": "tvly-1"},
            runtime_config={},
        )
        self.service.create_binding(
            agent_id=self.agent.id or 0,
            provider_key="baidu",
            enabled=True,
            auth_config={"api_key": "bce-1"},
            runtime_config={},
        )

        with self.assertRaisesRegex(ValueError, "Specify provider explicitly"):
            self.service.execute_search(
                agent_id=self.agent.id or 0,
                request=types_module.WebSearchQueryRequest(query="Pivot news"),
            )

    def test_execute_search_uses_requested_provider_binding(self) -> None:
        """Explicit provider selection should route to the matching adapter."""
        self.service.create_binding(
            agent_id=self.agent.id or 0,
            provider_key="tavily",
            enabled=True,
            auth_config={"api_key": "tvly-1"},
            runtime_config={},
        )

        expected_result = types_module.WebSearchExecutionResult(
            query="Pivot release notes",
            provider={"key": "tavily", "name": "Tavily"},
            applied_parameters={"max_results": 2},
            results=[],
        )

        with patch(
            "app.services.web_search_service.get_web_search_provider"
        ) as provider_getter:
            provider = provider_getter.return_value
            provider.search.return_value = expected_result

            result = self.service.execute_search(
                agent_id=self.agent.id or 0,
                request=types_module.WebSearchQueryRequest(
                    query="Pivot release notes",
                    provider="tavily",
                    max_results=2,
                ),
            )

        self.assertEqual(result.provider["key"], "tavily")
        provider.search.assert_called_once()


if __name__ == "__main__":
    unittest.main()
