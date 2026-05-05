"""Tests for workspace guidance discovery and prompt rendering."""

import sys
import tempfile
import unittest
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

prompt_template = import_module("app.orchestration.react.prompt_template")
workspace_guidance_service = import_module("app.services.workspace_guidance_service")


class WorkspaceGuidanceServiceTestCase(unittest.TestCase):
    """Validate workspace guidance discovery and prompt-template injection."""

    def setUp(self) -> None:
        """Create one isolated temporary workspace root."""
        self.tmpdir = tempfile.TemporaryDirectory()
        self.workspace_path = Path(self.tmpdir.name)

    def tearDown(self) -> None:
        """Release the temporary workspace root."""
        self.tmpdir.cleanup()

    def test_discover_prefers_agents_over_claude(self) -> None:
        """`AGENTS.md` should outrank `CLAUDE.md` when both are present."""
        (self.workspace_path / "AGENTS.md").write_text(
            "Use pytest.\n",
            encoding="utf-8",
        )
        (self.workspace_path / "CLAUDE.md").write_text(
            "Use npm test.\n",
            encoding="utf-8",
        )

        discovered = workspace_guidance_service.discover_workspace_guidance_file(
            self.workspace_path
        )

        self.assertIsNotNone(discovered)
        if discovered is None:
            self.fail("Expected one workspace guidance file to be discovered.")
        host_path, sandbox_path = discovered
        self.assertEqual(host_path.name, "AGENTS.md")
        self.assertEqual(sandbox_path, "/workspace/AGENTS.md")

    def test_build_workspace_guidance_prompt_uses_canonical_sandbox_path(
        self,
    ) -> None:
        """Prompt payloads should expose the sandbox-visible guidance path."""
        (self.workspace_path / "CLAUDE.md").write_text(
            "# Local Rules\n\nPrefer pnpm.\n",
            encoding="utf-8",
        )

        prompt_block = workspace_guidance_service.build_workspace_guidance_prompt(
            self.workspace_path
        )

        self.assertEqual(
            prompt_block,
            "# /workspace/CLAUDE.md\n\n# Local Rules\n\nPrefer pnpm.",
        )

    def test_build_workspace_guidance_prompt_returns_empty_when_missing(self) -> None:
        """Workspaces without a supported file should inject no guidance."""
        self.assertEqual(
            workspace_guidance_service.build_workspace_guidance_prompt(
                self.workspace_path
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

    def test_task_start_time_uses_configured_timezone_format(self) -> None:
        """Task-start time should render in local IANA timezone format."""
        rendered_time = prompt_template._format_task_start_time(
            datetime(2026, 5, 1, 6, 32, 10, tzinfo=UTC),
            timezone_name="Asia/Shanghai",
        )

        self.assertEqual(
            rendered_time,
            "2026-05-01 14:32:10 Asia/Shanghai (UTC+08:00)",
        )

    def test_runtime_user_prompt_injects_task_start_time(self) -> None:
        """The task bootstrap prompt should replace the system time placeholder."""
        rendered = prompt_template.build_runtime_user_prompt()

        self.assertIn("task start time:", rendered)
        self.assertNotIn("{{system_time}}", rendered)


if __name__ == "__main__":
    unittest.main()
