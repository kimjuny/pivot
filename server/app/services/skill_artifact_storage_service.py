"""Archive-based canonical storage helpers for user skill bundles."""

from __future__ import annotations

import shutil
import tarfile
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory

from app.services.binary_storage_service import build_binary_storage_backend


@dataclass(frozen=True, slots=True)
class StoredSkillArtifact:
    """Metadata returned after one skill bundle is persisted."""

    storage_backend: str
    storage_key: str
    content_digest: str
    size_bytes: int


class SkillArtifactStorageService:
    """Persist and materialize user skill bundles through the binary backend."""

    def __init__(self) -> None:
        self.backend = build_binary_storage_backend()

    @staticmethod
    def build_artifact_key(*, username: str, skill_name: str) -> str:
        """Return the canonical storage key for one user skill bundle."""
        return f"pivot/skills/users/{username}/{skill_name}/artifact/skill.tar.gz"

    def store_directory(
        self,
        *,
        username: str,
        skill_name: str,
        source_dir: Path,
    ) -> StoredSkillArtifact:
        """Archive one skill directory and persist it through shared storage."""
        artifact_key = self.build_artifact_key(username=username, skill_name=skill_name)
        with NamedTemporaryFile(suffix=".tar.gz", delete=False) as handle:
            archive_path = Path(handle.name)
        try:
            with tarfile.open(archive_path, mode="w:gz") as archive:
                archive.add(source_dir, arcname=".")
            stored_binary = self.backend.put_bytes(
                payload=archive_path.read_bytes(),
                key=artifact_key,
            )
            return StoredSkillArtifact(
                storage_backend=stored_binary.storage_backend,
                storage_key=stored_binary.storage_key,
                content_digest=stored_binary.content_digest,
                size_bytes=stored_binary.size_bytes,
            )
        finally:
            archive_path.unlink(missing_ok=True)

    def materialize_to_directory(
        self,
        *,
        storage_key: str,
        target_dir: Path,
    ) -> Path:
        """Replace one local skill cache directory from stored bundle bytes."""
        payload = self.backend.read_bytes(key=storage_key)
        with TemporaryDirectory(prefix="pivot-skill-artifact-") as tmp_root:
            archive_path = Path(tmp_root) / "skill.tar.gz"
            extracted_root = Path(tmp_root) / "skill"
            archive_path.write_bytes(payload)
            extracted_root.mkdir(parents=True, exist_ok=True)
            with tarfile.open(archive_path, mode="r:gz") as archive:
                self._safe_extract(archive=archive, target_dir=extracted_root)
            if target_dir.exists():
                shutil.rmtree(target_dir, ignore_errors=True)
            target_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(extracted_root, target_dir)
        return target_dir

    def delete_artifact(self, *, storage_key: str) -> None:
        """Delete one stored skill bundle."""
        self.backend.delete(key=storage_key)

    @staticmethod
    def _safe_extract(*, archive: tarfile.TarFile, target_dir: Path) -> None:
        """Extract one tar archive while rejecting path traversal entries."""
        target_root = target_dir.resolve()
        for member in archive.getmembers():
            member_path = (target_dir / member.name).resolve()
            if member_path != target_root and target_root not in member_path.parents:
                raise ValueError("Skill artifact contains an unsafe archive path.")
        archive.extractall(target_dir)
