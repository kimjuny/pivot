"""Tests for the database-backed skill registry service."""

import json
import sys
import tempfile
import unittest
from importlib import import_module
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from sqlmodel import Session, SQLModel, create_engine, select

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

import_module("app.models")
Skill = import_module("app.models.skill").Skill
User = import_module("app.models.user").User
github_skill_module = import_module("app.orchestration.skills.github")
GitHubSkillCandidate = github_skill_module.GitHubSkillCandidate
GitHubSkillProbeResult = github_skill_module.GitHubSkillProbeResult
skill_service = import_module("app.services.skill_service")
BundleImportFile = skill_service.BundleImportFile


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

        self.alice = User(username="alice", password_hash="hash", role_id=1)
        self.bob = User(username="bob", password_hash="hash", role_id=1)
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

    def _user_skill_dir(self, username: str, name: str) -> Path:
        """Return the unified on-disk directory for one user-owned skill."""
        return self.workspace_root / username / "skills" / name

    def _build_skill_archive(self, directory_name: str, source: str) -> bytes:
        """Create a GitHub-like repository zipball for one skill folder."""
        buffer = BytesIO()
        with ZipFile(buffer, "w") as archive:
            archive.writestr(
                f"example-repo-abcdef/skills/{directory_name}/SKILL.md",
                source,
            )
            archive.writestr(
                f"example-repo-abcdef/skills/{directory_name}/scripts/install.sh",
                "#!/bin/sh\necho install\n",
            )
        return buffer.getvalue()

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
        self.assertEqual(visible["qa-playbook"]["kind"], "shared")
        self.assertEqual(visible["research-notes"]["source"], "manual")
        self.assertEqual(visible["team-writer"]["source"], "manual")
        self.assertTrue(visible["coding"]["created_at"].endswith("+00:00"))
        self.assertTrue(visible["coding"]["updated_at"].endswith("+00:00"))
        self.assertTrue(visible["qa-playbook"]["created_at"].endswith("+00:00"))
        self.assertTrue(visible["qa-playbook"]["updated_at"].endswith("+00:00"))

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
                        self._user_skill_dir("alice", "research-notes").resolve()
                    ),
                },
                {
                    "name": "qa-playbook",
                    "location": str(
                        self._user_skill_dir("bob", "qa-playbook").resolve()
                    ),
                },
            ],
        )

        prompt_block = skill_service.build_skills_metadata_prompt_json(
            self.session,
            "alice",
            json.dumps(["qa-playbook"]),
        )
        self.assertEqual(
            json.loads(prompt_block),
            [
                {
                    "name": "qa-playbook",
                    "description": "Bob shared QA workflow",
                    "path": "/workspace/skills/qa-playbook/SKILL.md",
                }
            ],
        )

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

    def test_imported_private_skill_is_available_immediately(self) -> None:
        """Imported private skills should become runtime-visible immediately."""
        probe_result = GitHubSkillProbeResult(
            owner="acme",
            repo="pivot-skills",
            html_url="https://github.com/acme/pivot-skills",
            description="Imported skill catalog",
            default_ref="main",
            selected_ref="main",
            branches=("main",),
            tags=("v1.0.0",),
            has_skills_dir=True,
            candidates=(
                GitHubSkillCandidate(
                    directory_name="research-kit",
                    entry_filename="SKILL.md",
                    suggested_name="research-kit",
                    description="Imported research workflow",
                ),
            ),
        )
        archive_bytes = self._build_skill_archive(
            "research-kit",
            (
                "---\n"
                "name: research-kit\n"
                "description: Imported research workflow\n"
                "---\n\n"
                "# research-kit\n\n"
                "Use imported guidance.\n"
            ),
        )

        with (
            patch.object(
                skill_service,
                "probe_github_skill_repository",
                return_value=probe_result,
            ),
            patch.object(
                skill_service,
                "download_github_repository_archive",
                return_value=archive_bytes,
            ),
        ):
            metadata = skill_service.install_github_skill(
                self.session,
                self.alice,
                github_url="https://github.com/acme/pivot-skills",
                ref="main",
                ref_type="branch",
                kind="private",
                remote_directory_name="research-kit",
                skill_name="research-kit-imported",
            )

        self.assertEqual(metadata["github_ref_type"], "branch")
        self.assertEqual(metadata["github_skill_path"], "skills/research-kit")
        self.assertEqual(metadata["source"], "network")
        self.assertEqual(metadata["imported"], True)

        imported_dir = self._user_skill_dir("alice", "research-kit-imported")
        self.assertTrue((imported_dir / "scripts" / "install.sh").exists())

        imported_source = skill_service.read_user_skill(
            self.session,
            "alice",
            "private",
            "research-kit-imported",
        )["source"]
        self.assertIn("name: research-kit-imported", imported_source)

        visible_skill_names = {
            item["name"]
            for item in skill_service.list_visible_skills(self.session, "alice")
        }
        self.assertIn("research-kit-imported", visible_skill_names)
        mounts = skill_service.build_skill_mounts(
            self.session,
            "alice",
            ["research-kit-imported"],
        )
        self.assertEqual(mounts[0]["name"], "research-kit-imported")
        prompt_block = skill_service.build_skills_metadata_prompt_json(
            self.session,
            "alice",
            json.dumps(["research-kit-imported"]),
        )
        self.assertEqual(
            json.loads(prompt_block),
            [
                {
                    "name": "research-kit-imported",
                    "description": "Imported research workflow",
                    "path": "/workspace/skills/research-kit-imported/SKILL.md",
                }
            ],
        )

    def test_build_mandatory_skills_prompt_json_reads_full_skill_content(self) -> None:
        """Mandatory skill prompt payloads should inline the full markdown body."""
        self._write_skill(
            self.workspace_root / "alice" / "skills",
            "sample-skill",
            "Sample mandatory skill",
            "Follow the sample workflow carefully.",
        )

        prompt_block = skill_service.build_mandatory_skills_prompt_json(
            self.session,
            "alice",
            raw_skill_ids=json.dumps(["sample-skill"]),
            selected_skill_names=["sample-skill"],
        )

        self.assertEqual(
            json.loads(prompt_block),
            [
                {
                    "name": "sample-skill",
                    "description": "Sample mandatory skill",
                    "path": "/workspace/skills/sample-skill/SKILL.md",
                    "content": (
                        "---\n"
                        "name: sample-skill\n"
                        "description: Sample mandatory skill\n"
                        "---\n\n"
                        "# sample-skill\n\n"
                        "Follow the sample workflow carefully.\n"
                    ),
                }
            ],
        )

    def test_shared_import_is_visible_immediately(self) -> None:
        """Imported shared skills should be visible to other users immediately."""
        probe_result = GitHubSkillProbeResult(
            owner="acme",
            repo="pivot-skills",
            html_url="https://github.com/acme/pivot-skills",
            description="Imported skill catalog",
            default_ref="main",
            selected_ref="main",
            branches=("main",),
            tags=(),
            has_skills_dir=True,
            candidates=(
                GitHubSkillCandidate(
                    directory_name="team-handbook",
                    entry_filename="SKILL.md",
                    suggested_name="team-handbook",
                    description="Shared onboarding guide",
                ),
            ),
        )
        archive_bytes = self._build_skill_archive(
            "team-handbook",
            (
                "---\n"
                "name: team-handbook\n"
                "description: Shared onboarding guide\n"
                "---\n\n"
                "# team-handbook\n\n"
                "Shared import body.\n"
            ),
        )

        with (
            patch.object(
                skill_service,
                "probe_github_skill_repository",
                return_value=probe_result,
            ),
            patch.object(
                skill_service,
                "download_github_repository_archive",
                return_value=archive_bytes,
            ),
        ):
            skill_service.install_github_skill(
                self.session,
                self.alice,
                github_url="https://github.com/acme/pivot-skills",
                ref="main",
                ref_type="branch",
                kind="shared",
                remote_directory_name="team-handbook",
                skill_name="team-handbook",
            )

        alice_shared = {
            item["name"]: item
            for item in skill_service.list_shared_skills(self.session, "alice")
        }
        bob_shared = {
            item["name"]: item
            for item in skill_service.list_shared_skills(self.session, "bob")
        }
        self.assertIn("team-handbook", alice_shared)
        self.assertIn("team-handbook", bob_shared)
        shared_payload = skill_service.read_shared_skill(
            self.session,
            "bob",
            "team-handbook",
        )
        self.assertIn("Shared import body.", shared_payload["source"])
        self.assertEqual(bob_shared["team-handbook"]["source"], "network")

    def test_bundle_import_installs_local_skill_immediately(self) -> None:
        """Bundle imports should keep the directory tree and mark the source."""
        metadata = skill_service.install_bundle_skill(
            self.session,
            self.alice,
            bundle_name="local-research-kit",
            kind="private",
            skill_name="local-research-kit",
            files=[
                BundleImportFile(
                    relative_path="SKILL.md",
                    content=(
                        b"---\n"
                        b"name: local-research-kit\n"
                        b"description: Local workflow\n"
                        b"---\n\n"
                        b"# local-research-kit\n\n"
                        b"Local guidance.\n"
                    ),
                ),
                BundleImportFile(
                    relative_path="scripts/setup.sh",
                    content=b"#!/bin/sh\necho setup\n",
                ),
            ],
        )

        self.assertEqual(metadata["source"], "bundle")

        imported_dir = self._user_skill_dir("alice", "local-research-kit")
        self.assertTrue((imported_dir / "scripts" / "setup.sh").exists())
        imported_source = skill_service.read_user_skill(
            self.session,
            "alice",
            "private",
            "local-research-kit",
        )["source"]
        self.assertIn("name: local-research-kit", imported_source)

    def test_sync_registry_migrates_legacy_kind_directories(self) -> None:
        """Legacy private/shared folders should migrate into the unified root."""
        legacy_private_root = self.workspace_root / "alice" / "skills" / "private"
        legacy_shared_root = self.workspace_root / "alice" / "skills" / "shared"
        self._write_skill(
            legacy_private_root,
            "deep-research",
            "Legacy private workflow",
            "Private body.",
            filename="SKILL.md",
        )
        self._write_skill(
            legacy_shared_root,
            "team-notes",
            "Legacy shared workflow",
            "Shared body.",
            filename="team-notes.md",
        )

        skill_service.sync_skill_registry(self.session)

        migrated_private_dir = self._user_skill_dir("alice", "deep-research")
        migrated_shared_dir = self._user_skill_dir("alice", "team-notes")
        self.assertTrue((migrated_private_dir / "deep-research.md").exists())
        self.assertTrue((migrated_shared_dir / "team-notes.md").exists())
        self.assertFalse((legacy_private_root / "deep-research").exists())
        self.assertFalse((legacy_shared_root / "team-notes").exists())

        visible = {
            item["name"]: item
            for item in skill_service.list_visible_skills(self.session, "alice")
        }
        self.assertEqual(visible["deep-research"]["kind"], "private")
        self.assertEqual(visible["team-notes"]["kind"], "shared")

    def test_bundle_import_requires_top_level_skill_markdown(self) -> None:
        """Bundle imports should fail fast when the folder lacks SKILL.md."""
        with self.assertRaises(ValueError):
            skill_service.install_bundle_skill(
                self.session,
                self.alice,
                bundle_name="broken-skill",
                kind="private",
                skill_name="broken-skill",
                files=[
                    BundleImportFile(
                        relative_path="notes/readme.md",
                        content=b"# missing skill entry\n",
                    )
                ],
            )

    def test_probe_github_import_marks_conflicting_names(self) -> None:
        """Probe results should flag globally conflicting suggested skill names."""
        skill_service.upsert_user_skill(
            self.session,
            self.alice,
            "private",
            "research",
            (
                "---\n"
                "name: research\n"
                "description: Existing workflow\n"
                "---\n\n"
                "# research\n"
            ),
        )
        probe_result = GitHubSkillProbeResult(
            owner="acme",
            repo="pivot-skills",
            html_url="https://github.com/acme/pivot-skills",
            description="Imported skill catalog",
            default_ref="main",
            selected_ref="main",
            branches=("main",),
            tags=(),
            has_skills_dir=True,
            candidates=(
                GitHubSkillCandidate(
                    directory_name="research-folder",
                    entry_filename="SKILL.md",
                    suggested_name="research",
                    description="Would conflict with an existing name",
                ),
            ),
        )

        with patch.object(
            skill_service,
            "probe_github_skill_repository",
            return_value=probe_result,
        ):
            payload = skill_service.probe_github_skill_import(
                self.session,
                self.alice,
                "https://github.com/acme/pivot-skills",
            )

        self.assertEqual(payload["candidates"][0]["suggested_name"], "research")
        self.assertEqual(payload["candidates"][0]["name_conflict"], True)
