"""Unit tests for sandbox-manager client timeout behavior."""

from __future__ import annotations

import sys
import unittest
from importlib import import_module
from pathlib import Path
from unittest.mock import Mock, patch

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

sandbox_service_module = import_module("app.services.sandbox_service")
SandboxService = sandbox_service_module.SandboxService


class SandboxServiceTimeoutTestCase(unittest.TestCase):
    """Validate per-agent timeout overrides for sandbox-manager calls."""

    def setUp(self) -> None:
        """Create one sandbox service with deterministic settings."""
        settings = type(
            "Settings",
            (),
            {
                "SANDBOX_MANAGER_URL": "http://sandbox-manager:8051",
                "SANDBOX_MANAGER_TIMEOUT_SECONDS": 30,
                "SANDBOX_MANAGER_TOKEN": "test-token",
            },
        )()
        self.settings_patch = patch.object(
            sandbox_service_module,
            "get_settings",
            return_value=settings,
        )
        self.settings_patch.start()
        self.service = SandboxService()

    def tearDown(self) -> None:
        """Stop settings patching after each test."""
        self.settings_patch.stop()

    def test_exec_uses_override_timeout_when_provided(self) -> None:
        """Agent-level timeout should override the global sandbox default."""
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"exit_code": 0, "stdout": "ok", "stderr": ""}

        with patch.object(
            sandbox_service_module.requests,
            "post",
            return_value=response,
        ) as post_mock:
            result = self.service.exec(
                username="alice",
                workspace_id="workspace-1",
                workspace_backend_path="/app/server/workspace/alice",
                cmd=["echo", "hi"],
                timeout_seconds=60,
            )

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.stdout, "ok")
        self.assertEqual(
            post_mock.call_args.kwargs["timeout"],
            60,
        )

    def test_exec_falls_back_to_global_timeout_without_override(self) -> None:
        """Legacy callers should keep using the configured global timeout."""
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"exit_code": 0, "stdout": "", "stderr": ""}

        with patch.object(
            sandbox_service_module.requests,
            "post",
            return_value=response,
        ) as post_mock:
            self.service.exec(
                username="alice",
                workspace_id="workspace-1",
                workspace_backend_path="/app/server/workspace/alice",
                cmd=["pwd"],
            )

        self.assertEqual(post_mock.call_args.kwargs["timeout"], 30)

    def test_create_forwards_override_timeout(self) -> None:
        """Sandbox prewarming should honor the same per-agent timeout override."""
        response = Mock()
        response.status_code = 200
        response.json.return_value = {}

        with patch.object(
            sandbox_service_module.requests,
            "post",
            return_value=response,
        ) as post_mock:
            self.service.create(
                username="alice",
                workspace_id="workspace-1",
                workspace_backend_path="/app/server/workspace/alice",
                timeout_seconds=75,
            )

        self.assertEqual(post_mock.call_args.kwargs["timeout"], 75)

    def test_exec_timeout_error_is_actionable_for_agent(self) -> None:
        """Read timeouts should explain next actions in agent-friendly language."""
        with (
            patch.object(
                sandbox_service_module.requests,
                "post",
                side_effect=sandbox_service_module.requests.ReadTimeout(
                    "HTTPConnectionPool(host='sandbox-manager', port=8051): "
                    "Read timed out."
                ),
            ),
            self.assertRaisesRegex(
                RuntimeError,
                "Workspace sandbox timed out after 45 seconds",
            ) as context,
        ):
            self.service.exec(
                username="alice",
                workspace_id="workspace-1",
                workspace_backend_path="/app/server/workspace/alice",
                cmd=["bash", "-lc", "sleep 90"],
                timeout_seconds=45,
            )

        message = str(context.exception)
        self.assertIn("backend was waiting for sandbox-manager", message)
        self.assertIn("Retry once for read-only actions", message)
        self.assertIn("do not blindly retry", message)
        self.assertIn("sandbox_timeout_seconds", message)

    def test_connection_error_explains_infrastructure_problem(self) -> None:
        """Connection failures should not look like command syntax mistakes."""
        with (
            patch.object(
                sandbox_service_module.requests,
                "post",
                side_effect=sandbox_service_module.requests.ConnectionError(
                    "connection refused"
                ),
            ),
            self.assertRaisesRegex(
                RuntimeError,
                "Workspace sandbox service is unreachable",
            ) as context,
        ):
            self.service.create(
                username="alice",
                workspace_id="workspace-1",
                workspace_backend_path="/app/server/workspace/alice",
            )

        self.assertIn("infrastructure problem", str(context.exception))
