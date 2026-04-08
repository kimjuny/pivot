"""Storage backends for persisted extension artifacts."""

from __future__ import annotations

import shutil
import tarfile
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Protocol

from app.services.binary_storage_service import (
    StoredBinary,
    build_binary_storage_backend,
)


@dataclass(frozen=True)
class StoredArtifact:
    """Metadata returned after one artifact is persisted.

    Attributes:
        storage_backend: Stable backend identifier.
        artifact_key: Object-storage style key used to address the artifact.
        artifact_digest: Stable SHA-256 digest of the stored artifact bytes.
        size_bytes: Total artifact size in bytes.
    """

    storage_backend: str
    artifact_key: str
    artifact_digest: str
    size_bytes: int


class StorageBackend(Protocol):
    """Minimal object-style storage contract for extension artifacts."""

    backend_name: str

    def put_bytes(self, *, payload: bytes, key: str) -> StoredBinary:
        """Persist one local file under a stable storage key."""
        ...

    def read_bytes(self, *, key: str) -> bytes:
        """Return the stored bytes for one artifact key."""
        ...

    def delete(self, *, key: str) -> None:
        """Delete one stored artifact key if it exists."""
        ...


class ExtensionArtifactStorageService:
    """Persist and materialize extension package artifacts.

    Why: the persisted artifact should become the long-lived source of truth,
    while the extracted package directory remains a local runtime cache that can
    be recreated on demand in future multi-replica deployments.
    """

    def __init__(self, backend: StorageBackend | None = None) -> None:
        """Store the backend used for artifact persistence."""
        self.backend = backend or build_binary_storage_backend()

    def build_artifact_key(
        self,
        *,
        scope: str,
        name: str,
        version: str,
        manifest_hash: str,
    ) -> str:
        """Return the canonical artifact key for one extension version."""
        return (
            f"extensions/{scope}/{name}/{version}/artifact/" f"{manifest_hash}.tar.gz"
        )

    def store_directory(
        self,
        *,
        source_dir: Path,
        scope: str,
        name: str,
        version: str,
        manifest_hash: str,
    ) -> StoredArtifact:
        """Archive one extension directory and persist it through the backend.

        Args:
            source_dir: Package root directory to archive.
            scope: Extension package scope.
            name: Extension package name.
            version: Extension package version.
            manifest_hash: Stable normalized manifest hash.

        Returns:
            Stored artifact metadata from the backend.
        """
        artifact_key = self.build_artifact_key(
            scope=scope,
            name=name,
            version=version,
            manifest_hash=manifest_hash,
        )
        with NamedTemporaryFile(suffix=".tar.gz", delete=False) as handle:
            archive_path = Path(handle.name)
        try:
            with tarfile.open(archive_path, mode="w:gz") as archive:
                archive.add(source_dir, arcname=".")
            stored_binary = self.backend.put_bytes(
                payload=archive_path.read_bytes(),
                key=artifact_key,
            )
            return StoredArtifact(
                storage_backend=stored_binary.storage_backend,
                artifact_key=stored_binary.storage_key,
                artifact_digest=stored_binary.content_digest,
                size_bytes=stored_binary.size_bytes,
            )
        finally:
            archive_path.unlink(missing_ok=True)

    def materialize_to_directory(
        self,
        *,
        artifact_key: str,
        target_dir: Path,
    ) -> None:
        """Extract one stored extension artifact into a runtime directory.

        Args:
            artifact_key: Canonical key for the persisted artifact.
            target_dir: Empty directory path that receives the extracted files.
        """
        payload = self.backend.read_bytes(key=artifact_key)
        with TemporaryDirectory(prefix="pivot-extension-artifact-") as tmp_root:
            archive_path = Path(tmp_root) / "extension.tar.gz"
            archive_path.write_bytes(payload)
            target_dir.mkdir(parents=True, exist_ok=True)
            with tarfile.open(archive_path, mode="r:gz") as archive:
                self._safe_extract(archive=archive, target_dir=target_dir)

    def delete_artifact(self, *, artifact_key: str) -> None:
        """Delete one persisted extension artifact by key."""
        self.backend.delete(key=artifact_key)

    def ensure_materialized_directory(
        self,
        *,
        artifact_key: str,
        target_dir: Path,
    ) -> Path:
        """Ensure one persisted artifact exists as a local runtime directory.

        Args:
            artifact_key: Canonical key for the persisted artifact.
            target_dir: Directory that should contain the extracted runtime copy.

        Returns:
            The materialized runtime directory path.
        """
        manifest_path = target_dir / "manifest.json"
        if manifest_path.is_file():
            return target_dir

        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)

        target_dir.parent.mkdir(parents=True, exist_ok=True)
        self.materialize_to_directory(
            artifact_key=artifact_key,
            target_dir=target_dir,
        )
        return target_dir

    @staticmethod
    def _safe_extract(*, archive: tarfile.TarFile, target_dir: Path) -> None:
        """Extract one tar archive while rejecting path traversal entries."""
        target_root = target_dir.resolve()
        for member in archive.getmembers():
            member_path = (target_dir / member.name).resolve()
            if member_path != target_root and target_root not in member_path.parents:
                raise ValueError("Extension artifact contains an unsafe archive path.")
        archive.extractall(target_dir)
