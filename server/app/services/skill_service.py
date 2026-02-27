"""Skill service for managing shared/private markdown skills and metadata.

This service stores user-editable skills under:
- ``server/workspace/{username}/skills/private/{name}/{name}.md``
- ``server/workspace/{username}/skills/shared/{name}/{name}.md``

Built-in skills are loaded from:
- ``server/app/orchestration/skills/builtin/{name}/{name}.md``

For each user skill file, a structured metadata JSON is stored under:
- ``.../skills/{kind}/.metadata/{name}.json``
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.workspace_service import workspace_root
from app.utils.logging_config import get_logger

logger = get_logger("skill_service")

_SKILLS_DIRNAME = "skills"
_ALLOWED_KINDS = {"private", "shared"}


def _builtin_skills_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "orchestration" / "skills" / "builtin"


def _user_skills_dir(username: str, kind: str) -> Path:
    if kind not in _ALLOWED_KINDS:
        raise ValueError(f"Invalid skill kind: {kind}")
    base = workspace_root() / username / _SKILLS_DIRNAME / kind
    base.mkdir(parents=True, exist_ok=True)
    (base / ".metadata").mkdir(parents=True, exist_ok=True)
    return base


def _meta_path(base_dir: Path, skill_name: str) -> Path:
    return base_dir / ".metadata" / f"{skill_name}.json"


def _canonical_skill_path(base_dir: Path, skill_name: str) -> Path:
    return base_dir / skill_name / f"{skill_name}.md"


def _legacy_skill_path(base_dir: Path, skill_name: str) -> Path:
    return base_dir / f"{skill_name}.md"


def _resolve_skill_path(base_dir: Path, skill_name: str) -> Path | None:
    canonical = _canonical_skill_path(base_dir, skill_name)
    if canonical.exists():
        return canonical
    legacy = _legacy_skill_path(base_dir, skill_name)
    if legacy.exists():
        return legacy
    return None


def _list_skill_paths(base_dir: Path) -> list[Path]:
    """List canonical skill markdown files plus legacy flat files."""
    paths: list[Path] = []
    canonical_names: set[str] = set()

    for item in sorted(base_dir.iterdir()):
        if not item.is_dir() or item.name.startswith("_") or item.name == ".metadata":
            continue
        canonical = item / f"{item.name}.md"
        if canonical.exists():
            paths.append(canonical)
            canonical_names.add(item.name)

    for md_file in sorted(base_dir.glob("*.md")):
        if md_file.name.startswith("_"):
            continue
        if md_file.stem in canonical_names:
            continue
        paths.append(md_file)

    return paths


def _migrate_legacy_user_skill(base_dir: Path, skill_name: str) -> Path:
    """Move legacy ``{name}.md`` to canonical ``{name}/{name}.md`` layout."""
    canonical = _canonical_skill_path(base_dir, skill_name)
    legacy = _legacy_skill_path(base_dir, skill_name)
    if canonical.exists() or not legacy.exists():
        return canonical

    canonical.parent.mkdir(parents=True, exist_ok=True)
    legacy.replace(canonical)
    logger.info("Migrated legacy skill layout: %s -> %s", legacy, canonical)
    return canonical


def _file_md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()


def _parse_front_matter(source: str) -> dict[str, str]:
    """Parse markdown front matter and return a lowercase string map.

    Supports a simple YAML-like ``key: value`` format between ``---`` delimiters.
    """
    lines = source.splitlines()
    if len(lines) < 3:
        return {}
    if lines[0].strip() != "---":
        return {}

    end_idx = -1
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break
    if end_idx == -1:
        return {}

    meta: dict[str, str] = {}
    for raw in lines[1:end_idx]:
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        normalized_key = key.strip().lower()
        normalized_val = value.strip().strip('"').strip("'")
        meta[normalized_key] = normalized_val
    return meta


def _build_metadata(path: Path, kind: str, source_type: str, created_at: str | None = None) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    parsed = _parse_front_matter(raw)

    from_stat_created = path.stat().st_ctime
    from_stat_updated = path.stat().st_mtime

    created_iso = created_at
    if created_iso is None:
        created_iso = datetime.fromtimestamp(from_stat_created, tz=timezone.utc).isoformat()

    updated_iso = datetime.fromtimestamp(from_stat_updated, tz=timezone.utc).isoformat()

    name = parsed.get("name") or path.stem
    description = parsed.get("description") or ""

    return {
        "name": name,
        "description": description,
        "filename": path.name,
        "kind": kind,
        "source": source_type,
        "md5": _file_md5(path),
        # Keep both spellings for downstream compatibility.
        "create_at": created_iso,
        "update_at": updated_iso,
        "created_at": created_iso,
        "updated_at": updated_iso,
    }


def _validate_skill_name(skill_name: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", skill_name):
        raise ValueError("Skill name can only contain letters, numbers, '_', '-', '.'")


def list_builtin_skills() -> list[dict[str, Any]]:
    """List metadata for built-in shared skills."""
    root = _builtin_skills_dir()
    if not root.exists():
        return []

    result: list[dict[str, Any]] = []
    for md_file in _list_skill_paths(root):
        try:
            result.append(_build_metadata(md_file, kind="shared", source_type="builtin"))
        except Exception as exc:
            logger.warning("Failed to parse builtin skill '%s': %s", md_file.name, exc)
    return result


def list_user_skills(username: str, kind: str) -> list[dict[str, Any]]:
    """List metadata for user skills of a given kind."""
    base = _user_skills_dir(username, kind)
    result: list[dict[str, Any]] = []

    for md_file in _list_skill_paths(base):
        skill_name = md_file.stem
        md_file = _migrate_legacy_user_skill(base, skill_name)
        meta_file = _meta_path(base, skill_name)
        existing_created: str | None = None
        if meta_file.exists():
            try:
                saved = json.loads(meta_file.read_text(encoding="utf-8"))
                existing_created = saved.get("created_at")
            except json.JSONDecodeError:
                existing_created = None

        meta = _build_metadata(md_file, kind=kind, source_type="user", created_at=existing_created)
        meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        result.append(meta)

    return result


def list_all_skills(username: str) -> list[dict[str, Any]]:
    """List builtin + user shared + user private skill metadata."""
    return [
        *list_builtin_skills(),
        *list_user_skills(username, "shared"),
        *list_user_skills(username, "private"),
    ]


def get_skills_by_names(username: str, names: list[str]) -> list[dict[str, Any]]:
    """Return skill metadata entries filtered by exact names preserving input order."""
    all_by_name = {item["name"]: item for item in list_all_skills(username)}
    return [all_by_name[name] for name in names if name in all_by_name]


def read_user_skill(username: str, kind: str, skill_name: str) -> dict[str, Any]:
    """Read markdown source and metadata for a user skill."""
    _validate_skill_name(skill_name)
    base = _user_skills_dir(username, kind)
    skill_path = _resolve_skill_path(base, skill_name)
    if skill_path is None:
        raise FileNotFoundError(f"Skill '{skill_name}' not found in {kind}.")
    if skill_path == _legacy_skill_path(base, skill_name):
        skill_path = _migrate_legacy_user_skill(base, skill_name)

    meta_file = _meta_path(base, skill_name)
    existing_created: str | None = None
    if meta_file.exists():
        try:
            existing_created = json.loads(meta_file.read_text(encoding="utf-8")).get("created_at")
        except json.JSONDecodeError:
            existing_created = None

    meta = _build_metadata(skill_path, kind=kind, source_type="user", created_at=existing_created)
    meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "name": skill_name,
        "source": skill_path.read_text(encoding="utf-8"),
        "metadata": meta,
    }


def read_shared_skill(username: str, skill_name: str) -> dict[str, Any]:
    """Read shared skill source.

    Priority: user-shared first, then builtin shared.
    """
    _validate_skill_name(skill_name)

    user_shared_base = _user_skills_dir(username, "shared")
    user_shared_path = _resolve_skill_path(user_shared_base, skill_name)
    if user_shared_path is not None:
        return read_user_skill(username, "shared", skill_name)

    builtin_base = _builtin_skills_dir()
    builtin_path = _resolve_skill_path(builtin_base, skill_name)
    if builtin_path is None:
        raise FileNotFoundError(f"Shared skill '{skill_name}' not found.")

    meta = _build_metadata(builtin_path, kind="shared", source_type="builtin")
    return {
        "name": skill_name,
        "source": builtin_path.read_text(encoding="utf-8"),
        "metadata": meta,
    }


def read_skill_content_for_prompt(username: str, skill_name: str) -> str:
    """Read skill source by name from user shared/private first, then builtin."""
    _validate_skill_name(skill_name)
    for kind in ("private", "shared"):
        base = _user_skills_dir(username, kind)
        path = _resolve_skill_path(base, skill_name)
        if path is not None:
            if path == _legacy_skill_path(base, skill_name):
                path = _migrate_legacy_user_skill(base, skill_name)
            return path.read_text(encoding="utf-8")

    builtin_path = _resolve_skill_path(_builtin_skills_dir(), skill_name)
    if builtin_path is not None:
        return builtin_path.read_text(encoding="utf-8")

    raise FileNotFoundError(f"Skill '{skill_name}' not found.")


def build_selected_skills_prompt_block(username: str, selected_skills: list[str]) -> str:
    """Build a markdown block containing selected skills full text for prompt injection."""
    if not selected_skills:
        return ""

    blocks: list[str] = []
    for idx, skill_name in enumerate(selected_skills, start=1):
        try:
            content = read_skill_content_for_prompt(username, skill_name)
        except FileNotFoundError:
            continue
        blocks.append(f"### Skill {idx}: {skill_name}\n\n{content.strip()}\n")
    return "\n".join(blocks).strip()


def upsert_user_skill(username: str, kind: str, skill_name: str, source: str) -> dict[str, Any]:
    """Create or update a user skill markdown file and metadata."""
    _validate_skill_name(skill_name)
    base = _user_skills_dir(username, kind)
    legacy_path = _legacy_skill_path(base, skill_name)
    skill_path = _canonical_skill_path(base, skill_name)
    skill_path.parent.mkdir(parents=True, exist_ok=True)
    meta_file = _meta_path(base, skill_name)

    existing_created: str | None = None
    if meta_file.exists():
        try:
            existing_created = json.loads(meta_file.read_text(encoding="utf-8")).get("created_at")
        except json.JSONDecodeError:
            existing_created = None

    skill_path.write_text(source, encoding="utf-8")
    if legacy_path.exists():
        legacy_path.unlink()
    meta = _build_metadata(skill_path, kind=kind, source_type="user", created_at=existing_created)
    meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info("Saved %s skill '%s' for user '%s'", kind, skill_name, username)
    return meta


def delete_user_skill(username: str, kind: str, skill_name: str) -> None:
    """Delete a user skill markdown file and metadata."""
    _validate_skill_name(skill_name)
    base = _user_skills_dir(username, kind)
    canonical_path = _canonical_skill_path(base, skill_name)
    legacy_path = _legacy_skill_path(base, skill_name)
    if not canonical_path.exists() and not legacy_path.exists():
        raise FileNotFoundError(f"Skill '{skill_name}' not found in {kind}.")

    if canonical_path.exists():
        shutil.rmtree(canonical_path.parent, ignore_errors=True)
    if legacy_path.exists():
        legacy_path.unlink()
    meta_file = _meta_path(base, skill_name)
    if meta_file.exists():
        meta_file.unlink()

    logger.info("Deleted %s skill '%s' for user '%s'", kind, skill_name, username)
