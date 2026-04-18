"""Unit tests for the built-in create_preview_endpoint tool."""

from __future__ import annotations

import sys
import unittest
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

create_preview_endpoint_module = import_module(
    "app.orchestration.tool.builtin.create_preview_endpoint"
)


class CreatePreviewEndpointToolTestCase(unittest.TestCase):
    """Validate preview tool launch-recipe wiring."""

    def test_tool_records_launch_recipe_and_connects_preview(self) -> None:
        """The tool should store launch metadata, then ensure the preview is reachable."""
        module = create_preview_endpoint_module
        context = SimpleNamespace(
            username="alice",
            session_id="session-1",
            sandbox_timeout_seconds=90,
            allowed_skills=(
                {"name": "alpha", "location": "/workspace/skills/alpha"},
            ),
        )
        record = SimpleNamespace(
            preview_id="preview-1",
            session_id="session-1",
            workspace_id="workspace-1",
            title="Landing Page",
            port=3000,
            path="/",
            start_server="bash /workspace/.pivot/previews/landing-page.sh",
            cwd="/workspace/apps/landing-page",
            created_at=SimpleNamespace(isoformat=lambda: "2026-04-18T00:00:00+00:00"),
        )
        service = MagicMock()
        service.create_preview_endpoint.return_value = record
        service.connect_preview_endpoint.return_value = record
        service.list_preview_endpoints.return_value = [record]
        service.build_proxy_url.return_value = "/api/chat-previews/preview-1/proxy/"
        workspace_service = MagicMock()
        workspace_service.get_workspace.return_value = object()
        workspace_service.get_workspace_logical_root.return_value = (
            "users/alice/agents/7/sessions/session-1/workspace"
        )

        session_manager = MagicMock()
        session_manager.__enter__.return_value = "db-session"
        session_manager.__exit__.return_value = None

        with (
            patch.object(module, "get_current_tool_execution_context", return_value=context),
            patch.object(module, "managed_session", return_value=session_manager),
            patch.object(module, "PreviewEndpointService", return_value=service),
            patch.object(module, "WorkspaceService", return_value=workspace_service),
        ):
            result = module.create_preview_endpoint(
                preview_name="Landing Page",
                start_server="bash /workspace/.pivot/previews/landing-page.sh",
                port=3000,
                path="/",
                cwd="apps/landing-page",
            )

        service.create_preview_endpoint.assert_called_once_with(
            username="alice",
            session_id="session-1",
            port=3000,
            path="/",
            title="Landing Page",
            cwd="apps/landing-page",
            start_server="bash /workspace/.pivot/previews/landing-page.sh",
            skills=context.allowed_skills,
        )
        service.connect_preview_endpoint.assert_called_once_with(
            preview_id="preview-1",
            username="alice",
            timeout_seconds=90,
        )
        self.assertTrue(result["has_launch_recipe"])
        self.assertEqual(result["active_preview_id"], "preview-1")

    def test_tool_rejects_blank_preview_name(self) -> None:
        """The tool should fail fast on empty preview labels."""
        module = create_preview_endpoint_module
        context = SimpleNamespace(
            username="alice",
            session_id="session-1",
            sandbox_timeout_seconds=90,
            allowed_skills=(),
        )

        with (
            patch.object(
                module, "get_current_tool_execution_context", return_value=context
            ),
            self.assertRaisesRegex(
                ValueError, "preview_name must be a non-empty string."
            ),
        ):
            module.create_preview_endpoint(
                preview_name="   ",
                start_server="bash /workspace/.pivot/previews/example.sh",
                port=3000,
            )

    def test_tool_rejects_blank_start_server(self) -> None:
        """The tool should fail fast on empty launch commands."""
        module = create_preview_endpoint_module
        context = SimpleNamespace(
            username="alice",
            session_id="session-1",
            sandbox_timeout_seconds=90,
            allowed_skills=(),
        )

        with (
            patch.object(
                module, "get_current_tool_execution_context", return_value=context
            ),
            self.assertRaisesRegex(
                ValueError,
                "start_server must be a non-empty shell command string.",
            ),
        ):
            module.create_preview_endpoint(
                preview_name="Landing Page",
                start_server="   ",
                port=3000,
            )
