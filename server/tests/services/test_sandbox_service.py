"""Unit tests for sandbox-manager client timeout behavior."""

from __future__ import annotations

import sys
import unittest
from importlib import import_module
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

sandbox_service_module = import_module("app.services.sandbox_service")
SandboxService = sandbox_service_module.SandboxService
workspace_storage_service_module = import_module(
    "app.services.workspace_storage_service"
)


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

    def _mount_spec(self) -> Any:
        """Return one deterministic mount spec for sandbox-manager requests."""
        return workspace_storage_service_module.WorkspaceMountSpec(
            workspace_id="workspace-1",
            storage_backend="seaweedfs",
            logical_path="users/alice/agents/1/sessions/session-1",
            mount_mode="live_sync",
        )

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
                mount_spec=self._mount_spec(),
                cmd=["echo", "hi"],
                skills=[
                    {
                        "name": "crm_research",
                        "canonical_location": "/app/server/workspace/alice/skills/crm_research",
                    }
                ],
                timeout_seconds=60,
            )

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.stdout, "ok")
        self.assertEqual(
            post_mock.call_args.kwargs["timeout"],
            60,
        )
        self.assertEqual(
            post_mock.call_args.kwargs["json"]["storage_backend"],
            "seaweedfs",
        )
        self.assertEqual(
            post_mock.call_args.kwargs["json"]["logical_path"],
            "users/alice/agents/1/sessions/session-1",
        )
        self.assertEqual(
            post_mock.call_args.kwargs["json"]["skills"],
            [
                {
                    "name": "crm_research",
                    "canonical_location": "/app/server/workspace/alice/skills/crm_research",
                }
            ],
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
                mount_spec=self._mount_spec(),
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
                mount_spec=self._mount_spec(),
                timeout_seconds=75,
            )

        self.assertEqual(post_mock.call_args.kwargs["timeout"], 75)
        self.assertEqual(
            post_mock.call_args.kwargs["json"]["workspace_id"],
            "workspace-1",
        )

    def test_exec_surfaces_manager_detail_field_on_error(self) -> None:
        """Manager JSON errors should preserve their concrete detail message."""
        response = Mock()
        response.status_code = 500
        response.text = '{"detail":"Workspace cache path is missing."}'
        response.json.return_value = {"detail": "Workspace cache path is missing."}

        with (
            patch.object(
                sandbox_service_module.requests,
                "post",
                return_value=response,
            ),
            self.assertRaises(RuntimeError) as ctx,
        ):
            self.service.exec(
                username="alice",
                mount_spec=self._mount_spec(),
                cmd=["pwd"],
            )

        self.assertIn("Workspace cache path is missing.", str(ctx.exception))
