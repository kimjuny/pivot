"""Storage backends for persisted skill artifacts."""

from __future__ import annotations

import hashlib
import tarfile
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

from app.storage import get_resolved_storage_profile


@dataclass(frozen=True)
class StoredSkillArtifact:
    """Metadata returned after one skill bundle is persisted."""

    storage_backend: str
    artifact_key: str
    artifact_digest: str
    size_bytes: int


class SkillArtifactStorageService:
    """Persist skill directories as object-backed tarball artifacts."""

    def __init__(self) -> None:
        """Store the active object-storage provider."""
        self.object_storage = get_resolved_storage_profile().object_storage

    def build_artifact_key(
        self,
        *,
        username: str,
        skill_name: str,
        artifact_digest: str,
    ) -> str:
        """Return the canonical artifact key for one skill directory snapshot."""
        return f"users/{username}/skills/{skill_name}/artifact/{artifact_digest}.tar.gz"

    def store_directory(
        self,
        *,
        source_dir: Path,
        username: str,
        skill_name: str,
    ) -> StoredSkillArtifact:
        """Archive one skill directory and persist it through object storage."""
        with NamedTemporaryFile(suffix=".tar.gz", delete=False) as handle:
            archive_path = Path(handle.name)
        try:
            with tarfile.open(archive_path, mode="w:gz") as archive:
                archive.add(source_dir, arcname=".")

            payload = archive_path.read_bytes()
            artifact_digest = hashlib.sha256(payload).hexdigest()
            artifact_key = self.build_artifact_key(
                username=username,
                skill_name=skill_name,
                artifact_digest=artifact_digest,
            )
            stored = self.object_storage.put_bytes(
                artifact_key,
                payload,
                content_type="application/gzip",
            )
            return StoredSkillArtifact(
                storage_backend=stored.storage_backend,
                artifact_key=stored.object_key,
                artifact_digest=artifact_digest,
                size_bytes=stored.size_bytes,
            )
        finally:
            archive_path.unlink(missing_ok=True)

    def delete_artifact(self, *, artifact_key: str) -> None:
        """Delete one persisted skill artifact by key."""
        self.object_storage.delete(artifact_key)
