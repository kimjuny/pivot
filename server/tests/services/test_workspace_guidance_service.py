"""Tests for workspace guidance discovery and prompt rendering."""

import sys
import tempfile
import unittest
from importlib import import_module
from pathlib import Path
from unittest.mock import patch

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

prompt_template = import_module("app.orchestration.react.prompt_template")
workspace_guidance_service = import_module("app.services.workspace_guidance_service")
WorkspaceMountSpec = import_module(
    "app.services.workspace_storage_service"
).WorkspaceMountSpec


class WorkspaceGuidanceServiceTestCase(unittest.TestCase):
    """Validate workspace guidance discovery and prompt-template injection."""

    def setUp(self) -> None:
        """Create one isolated temporary workspace root."""
        self.tmpdir = tempfile.TemporaryDirectory()
        self.workspace_path = Path(self.tmpdir.name)

    def tearDown(self) -> None:
        """Release the temporary workspace root."""
        self.tmpdir.cleanup()

    def test_build_workspace_guidance_prompt_uses_canonical_sandbox_path(
        self,
    ) -> None:
        """Prompt payloads should expose the sandbox-visible guidance path."""
        with patch.object(
            workspace_guidance_service.WorkspaceRuntimeFileService,
            "read_guidance_file",
            return_value=("/workspace/CLAUDE.md", "# Local Rules\n\nPrefer pnpm."),
        ):
            prompt_block = workspace_guidance_service.build_workspace_guidance_prompt(
                username="alice",
                mount_spec=WorkspaceMountSpec(
                    workspace_id="workspace-1",
                    storage_backend="seaweedfs",
                    logical_path="users/alice/agents/7/sessions/workspace-1",
                    mount_mode="live_sync",
                ),
            )

        self.assertEqual(
            prompt_block,
            "# /workspace/CLAUDE.md\n\n# Local Rules\n\nPrefer pnpm.",
        )

    def test_build_workspace_guidance_prompt_returns_empty_when_missing(self) -> None:
        """Workspaces without a supported file should inject no guidance."""
        with patch.object(
            workspace_guidance_service.WorkspaceRuntimeFileService,
            "read_guidance_file",
            return_value=None,
        ):
            self.assertEqual(
                workspace_guidance_service.build_workspace_guidance_prompt(
                    username="alice",
                    mount_spec=WorkspaceMountSpec(
                        workspace_id="workspace-1",
                        storage_backend="seaweedfs",
                        logical_path="users/alice/agents/7/sessions/workspace-1",
                        mount_mode="live_sync",
                    ),
                ),
                "",
            )

    def test_runtime_user_prompt_injects_workspace_guidance(self) -> None:
        """The task bootstrap prompt should replace the guidance placeholder."""
        rendered = prompt_template.build_runtime_user_prompt(
            workspace_guidance="# /workspace/AGENTS.md\n\nUse uv run.",
        )

        self.assertIn("## 8. Workspace Guidance", rendered)
        self.assertIn("# /workspace/AGENTS.md", rendered)
        self.assertIn("Use uv run.", rendered)
        self.assertNotIn("{{workspace_guidance}}", rendered)


if __name__ == "__main__":
    unittest.main()
