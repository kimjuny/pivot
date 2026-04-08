"""Runtime file access helpers backed by sandbox-manager execution."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any
from zipfile import ZipFile

from app.services.sandbox_service import get_sandbox_service

if TYPE_CHECKING:
    from app.services.workspace_storage_service import WorkspaceMountSpec

_PRIORITIZED_GUIDANCE_FILENAMES = ("AGENTS.md", "CLAUDE.md")
_MAX_ATTACHMENT_TOTAL_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class WorkspaceRuntimeFile:
    """One immutable file snapshot exported from the sandbox workspace."""

    sandbox_path: str
    workspace_relative_path: str
    display_name: str
    content_bytes: bytes


class WorkspaceRuntimeFileService:
    """Read workspace files through sandbox-manager instead of host paths."""

    def read_text_file(
        self,
        *,
        username: str,
        mount_spec: WorkspaceMountSpec,
        workspace_relative_path: str,
    ) -> str:
        """Read one UTF-8 text file from the live workspace."""
        normalized_path = _normalize_workspace_relative_path(workspace_relative_path)
        payload = self._exec_json(
            username=username,
            mount_spec=mount_spec,
            cmd=_sandbox_text_read_command(workspace_relative_path=normalized_path),
            error_prefix="Failed to read workspace file",
        )
        content = payload.get("content")
        if not isinstance(content, str):
            raise ValueError("Sandbox returned an invalid workspace file payload.")
        return content

    def write_text_file(
        self,
        *,
        username: str,
        mount_spec: WorkspaceMountSpec,
        workspace_relative_path: str,
        content: str,
    ) -> None:
        """Write one UTF-8 text file back into the live workspace."""
        normalized_path = _normalize_workspace_relative_path(workspace_relative_path)
        self._exec_json(
            username=username,
            mount_spec=mount_spec,
            cmd=_sandbox_text_write_command(
                workspace_relative_path=normalized_path,
                content=content,
            ),
            error_prefix="Failed to write workspace file",
        )

    def read_guidance_file(
        self,
        *,
        username: str,
        mount_spec: WorkspaceMountSpec,
    ) -> tuple[str, str] | None:
        """Return the first prioritized workspace guidance file and content."""
        payload = self._exec_json(
            username=username,
            mount_spec=mount_spec,
            cmd=_sandbox_guidance_command(),
            error_prefix="Failed to read workspace guidance",
        )
        if not payload:
            return None

        sandbox_path = payload.get("sandbox_path")
        content = payload.get("content")
        if not isinstance(sandbox_path, str) or not isinstance(content, str):
            raise ValueError("Sandbox returned an invalid workspace guidance payload.")
        return sandbox_path, content

    def export_files(
        self,
        *,
        username: str,
        mount_spec: WorkspaceMountSpec,
        sandbox_paths: list[str],
        max_total_bytes: int = _MAX_ATTACHMENT_TOTAL_BYTES,
    ) -> list[WorkspaceRuntimeFile]:
        """Export regular files from ``/workspace`` as immutable byte snapshots."""
        if not sandbox_paths:
            return []

        payload = self._exec_json(
            username=username,
            mount_spec=mount_spec,
            cmd=_sandbox_file_export_command(
                sandbox_paths=sandbox_paths,
                max_total_bytes=max_total_bytes,
            ),
            error_prefix="Failed to export workspace files",
        )

        files_payload = payload.get("files")
        archive_b64 = payload.get("archive_b64")
        if not isinstance(files_payload, list) or not isinstance(archive_b64, str):
            raise ValueError("Sandbox returned an invalid workspace file snapshot.")

        archive_bytes = base64.b64decode(archive_b64.encode("ascii"), validate=True)
        archive_members: dict[str, bytes] = {}
        with ZipFile(BytesIO(archive_bytes)) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                archive_members[info.filename] = archive.read(info)

        exported: list[WorkspaceRuntimeFile] = []
        for item in files_payload:
            if not isinstance(item, dict):
                raise ValueError("Sandbox returned a malformed workspace file entry.")
            sandbox_path = item.get("sandbox_path")
            workspace_relative_path = item.get("workspace_relative_path")
            display_name = item.get("display_name")
            if not isinstance(sandbox_path, str):
                raise ValueError("Sandbox file entry is missing sandbox_path.")
            if not isinstance(workspace_relative_path, str):
                raise ValueError(
                    "Sandbox file entry is missing workspace_relative_path."
                )
            if not isinstance(display_name, str):
                raise ValueError("Sandbox file entry is missing display_name.")
            content_bytes = archive_members.get(workspace_relative_path)
            if content_bytes is None:
                raise ValueError("Sandbox file snapshot archive is incomplete.")
            exported.append(
                WorkspaceRuntimeFile(
                    sandbox_path=sandbox_path,
                    workspace_relative_path=workspace_relative_path,
                    display_name=display_name,
                    content_bytes=content_bytes,
                )
            )
        return exported

    def _exec_json(
        self,
        *,
        username: str,
        mount_spec: WorkspaceMountSpec,
        cmd: list[str],
        error_prefix: str,
    ) -> dict[str, Any]:
        """Execute one sandbox command and parse its JSON stdout payload."""
        result = get_sandbox_service().exec(
            username=username,
            mount_spec=mount_spec,
            cmd=cmd,
        )
        if result.exit_code != 0:
            message = result.stderr.strip() or result.stdout.strip()
            raise ValueError(f"{error_prefix}: {message}")
        try:
            payload = json.loads(result.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"{error_prefix}: sandbox returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{error_prefix}: sandbox returned a non-object payload.")
        return payload


def _sandbox_guidance_command() -> list[str]:
    """Build one sandbox command that reads the active guidance file."""
    script = """
import json
import pathlib

workspace_root = pathlib.Path("/workspace")
for filename in ("AGENTS.md", "CLAUDE.md"):
    candidate = workspace_root / filename
    if candidate.is_symlink():
        continue
    if candidate.is_file():
        print(
            json.dumps(
                {
                    "sandbox_path": f"/workspace/{filename}",
                    "content": candidate.read_text(encoding="utf-8").strip(),
                }
            )
        )
        raise SystemExit(0)
print("{}")
""".strip()
    return ["python3", "-c", script]


def _sandbox_file_export_command(
    *,
    sandbox_paths: list[str],
    max_total_bytes: int,
) -> list[str]:
    """Build one sandbox command that snapshots files under ``/workspace``."""
    payload = json.dumps(
        {
            "sandbox_paths": sandbox_paths,
            "max_total_bytes": max_total_bytes,
        },
        separators=(",", ":"),
    )
    script = """
import base64
import io
import json
import pathlib
import sys
import zipfile

payload = json.loads(sys.argv[1])
requested_paths = payload["sandbox_paths"]
max_total_bytes = int(payload["max_total_bytes"])
workspace_root = pathlib.Path("/workspace")
archive = io.BytesIO()
files = []
total_bytes = 0

with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
    for raw_path in requested_paths:
        if not isinstance(raw_path, str):
            continue
        candidate = pathlib.PurePosixPath(raw_path)
        if not candidate.is_absolute():
            continue
        if candidate == pathlib.PurePosixPath("/workspace"):
            continue
        try:
            relative = candidate.relative_to("/workspace")
        except ValueError:
            continue
        disk_path = workspace_root.joinpath(*relative.parts)
        if disk_path.is_symlink():
            continue
        if not disk_path.exists() or not disk_path.is_file():
            continue
        data = disk_path.read_bytes()
        total_bytes += len(data)
        if total_bytes > max_total_bytes:
            raise SystemExit("Workspace attachment export is too large.")
        relative_path = relative.as_posix()
        zf.writestr(relative_path, data)
        files.append(
            {
                "sandbox_path": candidate.as_posix(),
                "workspace_relative_path": relative_path,
                "display_name": disk_path.name,
            }
        )

print(
    json.dumps(
        {
            "archive_b64": base64.b64encode(archive.getvalue()).decode("ascii"),
            "files": files,
            "total_bytes": total_bytes,
        }
    )
)
""".strip()
    return ["python3", "-c", script, payload]


def _normalize_workspace_relative_path(workspace_relative_path: str) -> str:
    """Validate one workspace-relative file path before sandbox execution."""
    candidate = PurePosixPath(workspace_relative_path.strip())
    if workspace_relative_path.strip() == "" or candidate.is_absolute():
        raise ValueError("workspace_relative_path must be a relative workspace path.")
    if any(part in ("", ".", "..") for part in candidate.parts):
        raise ValueError("workspace_relative_path must not contain path traversal.")
    return candidate.as_posix()


def _sandbox_text_read_command(*, workspace_relative_path: str) -> list[str]:
    """Build one sandbox command that reads a UTF-8 workspace file."""
    payload = json.dumps(
        {"workspace_relative_path": workspace_relative_path},
        separators=(",", ":"),
    )
    script = """
import json
import pathlib
import sys

payload = json.loads(sys.argv[1])
relative_path = pathlib.PurePosixPath(payload["workspace_relative_path"])
workspace_root = pathlib.Path("/workspace")
disk_path = workspace_root.joinpath(*relative_path.parts)
if disk_path.is_symlink() or not disk_path.exists() or not disk_path.is_file():
    raise SystemExit("Workspace file not found.")

print(json.dumps({"content": disk_path.read_text(encoding="utf-8")}))
""".strip()
    return ["python3", "-c", script, payload]


def _sandbox_text_write_command(
    *,
    workspace_relative_path: str,
    content: str,
) -> list[str]:
    """Build one sandbox command that writes a UTF-8 workspace file."""
    payload = json.dumps(
        {
            "workspace_relative_path": workspace_relative_path,
            "content_b64": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        },
        separators=(",", ":"),
    )
    script = """
import base64
import json
import pathlib
import sys

payload = json.loads(sys.argv[1])
relative_path = pathlib.PurePosixPath(payload["workspace_relative_path"])
workspace_root = pathlib.Path("/workspace")
disk_path = workspace_root.joinpath(*relative_path.parts)
disk_path.parent.mkdir(parents=True, exist_ok=True)
disk_path.write_text(
    base64.b64decode(payload["content_b64"]).decode("utf-8"),
    encoding="utf-8",
)
print("{}")
""".strip()
    return ["python3", "-c", script, payload]
