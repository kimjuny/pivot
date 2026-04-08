"""Services for staging and applying sandbox-authored skill changes."""

from __future__ import annotations

import base64
import json
import posixpath
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING
from zipfile import ZipFile

from app.db.session import managed_session
from app.models.skill import Skill
from app.models.skill_change_submission import SkillChangeSubmission
from app.models.user import User
from app.orchestration.skills.skill_files import parse_front_matter
from app.services.sandbox_service import get_sandbox_service
from app.services.skill_change_artifact_storage_service import (
    SkillChangeArtifactStorageService,
)
from app.services.skill_service import (
    _detect_skill_entry_filename,
    _validate_skill_name,
    apply_private_skill_directory,
    sync_skill_registry,
)
from sqlmodel import Session, select

if TYPE_CHECKING:
    from app.services.workspace_storage_service import WorkspaceMountSpec

_SANDBOX_SKILLS_ROOT = "/workspace/skills"
_MAX_SNAPSHOT_FILE_COUNT = 200
_MAX_SNAPSHOT_TOTAL_BYTES = 8 * 1024 * 1024
_MAX_SNAPSHOT_ARCHIVE_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class SkillChangeApprovalRequest:
    """Structured approval payload returned to the tool/frontend layer."""

    submission_id: int
    skill_name: str
    change_type: str
    question: str
    message: str
    file_count: int
    total_bytes: int

    def to_dict(self) -> dict[str, object]:
        """Serialize the approval request for tool responses and clarify payloads."""
        return {
            "submission_id": self.submission_id,
            "skill_name": self.skill_name,
            "change_type": self.change_type,
            "question": self.question,
            "message": self.message,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
        }


def _normalize_draft_dir_path(draft_dir_path: str) -> str:
    """Validate and normalize one sandbox-local draft skill directory path."""
    raw = draft_dir_path.strip()
    if not raw:
        raise ValueError("draft_skill_dir_path cannot be empty.")

    if raw.startswith("/"):
        normalized = posixpath.normpath(raw)
    else:
        normalized = posixpath.normpath(posixpath.join("/workspace", raw))

    if not normalized.startswith(f"{_SANDBOX_SKILLS_ROOT}/"):
        raise ValueError("draft_skill_dir_path must point inside /workspace/skills.")

    relative = posixpath.relpath(normalized, _SANDBOX_SKILLS_ROOT)
    if relative in {".", ".."}:
        raise ValueError("draft_skill_dir_path must point to one skill directory.")
    if "/" in relative:
        raise ValueError(
            "draft_skill_dir_path must point to the top-level skill directory only."
        )
    _validate_skill_name(relative)
    return normalized


def _sandbox_export_command(draft_dir_path: str) -> list[str]:
    """Build the sandbox command that emits one draft directory as JSON."""
    script = """
import base64
import io
import json
import pathlib
import sys
import zipfile

root = pathlib.Path(sys.argv[1])
max_files = int(sys.argv[2])
max_total_bytes = int(sys.argv[3])
if not root.exists() or not root.is_dir():
    raise SystemExit("Draft skill directory does not exist.")

archive = io.BytesIO()
file_count = 0
total_bytes = 0
with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise SystemExit("Skill drafts cannot contain symbolic links.")
        if not path.is_file():
            continue
        data = path.read_bytes()
        file_count += 1
        total_bytes += len(data)
        if file_count > max_files:
            raise SystemExit("Skill draft contains too many files.")
        if total_bytes > max_total_bytes:
            raise SystemExit("Skill draft is too large.")
        zf.writestr(path.relative_to(root).as_posix(), data)

payload = {
    "archive_b64": base64.b64encode(archive.getvalue()).decode("ascii"),
    "file_count": file_count,
    "total_bytes": total_bytes,
}
print(json.dumps(payload))
""".strip()
    return [
        "python3",
        "-c",
        script,
        draft_dir_path,
        str(_MAX_SNAPSHOT_FILE_COUNT),
        str(_MAX_SNAPSHOT_TOTAL_BYTES),
    ]


def _export_draft_snapshot(
    *,
    username: str,
    mount_spec: WorkspaceMountSpec,
    draft_dir_path: str,
) -> tuple[bytes, int, int]:
    """Archive one sandbox draft skill directory and return its bytes."""
    result = get_sandbox_service().exec(
        username=username,
        mount_spec=mount_spec,
        cmd=_sandbox_export_command(draft_dir_path),
    )
    if result.exit_code != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise ValueError(f"Failed to read draft skill directory: {message}")

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("Sandbox returned an invalid skill draft snapshot.") from exc

    archive_b64 = payload.get("archive_b64")
    file_count = payload.get("file_count")
    total_bytes = payload.get("total_bytes")
    if not isinstance(archive_b64, str):
        raise ValueError("Sandbox snapshot is missing archive data.")
    if not isinstance(file_count, int) or not isinstance(total_bytes, int):
        raise ValueError("Sandbox snapshot is missing size metadata.")

    archive_bytes = base64.b64decode(archive_b64.encode("ascii"), validate=True)
    if len(archive_bytes) > _MAX_SNAPSHOT_ARCHIVE_BYTES:
        raise ValueError("Skill draft archive is too large to stage.")
    return archive_bytes, file_count, total_bytes


def _extract_snapshot_archive(archive_bytes: bytes, destination: Path) -> None:
    """Extract one archived skill snapshot into a staging directory."""
    destination.mkdir(parents=True, exist_ok=True)
    with ZipFile(BytesIO(archive_bytes)) as archive:
        for info in archive.infolist():
            relative = PurePosixPath(info.filename)
            if info.is_dir():
                continue
            if any(part in {"", ".", ".."} for part in relative.parts):
                raise ValueError("Skill draft archive contains an unsafe file path.")
            target_path = destination.joinpath(*relative.parts)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(archive.read(info))


def _build_submission_details(
    *,
    skill_name: str,
    snapshot_dir: Path,
    file_count: int,
    total_bytes: int,
) -> dict[str, object]:
    """Build compact preview metadata stored with one submission row."""
    entry_filename = _detect_skill_entry_filename(
        snapshot_dir,
        label=f"Skill draft '{skill_name}'",
    )
    source = (snapshot_dir / entry_filename).read_text(encoding="utf-8")
    front_matter = parse_front_matter(source)
    description = front_matter.get("description", "")
    return {
        "entry_filename": entry_filename,
        "description": description,
        "file_count": file_count,
        "total_bytes": total_bytes,
    }


def _resolve_submission_skill_name(
    *,
    draft_dir_path: str,
    snapshot_dir: Path,
) -> str:
    """Infer the target skill name from the staged snapshot contents."""
    entry_filename = _detect_skill_entry_filename(
        snapshot_dir,
        label="Skill draft",
    )
    source = (snapshot_dir / entry_filename).read_text(encoding="utf-8")
    parsed = parse_front_matter(source)
    candidate = parsed.get("name") or PurePosixPath(draft_dir_path).name
    _validate_skill_name(candidate)
    return candidate


def _approval_question(*, skill_name: str, change_type: str) -> str:
    """Build the user-facing approval prompt shown by the chat UI."""
    action_text = "create" if change_type == "create" else "update"
    return f"Approve the request to {action_text} private skill `{skill_name}`?"


def _build_pending_user_action(
    *,
    submission_id: int,
    skill_name: str,
    change_type: str,
    message: str,
    file_count: int,
    total_bytes: int,
) -> dict[str, object]:
    """Build the system-owned waiting action persisted on the task row."""
    approval_request = SkillChangeApprovalRequest(
        submission_id=submission_id,
        skill_name=skill_name,
        change_type=change_type,
        question=_approval_question(
            skill_name=skill_name,
            change_type=change_type,
        ),
        message=message,
        file_count=file_count,
        total_bytes=total_bytes,
    )
    return {
        "kind": "skill_change_approval",
        "approval_request": approval_request.to_dict(),
    }


def stage_skill_change_submission(
    session: Session,
    current_user: User,
    *,
    agent_id: int,
    mount_spec: WorkspaceMountSpec,
    draft_dir_path: str,
    message: str = "",
) -> dict[str, object]:
    """Freeze one sandbox-authored skill draft into a pending submission.

    Args:
        session: Active database session.
        current_user: Authenticated owner of the target private skill namespace.
        agent_id: Agent workspace that holds the draft.
        mount_spec: Runtime mount contract for the active workspace.
        draft_dir_path: Sandbox-local path under ``/workspace/skills``.
        message: Optional agent-authored explanation shown to the user.

    Returns:
        Structured submission metadata plus approval request payload.
    """
    if current_user.id is None:
        raise ValueError("Current user must be persisted before staging skills.")

    normalized_path = _normalize_draft_dir_path(draft_dir_path)
    archive_bytes, file_count, total_bytes = _export_draft_snapshot(
        username=current_user.username,
        mount_spec=mount_spec,
        draft_dir_path=normalized_path,
    )

    submission = SkillChangeSubmission(
        creator_id=current_user.id,
        agent_id=agent_id,
        skill_name="pending",
        target_kind="private",
        change_type="create",
        status="pending",
        sandbox_draft_path=normalized_path,
        storage_backend="pending",
        storage_key=None,
        summary=message.strip(),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(submission)
    session.commit()
    session.refresh(submission)

    artifact_storage = SkillChangeArtifactStorageService()
    try:
        with TemporaryDirectory(prefix="pivot-skill-change-stage-") as tmp_root:
            snapshot_dir = Path(tmp_root) / "source"
            _extract_snapshot_archive(archive_bytes, snapshot_dir)
            skill_name = _resolve_submission_skill_name(
                draft_dir_path=normalized_path,
                snapshot_dir=snapshot_dir,
            )
            sync_skill_registry(session)
            existing = session.exec(
                select(Skill).where(Skill.name == skill_name)
            ).first()
            if existing is None:
                change_type = "create"
            else:
                if existing.creator_id != current_user.id:
                    raise PermissionError(
                        f"Skill '{skill_name}' is owned by another creator."
                    )
                if existing.kind != "private":
                    raise PermissionError(
                        f"Skill '{skill_name}' is a {existing.kind} skill and cannot be "
                        "changed through agent submissions."
                    )
                change_type = "update"

            details = _build_submission_details(
                skill_name=skill_name,
                snapshot_dir=snapshot_dir,
                file_count=file_count,
                total_bytes=total_bytes,
            )
        stored_artifact = artifact_storage.store_archive(
            username=current_user.username,
            submission_id=submission.id or 0,
            archive_bytes=archive_bytes,
        )
        submission.skill_name = skill_name
        submission.change_type = change_type
        submission.storage_backend = stored_artifact.storage_backend
        submission.storage_key = stored_artifact.storage_key
        submission.details_json = json.dumps(details, ensure_ascii=False)
        submission.updated_at = datetime.now(UTC)
        session.add(submission)
        session.commit()
        session.refresh(submission)
    except Exception:
        session.delete(submission)
        session.commit()
        raise

    pending_user_action = _build_pending_user_action(
        submission_id=submission.id or 0,
        skill_name=submission.skill_name,
        change_type=submission.change_type,
        message=submission.summary,
        file_count=file_count,
        total_bytes=total_bytes,
    )
    return {
        "submission_id": submission.id or 0,
        "skill_name": submission.skill_name,
        "target_kind": submission.target_kind,
        "change_type": submission.change_type,
        "status": "pending_approval",
        "pending_user_action": pending_user_action,
    }


def submit_skill_change_for_agent(
    *,
    username: str,
    agent_id: int,
    mount_spec: WorkspaceMountSpec,
    skill_path: str,
    message: str = "",
) -> dict[str, object]:
    """Stage one sandbox-authored skill change for the current agent user.

    Why: tool handlers should stay thin and delegate persistence concerns to the
    service layer so database access patterns remain centralized and testable.

    Args:
        username: Authenticated username from the tool execution context.
        agent_id: Agent workspace that authored the draft.
        mount_spec: Runtime mount contract for the active workspace.
        skill_path: Sandbox-local skill directory under ``/workspace/skills``.
        message: Optional reviewer-facing explanation of the staged change.

    Returns:
        Structured pending approval payload for the submitted skill change.

    Raises:
        ValueError: If the user cannot be resolved or the draft is invalid.
    """
    with managed_session() as session:
        current_user = session.exec(
            select(User).where(User.username == username)
        ).first()
        if current_user is None:
            raise ValueError(f"User '{username}' not found.")

        return stage_skill_change_submission(
            session,
            current_user,
            agent_id=agent_id,
            mount_spec=mount_spec,
            draft_dir_path=skill_path,
            message=message,
        )


def apply_skill_change_submission(
    session: Session,
    current_user: User,
    *,
    submission_id: int,
    decision: str,
) -> dict[str, object]:
    """Approve or reject one staged skill change submission.

    Args:
        session: Active database session.
        current_user: Authenticated owner of the submission.
        submission_id: Primary key of the staged submission.
        decision: ``approve`` or ``reject``.

    Returns:
        Structured outcome payload suitable for tool responses.
    """
    if current_user.id is None:
        raise ValueError("Current user must be persisted before reviewing skills.")
    normalized_decision = decision.strip().lower()
    if normalized_decision not in {"approve", "reject"}:
        raise ValueError("decision must be either 'approve' or 'reject'.")

    submission = session.get(SkillChangeSubmission, submission_id)
    if submission is None:
        raise FileNotFoundError(f"Skill change submission #{submission_id} not found.")
    if submission.creator_id != current_user.id:
        raise PermissionError("This skill change submission belongs to another user.")
    if submission.status != "pending":
        raise ValueError(
            f"Skill change submission #{submission_id} is already {submission.status}."
        )

    if normalized_decision == "reject":
        submission.status = "rejected"
        submission.reviewed_at = datetime.now(UTC)
        submission.updated_at = datetime.now(UTC)
        session.add(submission)
        session.commit()
        return {
            "submission_id": submission.id or 0,
            "skill_name": submission.skill_name,
            "status": submission.status,
            "message": f"Rejected skill change submission #{submission.id}.",
        }

    if submission.storage_key is None:
        raise ValueError(
            f"Skill change submission #{submission_id} has no staged artifact."
        )

    with TemporaryDirectory(prefix="pivot-skill-change-apply-") as tmp_root:
        snapshot_dir = Path(tmp_root) / "source"
        SkillChangeArtifactStorageService().materialize_to_directory(
            storage_key=submission.storage_key,
            target_dir=snapshot_dir,
        )
        metadata = apply_private_skill_directory(
            session,
            current_user,
            skill_name=submission.skill_name,
            source_dir=snapshot_dir,
            source="agent",
        )
    submission.status = "applied"
    submission.reviewed_at = datetime.now(UTC)
    submission.updated_at = datetime.now(UTC)
    session.add(submission)
    session.commit()
    return {
        "submission_id": submission.id or 0,
        "skill_name": submission.skill_name,
        "status": submission.status,
        "metadata": metadata,
        "message": f"Applied private skill '{submission.skill_name}'.",
    }
