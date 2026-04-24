"""Reusable CRUD helpers for files under runtime workspaces."""

from __future__ import annotations

import base64
import mimetypes
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal

from app.services.workspace_service import WorkspaceService

if TYPE_CHECKING:
    from app.models.workspace import Workspace
    from sqlmodel import Session as DBSession


class WorkspaceFileServiceError(Exception):
    """Base error for workspace file operations."""


class WorkspaceFileNotFoundError(WorkspaceFileServiceError):
    """Raised when a requested workspace or file does not exist."""


class WorkspaceFilePermissionError(WorkspaceFileServiceError):
    """Raised when a caller does not own the requested workspace."""


class WorkspaceFileValidationError(WorkspaceFileServiceError):
    """Raised when a path is invalid for workspace-local file operations."""


@dataclass(frozen=True)
class WorkspaceFileTreeEntry:
    """Flat workspace tree entry returned by ``WorkspaceFileService``."""

    path: str
    name: str
    kind: str
    parent_path: str | None = None
    size_bytes: int | None = None


@dataclass(frozen=True)
class WorkspaceFileReadResult:
    """Structured workspace file payload for text or image previews."""

    kind: Literal["text", "image"]
    content: str | None = None
    encoding: Literal["utf-8"] | None = None
    mime_type: str | None = None
    data_base64: str | None = None


@dataclass(frozen=True)
class WorkspaceBinaryFileReadResult:
    """Structured binary file payload for direct download responses."""

    content: bytes
    mime_type: str
    size_bytes: int


@dataclass(frozen=True)
class WorkspaceBinaryFileWriteResult:
    """Binary file metadata returned after one workspace write."""

    path: str
    mime_type: str
    size_bytes: int


class WorkspaceFileService:
    """CRUD-style file access scoped to one owned runtime workspace."""

    def __init__(self, db: DBSession) -> None:
        """Store the active database session.

        Args:
            db: Active database session.
        """
        self.db = db

    def list_tree(
        self,
        *,
        workspace_id: str,
        username: str,
        root_path: str | None = None,
    ) -> list[WorkspaceFileTreeEntry]:
        """Return a recursive flat listing for one owned workspace subtree.

        Args:
            workspace_id: Public workspace identifier.
            username: Authenticated username that must own the workspace.
            root_path: Optional directory path relative to the workspace root.

        Returns:
            Flat list of directory and file entries sorted by path.

        Raises:
            WorkspaceFileNotFoundError: If the workspace or directory is missing.
            WorkspaceFilePermissionError: If the workspace is not owned.
            WorkspaceFileValidationError: If the path is unsafe or not a directory.
        """
        workspace = self._get_workspace_for_owner(
            workspace_id=workspace_id,
            username=username,
        )
        workspace_root = WorkspaceService(self.db).get_workspace_path(workspace).resolve()
        target_dir = self._resolve_workspace_path(
            workspace=workspace,
            relative_path=root_path,
            allow_root=True,
        )
        if not target_dir.exists():
            raise WorkspaceFileNotFoundError("Workspace path does not exist.")
        if not target_dir.is_dir():
            raise WorkspaceFileValidationError("Workspace tree path must be a directory.")

        entries: list[WorkspaceFileTreeEntry] = []
        if target_dir == workspace_root:
            iterator = sorted(workspace_root.rglob("*"), key=lambda path: path.as_posix())
        else:
            iterator = sorted(target_dir.rglob("*"), key=lambda path: path.as_posix())

        for entry_path in iterator:
            relative_path = entry_path.relative_to(workspace_root).as_posix()
            if not relative_path:
                continue
            parent_path = entry_path.parent.relative_to(workspace_root).as_posix()
            if parent_path == ".":
                parent_path = None
            entries.append(
                WorkspaceFileTreeEntry(
                    path=relative_path,
                    name=entry_path.name,
                    kind="directory" if entry_path.is_dir() else "file",
                    parent_path=parent_path,
                    size_bytes=(
                        None if entry_path.is_dir() else entry_path.stat().st_size
                    ),
                )
            )

        return entries

    def list_directory(
        self,
        *,
        workspace_id: str,
        username: str,
        path: str | None = None,
    ) -> list[WorkspaceFileTreeEntry]:
        """Return direct children for one owned workspace directory.

        Args:
            workspace_id: Public workspace identifier.
            username: Authenticated username that must own the workspace.
            path: Optional directory path relative to the workspace root.

        Returns:
            Direct child entries sorted by kind and then name.

        Raises:
            WorkspaceFileNotFoundError: If the workspace or directory is missing.
            WorkspaceFilePermissionError: If the workspace is not owned.
            WorkspaceFileValidationError: If the path is unsafe or not a directory.
        """
        workspace = self._get_workspace_for_owner(
            workspace_id=workspace_id,
            username=username,
        )
        workspace_root = WorkspaceService(self.db).get_workspace_path(workspace).resolve()
        target_dir = self._resolve_workspace_path(
            workspace=workspace,
            relative_path=path,
            allow_root=True,
        )
        if not target_dir.exists():
            raise WorkspaceFileNotFoundError("Workspace path does not exist.")
        if not target_dir.is_dir():
            raise WorkspaceFileValidationError("Workspace directory path is invalid.")

        entries: list[WorkspaceFileTreeEntry] = []
        for entry_path in sorted(
            target_dir.iterdir(),
            key=lambda item: (not item.is_dir(), item.name.lower(), item.name),
        ):
            relative_path = entry_path.relative_to(workspace_root).as_posix()
            parent_path = entry_path.parent.relative_to(workspace_root).as_posix()
            if parent_path == ".":
                parent_path = None
            entries.append(
                WorkspaceFileTreeEntry(
                    path=relative_path,
                    name=entry_path.name,
                    kind="directory" if entry_path.is_dir() else "file",
                    parent_path=parent_path,
                    size_bytes=(
                        None if entry_path.is_dir() else entry_path.stat().st_size
                    ),
                )
            )

        return entries

    def read_text_file(
        self,
        *,
        workspace_id: str,
        username: str,
        path: str,
    ) -> str:
        """Read one UTF-8 text file from an owned workspace.

        Args:
            workspace_id: Public workspace identifier.
            username: Authenticated username that must own the workspace.
            path: Workspace-relative file path.

        Returns:
            Decoded UTF-8 file content.

        Raises:
            WorkspaceFileNotFoundError: If the workspace or file is missing.
            WorkspaceFilePermissionError: If the workspace is not owned.
            WorkspaceFileValidationError: If the path is unsafe or not a file.
            UnicodeDecodeError: If the file is not valid UTF-8.
        """
        workspace = self._get_workspace_for_owner(
            workspace_id=workspace_id,
            username=username,
        )
        target_path = self._resolve_workspace_path(
            workspace=workspace,
            relative_path=path,
            allow_root=False,
        )
        if not target_path.exists():
            raise WorkspaceFileNotFoundError("Workspace file does not exist.")
        if not target_path.is_file():
            raise WorkspaceFileValidationError("Workspace path must be a file.")
        return target_path.read_text(encoding="utf-8")

    def read_file(
        self,
        *,
        workspace_id: str,
        username: str,
        path: str,
    ) -> WorkspaceFileReadResult:
        """Read one previewable workspace file from an owned workspace.

        Args:
            workspace_id: Public workspace identifier.
            username: Authenticated username that must own the workspace.
            path: Workspace-relative file path.

        Returns:
            Structured text or image preview payload.

        Raises:
            WorkspaceFileNotFoundError: If the workspace or file is missing.
            WorkspaceFilePermissionError: If the workspace is not owned.
            WorkspaceFileValidationError: If the path is unsafe, not a file, or
                the file format is not previewable yet.
        """
        workspace = self._get_workspace_for_owner(
            workspace_id=workspace_id,
            username=username,
        )
        target_path = self._resolve_workspace_path(
            workspace=workspace,
            relative_path=path,
            allow_root=False,
        )
        if not target_path.exists():
            raise WorkspaceFileNotFoundError("Workspace file does not exist.")
        if not target_path.is_file():
            raise WorkspaceFileValidationError("Workspace path must be a file.")

        file_bytes = target_path.read_bytes()
        try:
            return WorkspaceFileReadResult(
                kind="text",
                content=file_bytes.decode("utf-8"),
                encoding="utf-8",
            )
        except UnicodeDecodeError:
            mime_type = self._guess_previewable_image_mime_type(target_path)
            if mime_type is None:
                raise WorkspaceFileValidationError(
                    "Workspace file preview is not supported yet."
                ) from None
            return WorkspaceFileReadResult(
                kind="image",
                mime_type=mime_type,
                data_base64=base64.b64encode(file_bytes).decode("ascii"),
            )

    def write_text_file(
        self,
        *,
        workspace_id: str,
        username: str,
        path: str,
        content: str,
    ) -> None:
        """Write one UTF-8 text file inside an owned workspace.

        Args:
            workspace_id: Public workspace identifier.
            username: Authenticated username that must own the workspace.
            path: Workspace-relative file path.
            content: Full UTF-8 file content to persist.

        Raises:
            WorkspaceFileNotFoundError: If the workspace is missing.
            WorkspaceFilePermissionError: If the workspace is not owned.
            WorkspaceFileValidationError: If the path is unsafe.
        """
        workspace = self._get_workspace_for_owner(
            workspace_id=workspace_id,
            username=username,
        )
        target_path = self._resolve_workspace_path(
            workspace=workspace,
            relative_path=path,
            allow_root=False,
        )
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(content, encoding="utf-8")

    def read_binary_file(
        self,
        *,
        workspace_id: str,
        username: str,
        path: str,
    ) -> WorkspaceBinaryFileReadResult:
        """Read one binary file inside an owned workspace.

        Args:
            workspace_id: Public workspace identifier.
            username: Authenticated username that must own the workspace.
            path: Workspace-relative file path.

        Returns:
            File bytes plus normalized MIME metadata.

        Raises:
            WorkspaceFileNotFoundError: If the workspace or file is missing.
            WorkspaceFilePermissionError: If the workspace is not owned.
            WorkspaceFileValidationError: If the path is unsafe or not a file.
        """
        workspace = self._get_workspace_for_owner(
            workspace_id=workspace_id,
            username=username,
        )
        target_path = self._resolve_workspace_path(
            workspace=workspace,
            relative_path=path,
            allow_root=False,
        )
        if not target_path.exists():
            raise WorkspaceFileNotFoundError("Workspace file does not exist.")
        if not target_path.is_file():
            raise WorkspaceFileValidationError("Workspace path must be a file.")

        content = target_path.read_bytes()
        mime_type = self._guess_mime_type(target_path)
        return WorkspaceBinaryFileReadResult(
            content=content,
            mime_type=mime_type,
            size_bytes=len(content),
        )

    def write_binary_file(
        self,
        *,
        workspace_id: str,
        username: str,
        path: str,
        content: bytes,
        mime_type: str | None = None,
    ) -> WorkspaceBinaryFileWriteResult:
        """Write one binary file inside an owned workspace.

        Args:
            workspace_id: Public workspace identifier.
            username: Authenticated username that must own the workspace.
            path: Workspace-relative file path.
            content: Full binary payload to persist.
            mime_type: Optional caller-provided MIME type.

        Returns:
            File metadata after the write completes.

        Raises:
            WorkspaceFileNotFoundError: If the workspace is missing.
            WorkspaceFilePermissionError: If the workspace is not owned.
            WorkspaceFileValidationError: If the path is unsafe.
        """
        workspace = self._get_workspace_for_owner(
            workspace_id=workspace_id,
            username=username,
        )
        target_path = self._resolve_workspace_path(
            workspace=workspace,
            relative_path=path,
            allow_root=False,
        )
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(content)
        normalized_mime_type = mime_type or self._guess_mime_type(target_path)
        return WorkspaceBinaryFileWriteResult(
            path=path,
            mime_type=normalized_mime_type,
            size_bytes=len(content),
        )

    def _get_workspace_for_owner(self, *, workspace_id: str, username: str) -> Workspace:
        """Return one owned workspace row.

        Args:
            workspace_id: Public workspace identifier.
            username: Username that must own the workspace.

        Returns:
            Matching workspace row.

        Raises:
            WorkspaceFileNotFoundError: If the workspace does not exist.
            WorkspaceFilePermissionError: If the workspace belongs to another user.
        """
        workspace = WorkspaceService(self.db).get_workspace(workspace_id)
        if workspace is None:
            raise WorkspaceFileNotFoundError("Workspace not found.")
        if workspace.user != username:
            raise WorkspaceFilePermissionError("Workspace is not owned by the caller.")
        return workspace

    def _resolve_workspace_path(
        self,
        *,
        workspace: Workspace,
        relative_path: str | None,
        allow_root: bool,
    ) -> Path:
        """Resolve one safe workspace-relative path to its host path.

        Args:
            workspace: Owning workspace row.
            relative_path: Requested workspace-relative path.
            allow_root: Whether the workspace root itself is valid.

        Returns:
            Absolute host-side path under the workspace root.

        Raises:
            WorkspaceFileValidationError: If the path is empty, absolute, or escapes.
        """
        normalized = self._normalize_relative_path(
            relative_path=relative_path,
            allow_root=allow_root,
        )
        workspace_root = WorkspaceService(self.db).get_workspace_path(workspace).resolve()
        if normalized == PurePosixPath("."):
            return workspace_root

        target_path = workspace_root.joinpath(*normalized.parts).resolve()
        if not target_path.is_relative_to(workspace_root):
            raise WorkspaceFileValidationError("Workspace path must stay inside root.")
        return target_path

    @staticmethod
    def _normalize_relative_path(
        *,
        relative_path: str | None,
        allow_root: bool,
    ) -> PurePosixPath:
        """Validate one workspace-relative POSIX path.

        Args:
            relative_path: Raw caller-provided path.
            allow_root: Whether the workspace root is a valid target.

        Returns:
            Normalized ``PurePosixPath`` rooted under the workspace.

        Raises:
            WorkspaceFileValidationError: If the path is unsafe or empty.
        """
        if relative_path is None:
            if allow_root:
                return PurePosixPath(".")
            raise WorkspaceFileValidationError("Workspace file path is required.")

        normalized = relative_path.strip().replace("\\", "/")
        if normalized in {"", "."}:
            if allow_root:
                return PurePosixPath(".")
            raise WorkspaceFileValidationError("Workspace file path is required.")

        pure_path = PurePosixPath(normalized)
        if pure_path.is_absolute():
            raise WorkspaceFileValidationError("Workspace path must be relative.")
        if any(part == ".." for part in pure_path.parts):
            raise WorkspaceFileValidationError("Workspace path cannot escape root.")
        if any(part == "" for part in pure_path.parts):
            raise WorkspaceFileValidationError("Workspace path contains empty segments.")
        return pure_path

    @staticmethod
    def _guess_previewable_image_mime_type(target_path: Path) -> str | None:
        """Return one supported image MIME type for inline preview rendering."""
        mime_type, _encoding = mimetypes.guess_type(target_path.name)
        if not isinstance(mime_type, str) or not mime_type.startswith("image/"):
            return None
        if mime_type == "image/svg+xml":
            return None
        return mime_type

    @staticmethod
    def _guess_mime_type(target_path: Path) -> str:
        """Return one best-effort MIME type for an arbitrary file path."""
        mime_type, _encoding = mimetypes.guess_type(target_path.name)
        if not isinstance(mime_type, str) or mime_type.strip() == "":
            return "application/octet-stream"
        return mime_type
