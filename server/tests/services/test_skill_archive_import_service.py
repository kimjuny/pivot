"""Tests for compressed skill archive imports."""

from __future__ import annotations

import sys
import tempfile
import unittest
from importlib import import_module
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from sqlmodel import Session, SQLModel, create_engine

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

import_module("app.models")
User = import_module("app.models.user").User
skill_service = import_module("app.services.skill_service")


class _FakeSkillArtifactStorageService:
    """Avoid writing archive artifacts outside the test workspace."""

    def store_directory(
        self,
        *,
        source_dir: Path,
        username: str,
        skill_name: str,
    ):
        del source_dir, username, skill_name
        return skill_service.StoredSkillArtifact(
            storage_backend="test",
            artifact_key="test-key",
            artifact_digest="test-digest",
            size_bytes=1,
        )


class SkillArchiveImportServiceTestCase(unittest.TestCase):
    """Validate archive import behavior without the legacy skill-service fixture."""

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
        self.artifact_patch = patch.object(
            skill_service,
            "SkillArtifactStorageService",
            _FakeSkillArtifactStorageService,
        )
        self.workspace_patch.start()
        self.artifact_patch.start()
        self.alice = User(username="alice", password_hash="hash")
        self.session.add(self.alice)
        self.session.commit()
        self.session.refresh(self.alice)

    def tearDown(self) -> None:
        """Release temporary test state."""
        self.artifact_patch.stop()
        self.workspace_patch.stop()
        self.session.close()
        self.tmpdir.cleanup()

    def test_archive_import_extracts_wrapped_skill_directory(self) -> None:
        """Archive imports should accept a zipped skill folder and report progress."""
        archive_path = Path(self.tmpdir.name) / "ppt-master.zip"
        with ZipFile(archive_path, "w") as archive:
            archive.writestr(
                "ppt-master/SKILL.md",
                (
                    "---\n"
                    "name: ppt-master\n"
                    "description: Deck workflow\n"
                    "---\n\n"
                    "# ppt-master\n\n"
                    "Create decks.\n"
                ),
            )
            archive.writestr("ppt-master/templates/base.txt", "template\n")

        progress_events: list[tuple[str, str, int, str | None]] = []
        metadata = skill_service.install_archive_skill(
            self.session,
            self.alice,
            archive_path=archive_path,
            archive_filename="ppt-master.zip",
            kind="private",
            skill_name="ppt-master",
            progress=lambda stage, label, percent, detail: progress_events.append(
                (stage, label, percent, detail)
            ),
        )

        self.assertEqual(metadata["source"], "bundle")
        imported_dir = self.workspace_root / "users" / "alice" / "skills" / "ppt-master"
        self.assertTrue((imported_dir / "templates" / "base.txt").exists())
        self.assertIn("extracting", [event[0] for event in progress_events])
        self.assertIn("saving_artifact", [event[0] for event in progress_events])
