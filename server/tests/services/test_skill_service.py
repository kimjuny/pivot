"""Tests for the database-backed skill registry service."""

import sys
import tempfile
import unittest
from importlib import import_module
from pathlib import Path
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine, select

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

import_module("app.models")
Skill = import_module("app.models.skill").Skill
User = import_module("app.models.user").User
skill_service = import_module("app.services.skill_service")


class SkillServiceTestCase(unittest.TestCase):
    """Validate skill persistence, visibility, and creator-only writes."""

    def setUp(self) -> None:
        """Create an isolated database plus temporary skill directories."""
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)

        self.tmpdir = tempfile.TemporaryDirectory()
        root = Path(self.tmpdir.name)
        self.workspace_root = root / "workspace"
        self.builtin_root = root / "builtin"
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.builtin_root.mkdir(parents=True, exist_ok=True)

        self.workspace_patch = patch.object(
            skill_service, "workspace_root", return_value=self.workspace_root
        )
        self.builtin_patch = patch.object(
            skill_service, "_builtin_skills_dir", return_value=self.builtin_root
        )
        self.workspace_patch.start()
        self.builtin_patch.start()

        self.alice = User(username="alice", password_hash="hash")
        self.bob = User(username="bob", password_hash="hash")
        self.session.add(self.alice)
        self.session.add(self.bob)
        self.session.commit()
        self.session.refresh(self.alice)
        self.session.refresh(self.bob)

    def tearDown(self) -> None:
        """Release temporary state after each test."""
        self.workspace_patch.stop()
        self.builtin_patch.stop()
        self.session.close()
        self.tmpdir.cleanup()

    def _write_skill(
        self,
        root: Path,
        name: str,
        description: str,
        body: str,
        *,
        filename: str = "SKILL.md",
    ) -> Path:
        """Create one markdown skill directory under the given root."""
        skill_dir = root / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_path = skill_dir / filename
        skill_path.write_text(
            (
                f"---\nname: {name}\ndescription: {description}\n---\n\n"
                f"# {name}\n\n{body}\n"
            ),
            encoding="utf-8",
        )
        return skill_path

    def test_sync_registry_and_visible_metadata(self) -> None:
        """Visible skill listings should come from persisted registry metadata."""
        self._write_skill(
            self.builtin_root,
            "coding",
            "Built-in coding instructions",
            "Use coding best practices.",
            filename="coding.md",
        )
        self._write_skill(
            self.workspace_root / "alice" / "skills" / "private",
            "research-notes",
            "Alice private research workflow",
            "Private notes body.",
            filename="research-notes.md",
        )
        self._write_skill(
            self.workspace_root / "alice" / "skills" / "shared",
            "team-writer",
            "Alice shared writing workflow",
            "Shared writing body.",
        )
        self._write_skill(
            self.workspace_root / "bob" / "skills" / "shared",
            "qa-playbook",
            "Bob shared QA workflow",
            "Shared QA body.",
        )

        skill_service.sync_skill_registry(self.session)

        rows = self.session.exec(select(Skill).order_by(Skill.name)).all()
        self.assertEqual(
            [row.name for row in rows],
            [
                "coding",
                "qa-playbook",
                "research-notes",
                "team-writer",
            ],
        )

        visible = {
            item["name"]: item
            for item in skill_service.list_visible_skills(self.session, "alice")
        }

        self.assertEqual(visible["coding"]["builtin"], True)
        self.assertEqual(visible["coding"]["read_only"], True)
        self.assertEqual(visible["qa-playbook"]["creator"], "bob")
        self.assertEqual(visible["qa-playbook"]["read_only"], True)
        self.assertEqual(visible["research-notes"]["kind"], "private")
        self.assertEqual(visible["research-notes"]["read_only"], False)
        self.assertEqual(visible["team-writer"]["creator"], "alice")
        self.assertEqual(visible["team-writer"]["read_only"], False)
        self.assertEqual(visible["coding"]["source"], "builtin")
        self.assertTrue(visible["coding"]["created_at"].endswith("+00:00"))
        self.assertTrue(visible["coding"]["updated_at"].endswith("+00:00"))

        mounts = skill_service.build_skill_mounts(
            self.session,
            "alice",
            ["research-notes", "qa-playbook"],
        )
        self.assertEqual(
            mounts,
            [
                {
                    "name": "research-notes",
                    "location": str(
                        (
                            self.workspace_root
                            / "alice"
                            / "skills"
                            / "private"
                            / "research-notes"
                        ).resolve()
                    ),
                },
                {
                    "name": "qa-playbook",
                    "location": str(
                        (
                            self.workspace_root
                            / "bob"
                            / "skills"
                            / "shared"
                            / "qa-playbook"
                        ).resolve()
                    ),
                },
            ],
        )

        prompt_block = skill_service.build_selected_skills_prompt_block(
            self.session,
            "alice",
            ["qa-playbook"],
        )
        self.assertIn("### Skill 1: qa-playbook", prompt_block)
        self.assertIn("Shared QA body.", prompt_block)

    def test_shared_skills_are_read_only_for_non_creators(self) -> None:
        """Shared skills should remain editable only by their creator."""
        owner_source = (
            "---\n"
            "name: shared-docs\n"
            "description: Shared docs workflow\n"
            "---\n\n"
            "# shared-docs\n\n"
            "Original shared body.\n"
        )
        skill_service.upsert_user_skill(
            self.session,
            self.alice,
            "shared",
            "shared-docs",
            owner_source,
        )

        shared_payload = skill_service.read_shared_skill(
            self.session,
            "bob",
            "shared-docs",
        )
        self.assertEqual(shared_payload["metadata"]["creator"], "alice")
        self.assertEqual(shared_payload["metadata"]["read_only"], True)

        with self.assertRaises(PermissionError):
            skill_service.upsert_user_skill(
                self.session,
                self.bob,
                "shared",
                "shared-docs",
                owner_source.replace("Original", "Bob edit"),
            )

        with self.assertRaises(PermissionError):
            skill_service.delete_user_skill(
                self.session,
                self.bob,
                "shared",
                "shared-docs",
            )

        with self.assertRaises(PermissionError):
            skill_service.upsert_user_skill(
                self.session,
                self.bob,
                "private",
                "shared-docs",
                owner_source,
            )
