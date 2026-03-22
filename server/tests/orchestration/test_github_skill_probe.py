import sys
import unittest
from importlib import import_module
from pathlib import Path
from unittest.mock import patch

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

github_skill_module = import_module("app.orchestration.skills.github")


class GitHubSkillProbeTestCase(unittest.TestCase):
    """Regression tests for GitHub skill probe ref selection behavior."""

    def test_probe_keeps_default_branch_visible_when_branch_page_omits_it(self) -> None:
        """Default branch should still be selectable even if the first page omits it."""
        branches_payload = [{"name": "feature-001"}, {"name": "feature-002"}]
        tags_payload = [{"name": "v1.0.0"}]
        skills_payload = []

        def fake_get_json(path: str, *, allow_not_found: bool = False):  # type: ignore[no-untyped-def]
            if path == "/repos/acme/pivot-skills":
                return {
                    "default_branch": "main",
                    "description": "Skill catalog",
                }
            if path == "/repos/acme/pivot-skills/branches?per_page=100":
                return branches_payload
            if path == "/repos/acme/pivot-skills/tags?per_page=100":
                return tags_payload
            if path == "/repos/acme/pivot-skills/branches/main":
                return {"name": "main"}
            if path == "/repos/acme/pivot-skills/contents/skills?ref=main":
                return skills_payload
            if allow_not_found:
                return None
            raise AssertionError(f"Unexpected path: {path}")

        with patch.object(github_skill_module, "_get_json", side_effect=fake_get_json):
            result = github_skill_module.probe_github_skill_repository(
                "https://github.com/acme/pivot-skills"
            )

        self.assertEqual(result.default_ref, "main")
        self.assertEqual(result.selected_ref, "main")
        self.assertEqual(result.branches[0], "main")
        self.assertIn("feature-001", result.branches)
