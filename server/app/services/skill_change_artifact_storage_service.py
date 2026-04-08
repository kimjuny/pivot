"""Canonical storage helpers for staged skill change submissions."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from app.services.binary_storage_service import build_binary_storage_backend


@dataclass(frozen=True, slots=True)
class StoredSkillChangeArtifact:
    """Metadata returned after one staged submission archive is persisted."""

    storage_backend: str
    storage_key: str
    content_digest: str
    size_bytes: int


class SkillChangeArtifactStorageService:
    """Persist and materialize staged skill change archives."""

    def __init__(self) -> None:
        self.backend = build_binary_storage_backend()

    @staticmethod
    def build_artifact_key(*, username: str, submission_id: int) -> str:
        """Return the canonical storage key for one staged skill submission."""
        return f"users/{username}/skills/.submissions/{submission_id}/snapshot.zip"

    def store_archive(
        self,
        *,
        username: str,
        submission_id: int,
        archive_bytes: bytes,
    ) -> StoredSkillChangeArtifact:
        """Persist one staged submission archive through shared storage."""
        stored_binary = self.backend.put_bytes(
            payload=archive_bytes,
            key=self.build_artifact_key(
                username=username,
                submission_id=submission_id,
            ),
        )
        return StoredSkillChangeArtifact(
            storage_backend=stored_binary.storage_backend,
            storage_key=stored_binary.storage_key,
            content_digest=stored_binary.content_digest,
            size_bytes=stored_binary.size_bytes,
        )

    def materialize_to_directory(
        self,
        *,
        storage_key: str,
        target_dir: Path,
    ) -> Path:
        """Extract one staged submission archive into the requested directory."""
        payload = self.backend.read_bytes(key=storage_key)
        with TemporaryDirectory(prefix="pivot-skill-submission-") as tmp_root:
            extracted_root = Path(tmp_root) / "snapshot"
            extracted_root.mkdir(parents=True, exist_ok=True)
            with ZipFile(BytesIO(payload)) as archive:
                self._safe_extract(archive=archive, target_dir=extracted_root)
            if target_dir.exists():
                shutil.rmtree(target_dir, ignore_errors=True)
            target_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(extracted_root, target_dir)
        return target_dir

    def delete_artifact(self, *, storage_key: str) -> None:
        """Delete one stored staged submission archive."""
        self.backend.delete(key=storage_key)

    @staticmethod
    def _safe_extract(*, archive: ZipFile, target_dir: Path) -> None:
        """Extract one zip archive while rejecting path traversal entries."""
        target_root = target_dir.resolve()
        for info in archive.infolist():
            destination = (target_dir / info.filename).resolve()
            if destination != target_root and target_root not in destination.parents:
                raise ValueError("Skill submission archive contains an unsafe path.")
        archive.extractall(target_dir)
