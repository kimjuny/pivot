"""Tests for sandbox-authored skill change staging and approval."""

from __future__ import annotations

import base64
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
skill_change_service = import_module("app.services.skill_change_service")
skill_service = import_module("app.services.skill_service")
sandbox_service_module = import_module("app.services.sandbox_service")
Skill = import_module("app.models.skill").Skill
SkillChangeSubmission = import_module(
    "app.models.skill_change_submission"
).SkillChangeSubmission
User = import_module("app.models.user").User
SandboxExecResult = sandbox_service_module.SandboxExecResult


class _FakeSandboxService:
    """Minimal sandbox service stub that returns one archived draft snapshot."""

    def __init__(self, archive_payload: dict[str, object]) -> None:
        self.archive_payload = archive_payload

    def exec(
        self,
        username: str,
        agent_id: int,
        cmd: list[str],
        skills: list[dict[str, str]] | None = None,
        timeout_seconds: int | None = None,
    ) -> SandboxExecResult:
        del username, agent_id, cmd, skills, timeout_seconds
        return SandboxExecResult(
            exit_code=0,
            stdout=json.dumps(self.archive_payload),
            stderr="",
        )


class SkillChangeServiceTestCase(unittest.TestCase):
    """Validate staging and approval of sandbox-authored skill changes."""

    def setUp(self) -> None:
        """Create an isolated database plus temporary workspace roots."""
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)

        self.tmpdir = tempfile.TemporaryDirectory()
        root = Path(self.tmpdir.name)
        self.workspace_root = root / "workspace"
        self.builtin_root = root / "builtin"
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.builtin_root.mkdir(parents=True, exist_ok=True)

        self.skill_workspace_patch = patch.object(
            skill_service, "workspace_root", return_value=self.workspace_root
        )
        self.skill_change_workspace_patch = patch.object(
            skill_change_service, "workspace_root", return_value=self.workspace_root
        )
        self.builtin_patch = patch.object(
            skill_service, "_builtin_skills_dir", return_value=self.builtin_root
        )
        self.skill_workspace_patch.start()
        self.skill_change_workspace_patch.start()
        self.builtin_patch.start()

        self.alice = User(username="alice", password_hash="hash", role_id=1)
        self.session.add(self.alice)
        self.session.commit()
        self.session.refresh(self.alice)

    def tearDown(self) -> None:
        """Release temporary state after each test."""
        self.skill_workspace_patch.stop()
        self.skill_change_workspace_patch.stop()
        self.builtin_patch.stop()
        self.session.close()
        self.tmpdir.cleanup()

    def _build_archive_payload(self, files: dict[str, bytes]) -> dict[str, object]:
        """Pack one in-memory skill directory into the sandbox export payload shape."""
        buffer = BytesIO()
        total_bytes = 0
        with ZipFile(buffer, "w") as archive:
            for relative_path, content in files.items():
                archive.writestr(relative_path, content)
                total_bytes += len(content)

        return {
            "archive_b64": base64.b64encode(buffer.getvalue()).decode("ascii"),
            "file_count": len(files),
            "total_bytes": total_bytes,
        }

    def test_stage_then_apply_new_private_skill(self) -> None:
        """A submitted draft should become a private skill only after approval."""
        payload = self._build_archive_payload(
            {
                "SKILL.md": (
                    b"---\nname: planning-kit\ndescription: Planning helper\n---\n\n"
                    b"# planning-kit\n\nUse planning best practices.\n"
                ),
                "scripts/check.sh": b"#!/bin/sh\necho ok\n",
            }
        )
        fake_sandbox = _FakeSandboxService(payload)

        with patch.object(
            skill_change_service,
            "get_sandbox_service",
            return_value=fake_sandbox,
        ):
            staged = skill_change_service.stage_skill_change_submission(
                self.session,
                self.alice,
                agent_id=7,
                draft_dir_path="/workspace/skills/planning-kit",
                message="Adds a reusable planning workflow.",
            )

            self.assertEqual(staged["status"], "pending_approval")
            self.assertEqual(staged["skill_name"], "planning-kit")
            self.assertEqual(staged["change_type"], "create")
            pending_user_action = staged["pending_user_action"]
            self.assertEqual(pending_user_action["kind"], "skill_change_approval")
            approval_request = pending_user_action["approval_request"]
            self.assertEqual(approval_request["skill_name"], "planning-kit")
            self.assertEqual(
                approval_request["message"],
                "Adds a reusable planning workflow.",
            )

            submission_id = int(staged["submission_id"])
            applied = skill_change_service.apply_skill_change_submission(
                self.session,
                self.alice,
                submission_id=submission_id,
                decision="approve",
            )

        self.assertEqual(applied["status"], "applied")
        skill = self.session.exec(
            select(Skill).where(Skill.name == "planning-kit")
        ).first()
        assert skill is not None
        self.assertIsNotNone(skill)
        self.assertEqual(skill.kind, "private")
        self.assertEqual(skill.source, "agent")
        applied_path = self.workspace_root / "alice" / "skills" / "planning-kit"
        self.assertTrue((applied_path / "scripts" / "check.sh").exists())

        submission = self.session.get(SkillChangeSubmission, submission_id)
        assert submission is not None
        self.assertIsNotNone(submission)
        self.assertEqual(submission.status, "applied")

    def test_stage_then_apply_updates_existing_private_skill(self) -> None:
        """Approving a staged draft should replace an existing private skill bundle."""
        skill_service.upsert_user_skill(
            self.session,
            self.alice,
            "private",
            "research-notes",
            (
                "---\nname: research-notes\ndescription: Original notes\n---\n\n"
                "# research-notes\n\nOriginal body.\n"
            ),
        )

        payload = self._build_archive_payload(
            {
                "SKILL.md": (
                    b"---\nname: research-notes\ndescription: Updated notes\n---\n\n"
                    b"# research-notes\n\nUpdated body.\n"
                ),
                "templates/outline.md": b"## Outline\n",
            }
        )
        fake_sandbox = _FakeSandboxService(payload)

        with patch.object(
            skill_change_service,
            "get_sandbox_service",
            return_value=fake_sandbox,
        ):
            staged = skill_change_service.stage_skill_change_submission(
                self.session,
                self.alice,
                agent_id=9,
                draft_dir_path="/workspace/skills/research-notes",
            )
            self.assertEqual(staged["change_type"], "update")

            skill_change_service.apply_skill_change_submission(
                self.session,
                self.alice,
                submission_id=int(staged["submission_id"]),
                decision="approve",
            )

        skill_dir = self.workspace_root / "alice" / "skills" / "research-notes"
        skill_source = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Updated body.", skill_source)
        self.assertTrue((skill_dir / "templates" / "outline.md").exists())
