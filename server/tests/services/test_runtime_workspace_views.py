"""Tests for runtime workspace views that must stay sandbox-stable."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from importlib import import_module
from pathlib import Path
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

import_module("app.models")
User = import_module("app.models.user").User
skill_service = import_module("app.services.skill_service")


class RuntimeWorkspaceViewsTestCase(unittest.TestCase):
    """Validate runtime views that must stay independent from provider roots."""

    def setUp(self) -> None:
        """Create one isolated database and workspace root."""
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)

        self.tmpdir = tempfile.TemporaryDirectory()
        self.workspace_root = Path(self.tmpdir.name) / "workspace"
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.workspace_patch = patch.object(
            skill_service,
            "workspace_root",
            return_value=self.workspace_root,
        )
        self.workspace_patch.start()

        self.alice = User(username="alice", password_hash="hash", role_id=1)
        self.bob = User(username="bob", password_hash="hash", role_id=1)
        self.session.add(self.alice)
        self.session.add(self.bob)
        self.session.commit()

    def tearDown(self) -> None:
        """Release temporary state after each test."""
        self.workspace_patch.stop()
        self.session.close()
        self.tmpdir.cleanup()

    def _write_skill(
        self,
        *,
        username: str,
        name: str,
        description: str,
        body: str,
    ) -> Path:
        """Create one skill in the unified on-disk layout."""
        skill_dir = self.workspace_root / "users" / username / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_path = skill_dir / "SKILL.md"
        skill_path.write_text(
            (
                f"---\nname: {name}\ndescription: {description}\n---\n\n"
                f"# {name}\n\n{body}\n"
            ),
            encoding="utf-8",
        )
        return skill_path

    def test_skill_mount_sources_and_prompt_paths_use_distinct_runtime_views(
        self,
    ) -> None:
        """Sandbox mounts should use host paths while prompts keep `/workspace` paths."""
        self._write_skill(
            username="alice",
            name="research-notes",
            description="Alice private research workflow",
            body="Private notes body.",
        )
        self._write_skill(
            username="bob",
            name="qa-playbook",
            description="Bob shared QA workflow",
            body="Shared QA body.",
        )

        skill_service.sync_skill_registry(self.session)

        mounts = skill_service.build_skill_mounts(
            self.session,
            "alice",
            ["research-notes", "qa-playbook"],
        )
        prompt_payload = json.loads(
            skill_service.build_skills_metadata_prompt_json(
                self.session,
                "alice",
                json.dumps(["qa-playbook"]),
            )
        )

        self.assertEqual(
            mounts,
            [
                {
                    "name": "research-notes",
                    "location": str(
                        (
                            self.workspace_root
                            / "users"
                            / "alice"
                            / "skills"
                            / "research-notes"
                        ).resolve()
                    ),
                },
                {
                    "name": "qa-playbook",
                    "location": str(
                        (
                            self.workspace_root
                            / "users"
                            / "bob"
                            / "skills"
                            / "qa-playbook"
                        ).resolve()
                    ),
                },
            ],
        )
        self.assertEqual(
            prompt_payload,
            [
                {
                    "name": "qa-playbook",
                    "description": "Bob shared QA workflow",
                    "path": "/workspace/skills/qa-playbook/SKILL.md",
                }
            ],
        )

    def test_runtime_skill_mounts_ignore_studio_skill_visibility(self) -> None:
        """End-user runtime should still mount configured skills after Studio access is revoked."""
        self._write_skill(
            username="alice",
            name="research-notes",
            description="Alice private research workflow",
            body="Private notes body.",
        )

        skill_service.sync_skill_registry(self.session)
        skill = skill_service.get_skill_by_name(self.session, "research-notes")
        self.assertIsNotNone(skill)
        skill_service.set_skill_access(
            self.session,
            skill=skill,
            use_scope="selected",
            use_user_ids={self.alice.id or 0},
            use_group_ids=set(),
            edit_user_ids={self.alice.id or 0},
            edit_group_ids=set(),
        )

        mounts = skill_service.build_skill_mounts(
            self.session,
            "bob",
            ["research-notes"],
        )
        prompt_payload = json.loads(
            skill_service.build_skills_metadata_prompt_json(
                self.session,
                "bob",
                json.dumps(["research-notes"]),
            )
        )

        self.assertEqual(
            mounts,
            [
                {
                    "name": "research-notes",
                    "location": str(
                        (
                            self.workspace_root
                            / "users"
                            / "alice"
                            / "skills"
                            / "research-notes"
                        ).resolve()
                    ),
                }
            ],
        )
        self.assertEqual(
            prompt_payload,
            [
                {
                    "name": "research-notes",
                    "description": "Alice private research workflow",
                    "path": "/workspace/skills/research-notes/SKILL.md",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
