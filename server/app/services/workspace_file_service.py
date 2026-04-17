"""Reusable CRUD helpers for text files under runtime workspaces."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

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


class WorkspaceFileService:
    """CRUD-style text file access scoped to one owned runtime workspace."""

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
