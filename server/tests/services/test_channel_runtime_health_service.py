"""Tests for centralized channel runtime health state."""

from __future__ import annotations

import sys
import unittest
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

import_module("app.models")

Agent = import_module("app.models.agent").Agent
AgentChannelBinding = import_module("app.models.channel").AgentChannelBinding
ChannelRuntimeHealthService = import_module(
    "app.services.channel_runtime_health_service"
).ChannelRuntimeHealthService


class ChannelRuntimeHealthServiceTestCase(unittest.TestCase):
    """Validate generic health state transitions for channel bindings."""

    def setUp(self) -> None:
        """Create an isolated in-memory database."""
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.agent = Agent(name="support-bot", is_active=True, max_iteration=5)
        self.session.add(self.agent)
        self.session.commit()
        self.session.refresh(self.agent)

        self.binding = AgentChannelBinding(
            agent_id=self.agent.id or 0,
            channel_key="pivot@test",
            name="Test Channel",
            enabled=True,
            auth_config="{}",
            runtime_config="{}",
        )
        self.session.add(self.binding)
        self.session.commit()
        self.session.refresh(self.binding)
        self.service = ChannelRuntimeHealthService(self.session)

    def tearDown(self) -> None:
        """Close the database session."""
        self.session.close()

    def test_record_network_failure_sets_retry_backoff(self) -> None:
        """Recoverable failures should enter degraded state with retry time."""
        self.service.record_failure(
            self.binding.id or 0,
            message="Connection timed out.",
            error_kind="network",
        )

        row = self.session.get(AgentChannelBinding, self.binding.id)
        if row is None:
            self.fail("Expected binding row to exist")
        self.assertEqual(row.last_health_status, "degraded")
        self.assertEqual(row.consecutive_failure_count, 1)
        self.assertIsNotNone(row.next_retry_at)
        self.assertIsNotNone(row.last_disconnected_at)
        self.assertIsNotNone(row.last_error_fingerprint)

    def test_record_dependency_failure_stops_automatic_retry(self) -> None:
        """Non-recoverable dependency failures should not schedule retry."""
        runtime = import_module("app.channels.runtime")

        self.service.record_failure(
            self.binding.id or 0,
            message="No module named provider_sdk.",
            error_kind="dependency",
        )

        row = self.session.get(AgentChannelBinding, self.binding.id)
        if row is None:
            self.fail("Expected binding row to exist")
        self.assertEqual(row.last_health_status, "error")
        self.assertEqual(row.consecutive_failure_count, 1)
        self.assertIsNone(row.next_retry_at)
        self.assertTrue(runtime.ChannelRuntimeManager._is_retry_deferred(row))

    def test_mark_healthy_clears_failure_state(self) -> None:
        """A healthy check should clear previous retry and failure state."""
        self.service.record_failure(
            self.binding.id or 0,
            message="Connection timed out.",
            error_kind="network",
        )

        self.service.mark_healthy(self.binding.id or 0, "Connected.")

        row = self.session.get(AgentChannelBinding, self.binding.id)
        if row is None:
            self.fail("Expected binding row to exist")
        self.assertEqual(row.last_health_status, "healthy")
        self.assertEqual(row.consecutive_failure_count, 0)
        self.assertIsNone(row.next_retry_at)
        self.assertIsNone(row.last_error_fingerprint)
        self.assertIsNotNone(row.last_connected_at)

    def test_naive_retry_time_is_treated_as_utc(self) -> None:
        """Retry comparisons must tolerate SQLite naive datetime values."""
        runtime = import_module("app.channels.runtime")
        self.binding.next_retry_at = datetime.now(UTC).replace(tzinfo=None)
        self.session.add(self.binding)
        self.session.commit()

        is_deferred = runtime.ChannelRuntimeManager._is_retry_deferred(self.binding)
        self.assertIsInstance(is_deferred, bool)
