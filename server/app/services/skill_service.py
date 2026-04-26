"""Database-backed skill registry plus markdown source access helpers."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tarfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any
from zipfile import ZipFile

from app.models.skill import Skill
from app.models.user import User
from app.orchestration.skills.github import (
    download_github_repository_archive,
    probe_github_skill_repository,
)
from app.orchestration.skills.skill_files import (
    SKILL_MARKDOWN_FILENAMES,
    parse_front_matter,
    rewrite_skill_name,
)
from app.services.skill_artifact_storage_service import (
    SkillArtifactStorageService,
    StoredSkillArtifact,
)
from app.services.workspace_service import workspace_root
from app.utils.logging_config import get_logger
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = get_logger("skill_service")

_SKILLS_DIRNAME = "skills"
_ALLOWED_KINDS = {"private", "shared"}
_ALLOWED_USER_SOURCES = {"manual", "network", "bundle", "agent"}
_LEGACY_USER_SKILL_DIRS = frozenset(_ALLOWED_KINDS)
_CANONICAL_SKILL_ENTRY_FILENAME = "SKILL.md"


@dataclass(frozen=True)
class SkillMount:
    """Minimal mount information for sandbox skill injection."""

    name: str
    location: str


@dataclass(frozen=True)
class BundleImportFile:
    """One uploaded file that belongs to a local skill bundle."""

    relative_path: str
    content: bytes


ImportProgressCallback = Callable[[str, str, int, str | None], None]


@dataclass(frozen=True)
class _DiscoveredSkill:
    """Metadata discovered from one markdown skill file on disk."""

    name: str
    description: str
    kind: str
    source: str
    creator_id: int | None
    creator_username: str | None
    location: str
    filename: str
    md5: str
    updated_at: datetime


def _legacy_user_skills_root(username: str) -> Path:
    """Return the pre-namespace local root used by older skill layouts."""
    return workspace_root() / username / _SKILLS_DIRNAME


def _user_skills_dir(username: str, *, create: bool) -> Path:
    """Return the unified user skill root.

    Why: the filesystem now stores all creator-owned skills under one directory.
    Visibility and sharing rules live in persistent metadata instead of the
    on-disk path shape, which keeps future ACL changes out of storage layout.
    """
    base = workspace_root() / "users" / username / _SKILLS_DIRNAME
    legacy_base = _legacy_user_skills_root(username)
    if not base.exists() and legacy_base.exists():
        base.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy_base), str(base))
        logger.info("Migrated legacy user skill root: %s -> %s", legacy_base, base)
    if create:
        base.mkdir(parents=True, exist_ok=True)
    return base


def _legacy_user_skills_dir(username: str, kind: str, *, create: bool) -> Path:
    """Return the legacy kind-scoped directory used by older installations."""
    if kind not in _ALLOWED_KINDS:
        raise ValueError(f"Invalid skill kind: {kind}")
    base = _user_skills_dir(username, create=create) / kind
    if create:
        base.mkdir(parents=True, exist_ok=True)
    return base


def _canonical_skill_path(base_dir: Path, skill_name: str) -> Path:
    return base_dir / skill_name / _CANONICAL_SKILL_ENTRY_FILENAME


def _legacy_skill_path(base_dir: Path, skill_name: str) -> Path:
    return base_dir / f"{skill_name}.md"


def _sandbox_skill_entry_path(skill_name: str) -> str:
    return f"/workspace/skills/{skill_name}/{_CANONICAL_SKILL_ENTRY_FILENAME}"


def _resolve_skill_path(base_dir: Path, skill_name: str) -> Path | None:
    skill_dir = base_dir / skill_name
    if skill_dir.is_dir():
        canonical = _canonical_skill_path(base_dir, skill_name)
        if canonical.exists():
            return canonical
        for filename in SKILL_MARKDOWN_FILENAMES:
            candidate = skill_dir / filename
            if candidate.exists():
                return candidate
        for candidate in sorted(skill_dir.glob("*.md")):
            if not candidate.name.startswith("_"):
                return candidate

    legacy = _legacy_skill_path(base_dir, skill_name)
    if legacy.exists():
        return legacy
    return None


def _canonicalize_skill_entry_filename(skill_path: Path) -> Path:
    """Rename one discovered entry file to the canonical ``SKILL.md`` path."""
    if skill_path.name == _CANONICAL_SKILL_ENTRY_FILENAME:
        return skill_path

    canonical_path = skill_path.parent / _CANONICAL_SKILL_ENTRY_FILENAME
    if canonical_path.exists():
        return canonical_path

    skill_path.replace(canonical_path)
    return canonical_path


def _list_skill_paths(
    base_dir: Path,
    *,
    ignored_dir_names: set[str] | None = None,
) -> list[Path]:
    """List markdown skill files under one base directory."""
    if not base_dir.exists():
        return []

    paths: list[Path] = []
    directory_skill_names: set[str] = set()
    ignored = ignored_dir_names or set()

    for item in sorted(base_dir.iterdir()):
        if not item.is_dir() or item.name.startswith("_"):
            continue
        if item.name in ignored:
            continue
        matched = _resolve_skill_path(base_dir, item.name)
        if matched is not None:
            paths.append(matched)
            directory_skill_names.add(item.name)

    for md_file in sorted(base_dir.glob("*.md")):
        if md_file.name.startswith("_"):
            continue
        if md_file.stem not in directory_skill_names:
            paths.append(md_file)

    return paths


def _skill_location_for_path(base_dir: Path, skill_path: Path) -> Path:
    if skill_path.parent == base_dir:
        return base_dir / skill_path.stem
    return skill_path.parent


def _fallback_skill_name(base_dir: Path, skill_path: Path) -> str:
    if skill_path.parent == base_dir:
        return skill_path.stem
    return skill_path.parent.name


def _migrate_legacy_user_skill(base_dir: Path, skill_name: str) -> Path:
    """Normalize legacy flat files into directory layout for stable locations."""
    canonical = base_dir / skill_name / _CANONICAL_SKILL_ENTRY_FILENAME
    legacy = _legacy_skill_path(base_dir, skill_name)
    if canonical.exists():
        return canonical
    if not legacy.exists():
        return legacy

    canonical.parent.mkdir(parents=True, exist_ok=True)
    legacy.replace(canonical)
    logger.info("Migrated legacy skill layout: %s -> %s", legacy, canonical)
    return canonical


def _migrate_legacy_user_skill_to_unified_root(
    *,
    unified_root: Path,
    legacy_root: Path,
    skill_name: str,
) -> Path:
    """Move one legacy kind-scoped skill into the unified user skill root."""
    legacy_path = _resolve_skill_path(legacy_root, skill_name)
    if legacy_path is None:
        raise FileNotFoundError(
            f"Legacy skill '{skill_name}' not found in {legacy_root}."
        )

    if legacy_path == _legacy_skill_path(legacy_root, skill_name):
        legacy_path = _migrate_legacy_user_skill(legacy_root, skill_name)

    legacy_dir = _skill_location_for_path(legacy_root, legacy_path)
    target_dir = unified_root / skill_name
    if target_dir.exists() and target_dir != legacy_dir:
        raise ValueError(
            "Cannot migrate legacy skill because unified destination already exists: "
            f"'{target_dir}'."
        )

    unified_root.mkdir(parents=True, exist_ok=True)
    if target_dir != legacy_dir:
        shutil.move(str(legacy_dir), str(target_dir))
        logger.info("Migrated legacy skill directory: %s -> %s", legacy_dir, target_dir)

    canonical_path = target_dir / _CANONICAL_SKILL_ENTRY_FILENAME
    if canonical_path.exists():
        return canonical_path

    for filename in SKILL_MARKDOWN_FILENAMES:
        candidate = target_dir / filename
        if candidate.exists():
            candidate.replace(canonical_path)
            break
    return canonical_path


def _read_markdown(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _file_md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()


def _validate_skill_name(skill_name: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", skill_name):
        raise ValueError("Skill name can only contain letters, numbers, '_', '-', '.'")


def _detect_skill_entry_filename(skill_dir: Path, *, label: str) -> str:
    """Return the top-level markdown entry file inside a skill directory."""
    for filename in SKILL_MARKDOWN_FILENAMES:
        entry_path = skill_dir / filename
        if entry_path.exists():
            return filename

    expected_names = ", ".join(SKILL_MARKDOWN_FILENAMES)
    raise ValueError(f"{label} must contain one of {expected_names} at its top level.")


def _emit_import_progress(
    progress: ImportProgressCallback | None,
    *,
    stage: str,
    label: str,
    percent: int,
    detail: str | None = None,
) -> None:
    """Send one optional import progress update."""
    if progress is not None:
        progress(stage, label, percent, detail)


def _replace_directory_contents(source_dir: Path, target_dir: Path) -> None:
    """Replace one skill directory atomically enough for local filesystem use."""
    parent_dir = target_dir.parent
    staging_dir = parent_dir / f".{target_dir.name}.tmp"
    backup_dir = parent_dir / f".{target_dir.name}.bak"

    if staging_dir.exists():
        shutil.rmtree(staging_dir, ignore_errors=True)
    if backup_dir.exists():
        shutil.rmtree(backup_dir, ignore_errors=True)

    shutil.copytree(source_dir, staging_dir)

    if target_dir.exists():
        target_dir.replace(backup_dir)
    staging_dir.replace(target_dir)

    if backup_dir.exists():
        shutil.rmtree(backup_dir, ignore_errors=True)


def _discover_skill(
    *,
    base_dir: Path,
    skill_path: Path,
    kind: str,
    source: str,
    creator: User | None,
) -> _DiscoveredSkill:
    """Build one discovered skill record from markdown on disk."""
    fallback_name = _fallback_skill_name(base_dir, skill_path)
    source_text = _read_markdown(skill_path)
    parsed = parse_front_matter(source_text)
    name = parsed.get("name") or fallback_name
    _validate_skill_name(name)

    stat = skill_path.stat()
    updated_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
    location = _skill_location_for_path(base_dir, skill_path)

    return _DiscoveredSkill(
        name=name,
        description=parsed.get("description", ""),
        kind=kind,
        source=source,
        creator_id=creator.id if creator is not None else None,
        creator_username=creator.username if creator is not None else None,
        location=str(location.resolve()),
        filename=skill_path.name,
        md5=_file_md5(skill_path),
        updated_at=updated_at,
    )


def _kind_for_unified_skill(
    *,
    user: User,
    skill_name: str,
    skill_path: Path,
    existing_by_name: dict[str, Skill],
    existing_by_location: dict[str, Skill],
) -> tuple[str, str]:
    """Resolve persisted kind/source for a unified user skill directory."""
    location = str(
        _skill_location_for_path(
            _user_skills_dir(user.username, create=False), skill_path
        ).resolve()
    )
    existing = existing_by_location.get(location) or existing_by_name.get(skill_name)
    if existing is not None and existing.creator_id == user.id:
        return existing.kind, _normalize_user_skill_source(existing.source)
    return "private", "manual"


def _discover_user_skills(
    users: Sequence[User],
    *,
    existing_by_name: dict[str, Skill],
    existing_by_location: dict[str, Skill],
) -> list[_DiscoveredSkill]:
    discovered: list[_DiscoveredSkill] = []
    for user in users:
        unified_root = _user_skills_dir(user.username, create=False)
        if unified_root.exists():
            for skill_path in _list_skill_paths(
                unified_root,
                ignored_dir_names=set(_LEGACY_USER_SKILL_DIRS),
            ):
                fallback_name = _fallback_skill_name(unified_root, skill_path)
                if skill_path == _legacy_skill_path(unified_root, fallback_name):
                    skill_path = _migrate_legacy_user_skill(unified_root, fallback_name)
                if not skill_path.exists():
                    continue
                skill_path = _canonicalize_skill_entry_filename(skill_path)
                kind, source = _kind_for_unified_skill(
                    user=user,
                    skill_name=fallback_name,
                    skill_path=skill_path,
                    existing_by_name=existing_by_name,
                    existing_by_location=existing_by_location,
                )
                discovered.append(
                    _discover_skill(
                        base_dir=unified_root,
                        skill_path=skill_path,
                        kind=kind,
                        source=source,
                        creator=user,
                    )
                )

        for kind in ("private", "shared"):
            legacy_root = _legacy_user_skills_dir(user.username, kind, create=False)
            if not legacy_root.exists():
                continue
            for skill_path in _list_skill_paths(legacy_root):
                fallback_name = _fallback_skill_name(legacy_root, skill_path)
                migrated_path = _migrate_legacy_user_skill_to_unified_root(
                    unified_root=unified_root,
                    legacy_root=legacy_root,
                    skill_name=fallback_name,
                )
                discovered.append(
                    _discover_skill(
                        base_dir=unified_root,
                        skill_path=_canonicalize_skill_entry_filename(migrated_path),
                        kind=kind,
                        source="manual",
                        creator=user,
                    )
                )
    return discovered


def _normalize_user_skill_source(source: str | None) -> str:
    """Normalize persisted user skill source values to the supported enum."""
    if source in _ALLOWED_USER_SOURCES:
        return source
    return "manual"


def _assert_unique_discovered_names(discovered: list[_DiscoveredSkill]) -> None:
    seen_by_name: dict[str, str] = {}
    for item in discovered:
        existing_location = seen_by_name.get(item.name)
        if existing_location is not None and existing_location != item.location:
            raise ValueError(
                "Skill names must be globally unique. "
                f"Found duplicate name '{item.name}' in '{existing_location}' and "
                f"'{item.location}'."
            )
        seen_by_name[item.name] = item.location


def _skill_content_path(skill: Skill) -> Path:
    return Path(skill.location) / skill.filename


def _parse_name_allowlist(raw_json: str | None) -> set[str] | None:
    if raw_json is None:
        return None

    text = raw_json.strip()
    if not text:
        return None

    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return set()

    if not isinstance(parsed, list):
        return set()

    return {item.strip() for item in parsed if isinstance(item, str) and item.strip()}


def _creator_name_map(session: Session) -> dict[int, str]:
    users = session.exec(select(User)).all()
    return {user.id: user.username for user in users if user.id is not None}


def _serialize_utc_timestamp(value: datetime) -> str:
    """Serialize persisted datetimes as explicit UTC ISO 8601 strings.

    Why: SQLite commonly drops timezone info on round-trip. The frontend timestamp
    helpers rely on explicit UTC offsets so browsers convert to the viewer's local
    timezone instead of treating the string as local time already.
    """
    return value.replace(tzinfo=UTC).isoformat()


def _serialize_skill(
    skill: Skill,
    *,
    creator_lookup: dict[int, str],
    current_username: str | None,
) -> dict[str, Any]:
    creator = (
        creator_lookup.get(skill.creator_id) if skill.creator_id is not None else None
    )
    read_only = False
    if (
        creator is not None
        and current_username is not None
        and creator != current_username
    ):
        read_only = True

    return {
        "name": skill.name,
        "description": skill.description,
        "location": skill.location,
        "filename": skill.filename,
        "artifact_storage_backend": skill.artifact_storage_backend,
        "artifact_key": skill.artifact_key,
        "artifact_digest": skill.artifact_digest,
        "artifact_size_bytes": skill.artifact_size_bytes,
        "kind": skill.kind,
        "source": skill.source,
        "creator": creator,
        "read_only": read_only,
        "md5": skill.md5,
        "github_repo_url": skill.github_repo_url,
        "github_ref": skill.github_ref,
        "github_ref_type": skill.github_ref_type,
        "github_skill_path": skill.github_skill_path,
        "imported": skill.github_repo_url is not None,
        "created_at": _serialize_utc_timestamp(skill.created_at),
        "updated_at": _serialize_utc_timestamp(skill.updated_at),
    }


def _all_skills_query(session: Session) -> list[Skill]:
    return list(session.exec(select(Skill).order_by(Skill.name)).all())


def _visible_skills_query(session: Session, username: str) -> list[Skill]:
    user = session.exec(select(User).where(User.username == username)).first()
    if user is None or user.id is None:
        raise ValueError(f"User '{username}' not found.")

    return [
        skill
        for skill in _all_skills_query(session)
        if skill.kind == "shared" or skill.creator_id == user.id
    ]


def _find_skill_by_name(skills: list[Skill], skill_name: str) -> Skill | None:
    for skill in skills:
        if skill.name == skill_name:
            return skill
    return None


def _upsert_skill_row(
    session: Session,
    *,
    existing_by_location: dict[str, Skill],
    existing_by_name: dict[str, Skill],
    discovered: _DiscoveredSkill,
) -> bool:
    """Insert or update one registry row if discovered metadata changed."""
    skill = existing_by_location.get(discovered.location)
    if skill is None:
        skill = existing_by_name.get(discovered.name)
        if skill is not None and skill.location != discovered.location:
            existing_by_location.pop(skill.location, None)

    if skill is None:
        session.add(
            Skill(
                name=discovered.name,
                description=discovered.description,
                kind=discovered.kind,
                source=discovered.source,
                creator_id=discovered.creator_id,
                location=discovered.location,
                filename=discovered.filename,
                md5=discovered.md5,
                created_at=discovered.updated_at,
                updated_at=discovered.updated_at,
            )
        )
        return True

    changed = False
    next_source = _normalize_user_skill_source(skill.source)
    new_values = {
        "name": discovered.name,
        "description": discovered.description,
        "kind": discovered.kind,
        "source": next_source,
        "creator_id": discovered.creator_id,
        "location": discovered.location,
        "filename": discovered.filename,
        "md5": discovered.md5,
        "updated_at": discovered.updated_at,
    }
    for field_name, field_value in new_values.items():
        if getattr(skill, field_name) != field_value:
            setattr(skill, field_name, field_value)
            changed = True

    if changed:
        session.add(skill)
    return changed


def sync_skill_registry(session: Session) -> None:
    """Synchronize persistent skill metadata with skill markdown files.

    Args:
        session: Active database session.

    Raises:
        ValueError: If duplicate skill names exist across visible skill sources.
    """
    users = session.exec(select(User).order_by(User.username)).all()
    existing_rows = _all_skills_query(session)
    existing_by_location = {item.location: item for item in existing_rows}
    existing_by_name = {item.name: item for item in existing_rows}
    discovered = _discover_user_skills(
        users,
        existing_by_name=existing_by_name,
        existing_by_location=existing_by_location,
    )
    _assert_unique_discovered_names(discovered)
    desired_locations = {item.location for item in discovered}

    changed = False
    for item in discovered:
        changed = (
            _upsert_skill_row(
                session,
                existing_by_location=existing_by_location,
                existing_by_name=existing_by_name,
                discovered=item,
            )
            or changed
        )

    for row in existing_rows:
        if row.location in desired_locations:
            continue
        session.delete(row)
        changed = True

    if changed:
        session.commit()


def list_shared_skills(session: Session, username: str) -> list[dict[str, Any]]:
    """List all shared skills visible to the current user.

    Args:
        session: Active database session.
        username: Authenticated username.

    Returns:
        Serialized shared-skill metadata rows.
    """
    sync_skill_registry(session)
    creator_lookup = _creator_name_map(session)
    user = session.exec(select(User).where(User.username == username)).first()
    if user is None or user.id is None:
        raise ValueError(f"User '{username}' not found.")

    statement = select(Skill).where(Skill.kind == "shared").order_by(Skill.name)
    skills = list(session.exec(statement).all())
    return [
        _serialize_skill(
            skill,
            creator_lookup=creator_lookup,
            current_username=username,
        )
        for skill in skills
    ]


def list_private_skills(session: Session, username: str) -> list[dict[str, Any]]:
    """List private skills owned by the current user.

    Args:
        session: Active database session.
        username: Authenticated username.

    Returns:
        Serialized private-skill metadata rows.
    """
    sync_skill_registry(session)
    creator_lookup = _creator_name_map(session)
    user = session.exec(select(User).where(User.username == username)).first()
    if user is None or user.id is None:
        raise ValueError(f"User '{username}' not found.")

    statement = (
        select(Skill)
        .where(Skill.kind == "private", Skill.creator_id == user.id)
        .order_by(Skill.name)
    )
    skills = session.exec(statement).all()
    return [
        _serialize_skill(
            skill,
            creator_lookup=creator_lookup,
            current_username=username,
        )
        for skill in skills
    ]


def list_visible_skills(session: Session, username: str) -> list[dict[str, Any]]:
    """List compact metadata for every skill visible to a user.

    Args:
        session: Active database session.
        username: Authenticated username.

    Returns:
        Serialized metadata for shared and user-private skills.
    """
    sync_skill_registry(session)
    creator_lookup = _creator_name_map(session)
    skills = _visible_skills_query(session, username)
    return [
        _serialize_skill(
            skill,
            creator_lookup=creator_lookup,
            current_username=username,
        )
        for skill in skills
    ]


def list_allowed_visible_skills(
    session: Session,
    username: str,
    *,
    raw_skill_ids: str | None,
    extra_skills: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """Return deterministic visible skill metadata for one runtime.

    Args:
        session: Active database session.
        username: Authenticated username.
        raw_skill_ids: Optional JSON allowlist matching the agent row format.
        extra_skills: Optional non-registry skill payloads such as extension
            package skills.

    Returns:
        Sorted visible skill metadata including storage location for mounting.
    """
    sync_skill_registry(session)
    visible_skills = _visible_skills_query(session, username)
    allowed_names = _parse_name_allowlist(raw_skill_ids)
    results: list[dict[str, str]] = []
    seen_names: set[str] = set()

    for skill in visible_skills:
        if allowed_names is not None and skill.name not in allowed_names:
            continue
        if skill.name in seen_names:
            continue
        seen_names.add(skill.name)
        results.append(
            {
                "name": skill.name,
                "description": skill.description,
                "location": skill.location,
                "filename": skill.filename,
            }
        )

    for extra_skill in extra_skills or []:
        skill_name = extra_skill.get("name")
        skill_location = extra_skill.get("location")
        if (
            not isinstance(skill_name, str)
            or not skill_name
            or not isinstance(skill_location, str)
        ):
            continue
        if skill_name in seen_names:
            continue
        seen_names.add(skill_name)
        entry_file = (
            str(extra_skill.get("entry_file"))
            if isinstance(extra_skill.get("entry_file"), str)
            else _CANONICAL_SKILL_ENTRY_FILENAME
        )
        results.append(
            {
                "name": skill_name,
                "description": (
                    str(extra_skill.get("description"))
                    if isinstance(extra_skill.get("description"), str)
                    else ""
                ),
                "location": str(Path(skill_location).resolve()),
                "filename": entry_file,
            }
        )

    return sorted(results, key=lambda item: item["name"])


def _read_skill_payload(
    session: Session,
    *,
    skill: Skill,
    username: str,
) -> dict[str, Any]:
    creator_lookup = _creator_name_map(session)
    return {
        "name": skill.name,
        "source": _read_markdown(_skill_content_path(skill)),
        "metadata": _serialize_skill(
            skill,
            creator_lookup=creator_lookup,
            current_username=username,
        ),
    }


def read_user_skill(
    session: Session,
    username: str,
    kind: str,
    skill_name: str,
) -> dict[str, Any]:
    """Read one user-owned skill markdown source and metadata.

    Args:
        session: Active database session.
        username: Authenticated username.
        kind: Skill scope, either ``private`` or ``shared``.
        skill_name: Globally unique skill name.

    Returns:
        Source markdown and serialized metadata.

    Raises:
        FileNotFoundError: If the skill is not owned by the user.
        PermissionError: If the skill exists but belongs to someone else.
        ValueError: If the skill name or scope is invalid.
    """
    _validate_skill_name(skill_name)
    if kind not in _ALLOWED_KINDS:
        raise ValueError(f"Invalid skill kind: {kind}")

    sync_skill_registry(session)
    user = session.exec(select(User).where(User.username == username)).first()
    if user is None or user.id is None:
        raise ValueError(f"User '{username}' not found.")

    skill = session.exec(select(Skill).where(Skill.name == skill_name)).first()
    if skill is None:
        raise FileNotFoundError(f"Skill '{skill_name}' not found.")
    if skill.creator_id != user.id or skill.kind != kind:
        raise PermissionError(f"Skill '{skill_name}' is not editable by '{username}'.")

    return _read_skill_payload(session, skill=skill, username=username)


def read_shared_skill(
    session: Session,
    username: str,
    skill_name: str,
) -> dict[str, Any]:
    """Read one shared skill visible to the current user.

    Args:
        session: Active database session.
        username: Authenticated username.
        skill_name: Globally unique shared skill name.

    Returns:
        Source markdown and serialized metadata.

    Raises:
        FileNotFoundError: If the shared skill does not exist.
        ValueError: If the skill name is invalid.
    """
    _validate_skill_name(skill_name)
    sync_skill_registry(session)
    user = session.exec(select(User).where(User.username == username)).first()
    if user is None or user.id is None:
        raise ValueError(f"User '{username}' not found.")

    skill = session.exec(
        select(Skill).where(Skill.name == skill_name, Skill.kind == "shared")
    ).first()
    if skill is None:
        raise FileNotFoundError(f"Shared skill '{skill_name}' not found.")

    return _read_skill_payload(session, skill=skill, username=username)


def build_skills_metadata_prompt_json(
    session: Session,
    username: str,
    raw_skill_ids: str | None,
    extra_skills: list[dict[str, str]] | None = None,
) -> str:
    """Build prompt-injection JSON from runtime-visible skill metadata.

    Args:
        session: Active database session.
        username: Authenticated username.
        raw_skill_ids: Optional JSON allowlist matching the agent row format.
        extra_skills: Optional non-registry skill payloads such as extension
            package skills.

    Returns:
        Stable JSON array text used by the task bootstrap prompt.
    """
    prompt_payload = build_skills_metadata_prompt_payload(
        session,
        username,
        raw_skill_ids=raw_skill_ids,
        extra_skills=extra_skills,
    )
    return json.dumps(prompt_payload, ensure_ascii=False, indent=2)


def build_skills_metadata_prompt_payload(
    session: Session,
    username: str,
    raw_skill_ids: str | None,
    extra_skills: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """Build runtime-visible skill metadata payload for prompts and APIs.

    Args:
        session: Active database session.
        username: Authenticated username.
        raw_skill_ids: Optional JSON allowlist matching the agent row format.
        extra_skills: Optional non-registry skill payloads such as extension
            package skills.

    Returns:
        Deterministic metadata records containing name, description, and the
        canonical sandbox path used by the ReAct runtime.
    """
    visible_skills = list_allowed_visible_skills(
        session,
        username,
        raw_skill_ids=raw_skill_ids,
        extra_skills=extra_skills,
    )
    return [
        {
            "name": skill["name"],
            "description": skill["description"],
            "path": _sandbox_skill_entry_path(skill["name"]),
        }
        for skill in visible_skills
    ]


def build_mandatory_skills_prompt_json(
    session: Session,
    username: str,
    *,
    raw_skill_ids: str | None,
    selected_skill_names: list[str],
    extra_skills: list[dict[str, str]] | None = None,
) -> str:
    """Build prompt JSON for user-selected mandatory skills.

    Args:
        session: Active database session.
        username: Authenticated username.
        raw_skill_ids: Optional JSON allowlist matching the agent row format.
        selected_skill_names: Ordered skill names explicitly selected by the
            user for the current task.
        extra_skills: Optional non-registry skill payloads such as extension
            package skills.

    Returns:
        Deterministic JSON array text used by the task bootstrap prompt.

    Raises:
        ValueError: If a selected skill is invalid or not visible to the
            current runtime.
    """
    normalized_names: list[str] = []
    seen_names: set[str] = set()
    for raw_name in selected_skill_names:
        skill_name = raw_name.strip()
        if not skill_name or skill_name in seen_names:
            continue
        _validate_skill_name(skill_name)
        normalized_names.append(skill_name)
        seen_names.add(skill_name)

    if not normalized_names:
        return "[]"

    visible_skills = list_allowed_visible_skills(
        session,
        username,
        raw_skill_ids=raw_skill_ids,
        extra_skills=extra_skills,
    )
    visible_by_name = {skill["name"]: skill for skill in visible_skills}

    prompt_payload: list[dict[str, str]] = []
    for skill_name in normalized_names:
        skill = visible_by_name.get(skill_name)
        if skill is None:
            raise ValueError(
                f"Mandatory skill '{skill_name}' is not visible to this agent runtime."
            )

        content_path = Path(skill["location"]) / skill["filename"]
        prompt_payload.append(
            {
                "name": skill_name,
                "description": skill["description"],
                "path": _sandbox_skill_entry_path(skill_name),
                "content": _read_markdown(content_path),
            }
        )

    return json.dumps(prompt_payload, ensure_ascii=False, indent=2)


def build_skill_mounts(
    session: Session,
    username: str,
    skill_names: list[str],
    extra_skills: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """Build sandbox mount metadata for visible skills.

    Args:
        session: Active database session.
        username: Authenticated username.
        skill_names: Allowed globally unique skill names.
        extra_skills: Optional non-registry skill payloads such as extension
            package skills.

    Returns:
        List of ``{"name": ..., "location": ...}`` payloads for sandbox-manager.
    """
    sync_skill_registry(session)
    visible_skills = _visible_skills_query(session, username)
    by_name = {skill.name: skill for skill in visible_skills}
    extra_by_name = {
        item["name"]: item
        for item in extra_skills or []
        if isinstance(item.get("name"), str) and isinstance(item.get("location"), str)
    }

    mounts: list[dict[str, str]] = []
    seen_names: set[str] = set()
    for skill_name in skill_names:
        if skill_name in seen_names:
            continue
        skill = by_name.get(skill_name)
        if skill is None:
            extra_skill = extra_by_name.get(skill_name)
            if extra_skill is None:
                continue
            seen_names.add(skill_name)
            mounts.append(
                {
                    "name": skill_name,
                    "location": str(Path(extra_skill["location"]).resolve()),
                }
            )
            continue
        seen_names.add(skill_name)
        mounts.append({"name": skill.name, "location": skill.location})
    return mounts


def probe_github_skill_import(
    session: Session,
    current_user: User,
    github_url: str,
    *,
    ref: str | None = None,
) -> dict[str, Any]:
    """Probe a public GitHub repository for importable skills.

    Args:
        session: Active database session.
        current_user: Authenticated user requesting the probe.
        github_url: GitHub repository URL.
        ref: Optional branch or tag to inspect.

    Returns:
        Serialized repository probe result with name-conflict hints.
    """
    if current_user.id is None:
        raise ValueError("Current user must be persisted before probing skills.")

    sync_skill_registry(session)
    existing_names = {skill.name for skill in _all_skills_query(session)}
    probe = probe_github_skill_repository(github_url, selected_ref=ref)
    payload = probe.to_dict()
    candidates = payload["candidates"]
    for candidate in candidates:
        suggested_name = candidate["suggested_name"]
        candidate["name_conflict"] = suggested_name in existing_names
    return payload


def install_github_skill(
    session: Session,
    current_user: User,
    *,
    github_url: str,
    ref: str,
    ref_type: str,
    kind: str,
    remote_directory_name: str,
    skill_name: str,
) -> dict[str, Any]:
    """Install one skill folder from a public GitHub repository.

    Args:
        session: Active database session.
        current_user: Authenticated user who owns the installation target.
        github_url: GitHub repository URL.
        ref: Selected branch or tag.
        kind: Installation scope, either ``private`` or ``shared``.
        remote_directory_name: Chosen folder directly under ``skills/`` in the repo.
        skill_name: Final globally unique skill name stored locally.

    Returns:
        Serialized metadata for the installed skill.
    """
    _validate_skill_name(skill_name)
    if kind not in _ALLOWED_KINDS:
        raise ValueError(f"Invalid skill kind: {kind}")
    if ref_type not in {"branch", "tag"}:
        raise ValueError(f"Invalid GitHub ref type: {ref_type}")
    if current_user.id is None:
        raise ValueError("Current user must be persisted before importing skills.")

    sync_skill_registry(session)
    existing = session.exec(select(Skill).where(Skill.name == skill_name)).first()
    if existing is not None:
        raise ValueError(f"Skill name '{skill_name}' already exists.")

    probe = probe_github_skill_repository(github_url, selected_ref=ref)
    candidate_by_directory = {
        candidate.directory_name: candidate for candidate in probe.candidates
    }
    selected_candidate = candidate_by_directory.get(remote_directory_name)
    if selected_candidate is None:
        raise ValueError(
            f"Directory '{remote_directory_name}' is not an importable skill for ref '{ref}'."
        )

    archive_bytes = download_github_repository_archive(github_url, ref)
    with TemporaryDirectory(prefix="pivot-skill-import-") as tmp_root:
        extracted_dir = Path(tmp_root) / skill_name
        _extract_skill_directory_from_archive(
            archive_bytes=archive_bytes,
            remote_directory_name=remote_directory_name,
            destination=extracted_dir,
        )
        metadata = _install_skill_from_directory(
            session,
            current_user,
            kind=kind,
            skill_name=skill_name,
            source="network",
            extracted_dir=extracted_dir,
            entry_filename=selected_candidate.entry_filename,
            github_repo_url=github_url,
            github_ref=ref,
            github_ref_type=ref_type,
            github_skill_path=f"skills/{remote_directory_name}",
        )

    logger.info(
        "Imported %s skill '%s' from %s@%s for user '%s'",
        kind,
        skill_name,
        github_url,
        ref,
        current_user.username,
    )
    return metadata


def install_bundle_skill(
    session: Session,
    current_user: User,
    *,
    bundle_name: str,
    kind: str,
    skill_name: str,
    files: Sequence[BundleImportFile],
) -> dict[str, Any]:
    """Install one skill bundle uploaded from the user's local machine."""
    _validate_skill_name(skill_name)
    if kind not in _ALLOWED_KINDS:
        raise ValueError(f"Invalid skill kind: {kind}")
    if current_user.id is None:
        raise ValueError("Current user must be persisted before importing skills.")

    sync_skill_registry(session)
    existing = session.exec(select(Skill).where(Skill.name == skill_name)).first()
    if existing is not None:
        raise ValueError(f"Skill name '{skill_name}' already exists.")

    with TemporaryDirectory(prefix="pivot-skill-bundle-") as tmp_root:
        extracted_dir = Path(tmp_root) / skill_name
        entry_filename = _extract_bundle_skill_directory(
            bundle_name=bundle_name,
            files=files,
            destination=extracted_dir,
        )
        metadata = _install_skill_from_directory(
            session,
            current_user,
            kind=kind,
            skill_name=skill_name,
            source="bundle",
            extracted_dir=extracted_dir,
            entry_filename=entry_filename,
        )

    logger.info(
        "Imported %s skill '%s' from local bundle '%s' for user '%s'",
        kind,
        skill_name,
        bundle_name,
        current_user.username,
    )
    return metadata


def install_archive_skill(
    session: Session,
    current_user: User,
    *,
    archive_path: Path,
    archive_filename: str,
    kind: str,
    skill_name: str,
    progress: ImportProgressCallback | None = None,
) -> dict[str, Any]:
    """Install one skill from an uploaded zip or tar archive."""
    _emit_import_progress(
        progress,
        stage="validating",
        label="Validating archive",
        percent=12,
    )
    _validate_skill_name(skill_name)
    if kind not in _ALLOWED_KINDS:
        raise ValueError(f"Invalid skill kind: {kind}")
    if current_user.id is None:
        raise ValueError("Current user must be persisted before importing skills.")

    sync_skill_registry(session)
    existing = session.exec(select(Skill).where(Skill.name == skill_name)).first()
    if existing is not None:
        raise ValueError(f"Skill name '{skill_name}' already exists.")

    with TemporaryDirectory(prefix="pivot-skill-archive-") as tmp_root:
        unpacked_dir = Path(tmp_root) / "archive"
        _emit_import_progress(
            progress,
            stage="extracting",
            label="Extracting archive",
            percent=28,
        )
        matched_files = _extract_uploaded_skill_archive(
            archive_path=archive_path,
            archive_filename=archive_filename,
            destination=unpacked_dir,
        )
        _emit_import_progress(
            progress,
            stage="locating_entry",
            label="Locating skill entry",
            percent=45,
            detail=f"{matched_files} files extracted",
        )
        extracted_dir, entry_filename = _archived_skill_root(unpacked_dir)
        metadata = _install_skill_from_directory(
            session,
            current_user,
            kind=kind,
            skill_name=skill_name,
            source="bundle",
            extracted_dir=extracted_dir,
            entry_filename=entry_filename,
            progress=progress,
        )

    logger.info(
        "Imported %s skill '%s' from local archive '%s' for user '%s'",
        kind,
        skill_name,
        archive_filename,
        current_user.username,
    )
    return metadata


def _extract_skill_directory_from_archive(
    *,
    archive_bytes: bytes,
    remote_directory_name: str,
    destination: Path,
) -> None:
    """Extract one ``skills/<dir>/`` subtree from a GitHub zip archive.

    Args:
        archive_bytes: Raw repository archive bytes.
        remote_directory_name: Folder selected under the repository ``skills/`` root.
        destination: Local destination directory.
    """
    destination.mkdir(parents=True, exist_ok=True)
    matched_files = 0
    with ZipFile(BytesIO(archive_bytes)) as archive:
        for member in archive.infolist():
            parts = PurePosixPath(member.filename).parts
            if (
                len(parts) < 3
                or parts[1] != "skills"
                or parts[2] != remote_directory_name
            ):
                continue

            relative_parts = parts[3:]
            if not relative_parts:
                continue

            target_path = destination.joinpath(*relative_parts)
            if member.is_dir():
                target_path.mkdir(parents=True, exist_ok=True)
                continue

            target_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target_path.open("wb") as output:
                shutil.copyfileobj(source, output)
            matched_files += 1

    if matched_files == 0:
        raise ValueError(
            f"Repository archive does not contain skills/{remote_directory_name}/."
        )


def _safe_archive_parts(raw_name: str) -> tuple[str, ...]:
    """Return safe archive path parts or raise for traversal attempts."""
    normalized = raw_name.strip().replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    if not parts:
        raise ValueError("Archive contains a file with an empty path.")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("Archive contains an unsafe file path.")
    if normalized.startswith("/"):
        raise ValueError("Archive contains an absolute file path.")
    return tuple(parts)


def _extract_uploaded_zip_archive(*, archive_path: Path, destination: Path) -> int:
    """Extract a user-uploaded zip archive into a destination directory."""
    matched_files = 0
    with ZipFile(archive_path) as archive:
        for member in archive.infolist():
            parts = _safe_archive_parts(member.filename)
            target_path = destination.joinpath(*parts)
            if member.is_dir():
                target_path.mkdir(parents=True, exist_ok=True)
                continue

            target_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target_path.open("wb") as output:
                shutil.copyfileobj(source, output)
            matched_files += 1
    return matched_files


def _extract_uploaded_tar_archive(*, archive_path: Path, destination: Path) -> int:
    """Extract a user-uploaded tar archive into a destination directory."""
    matched_files = 0
    with tarfile.open(archive_path) as archive:
        for member in archive.getmembers():
            parts = _safe_archive_parts(member.name)
            target_path = destination.joinpath(*parts)
            if member.isdir():
                target_path.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise ValueError("Archive contains unsupported link or special file.")

            source = archive.extractfile(member)
            if source is None:
                raise ValueError("Archive contains an unreadable file.")
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with source, target_path.open("wb") as output:
                shutil.copyfileobj(source, output)
            matched_files += 1
    return matched_files


def _extract_uploaded_skill_archive(
    *,
    archive_path: Path,
    archive_filename: str,
    destination: Path,
) -> int:
    """Extract one uploaded skill archive into a temporary directory."""
    filename = archive_filename.lower()
    destination.mkdir(parents=True, exist_ok=True)
    if filename.endswith(".zip"):
        matched_files = _extract_uploaded_zip_archive(
            archive_path=archive_path,
            destination=destination,
        )
    elif filename.endswith((".tar", ".tar.gz", ".tgz")):
        matched_files = _extract_uploaded_tar_archive(
            archive_path=archive_path,
            destination=destination,
        )
    else:
        raise ValueError("Skill archive must be a .zip, .tar, .tar.gz, or .tgz file.")

    if matched_files == 0:
        raise ValueError("Skill archive does not contain any files.")
    return matched_files


def _archived_skill_root(unpacked_dir: Path) -> tuple[Path, str]:
    """Find the skill directory inside an extracted user archive."""
    try:
        entry_filename = _detect_skill_entry_filename(
            unpacked_dir,
            label="Skill archive",
        )
        return unpacked_dir, entry_filename
    except ValueError:
        pass

    candidates: list[tuple[Path, str]] = []
    for item in sorted(unpacked_dir.iterdir()):
        if not item.is_dir() or item.name in {"__MACOSX"} or item.name.startswith("."):
            continue
        try:
            entry_filename = _detect_skill_entry_filename(
                item,
                label=f"Archive folder '{item.name}'",
            )
        except ValueError:
            continue
        candidates.append((item, entry_filename))

    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        expected_names = ", ".join(SKILL_MARKDOWN_FILENAMES)
        raise ValueError(f"Skill archive must contain {expected_names} at its root.")
    raise ValueError("Skill archive contains multiple top-level skill folders.")


def _extract_bundle_skill_directory(
    *,
    bundle_name: str,
    files: Sequence[BundleImportFile],
    destination: Path,
) -> str:
    """Write uploaded bundle files into a temporary skill directory.

    Args:
        bundle_name: Root folder name selected by the user.
        files: Uploaded files with browser-provided relative paths.
        destination: Temporary directory that receives the extracted bundle.

    Returns:
        The detected top-level skill markdown filename.

    Raises:
        ValueError: If the bundle is empty, malformed, or missing a skill entry file.
    """
    if not files:
        raise ValueError("Choose a local skill folder before importing.")

    destination.mkdir(parents=True, exist_ok=True)
    seen_paths: set[PurePosixPath] = set()

    for item in files:
        normalized = item.relative_path.strip().replace("\\", "/")
        if not normalized:
            raise ValueError("Imported bundle contains a file without a relative path.")

        path_parts = list(PurePosixPath(normalized).parts)
        if path_parts and path_parts[0] == bundle_name:
            path_parts = path_parts[1:]
        if not path_parts:
            raise ValueError("Imported bundle contains an invalid file path.")
        if any(part in {"", ".", ".."} for part in path_parts):
            raise ValueError("Imported bundle contains an unsafe file path.")

        relative_path = PurePosixPath(*path_parts)
        if relative_path in seen_paths:
            raise ValueError(
                f"Imported bundle contains duplicate file '{relative_path.as_posix()}'."
            )
        seen_paths.add(relative_path)

        target_path = destination.joinpath(*relative_path.parts)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(item.content)

    return _detect_skill_entry_filename(
        destination,
        label=f"Folder '{bundle_name}'",
    )


def _create_skill_row(
    *,
    discovered: _DiscoveredSkill,
    creator_id: int,
    source: str,
    created_at: datetime,
    stored_artifact: StoredSkillArtifact | None = None,
    github_repo_url: str | None = None,
    github_ref: str | None = None,
    github_ref_type: str | None = None,
    github_skill_path: str | None = None,
) -> Skill:
    """Create a persisted skill row for a newly installed user skill."""
    return Skill(
        name=discovered.name,
        description=discovered.description,
        kind=discovered.kind,
        source=source,
        creator_id=creator_id,
        location=discovered.location,
        artifact_storage_backend=(
            stored_artifact.storage_backend if stored_artifact is not None else None
        ),
        artifact_key=stored_artifact.artifact_key
        if stored_artifact is not None
        else None,
        artifact_digest=(
            stored_artifact.artifact_digest if stored_artifact is not None else None
        ),
        artifact_size_bytes=(
            stored_artifact.size_bytes if stored_artifact is not None else 0
        ),
        filename=discovered.filename,
        md5=discovered.md5,
        github_repo_url=github_repo_url,
        github_ref=github_ref,
        github_ref_type=github_ref_type,
        github_skill_path=github_skill_path,
        created_at=created_at,
        updated_at=created_at,
    )


def _update_skill_row_from_discovery(
    row: Skill,
    *,
    discovered: _DiscoveredSkill,
    source: str,
    stored_artifact: StoredSkillArtifact,
    github_repo_url: str | None = None,
    github_ref: str | None = None,
    github_ref_type: str | None = None,
    github_skill_path: str | None = None,
) -> Skill:
    """Update an existing row from a newly installed skill directory."""
    row.name = discovered.name
    row.description = discovered.description
    row.kind = discovered.kind
    row.source = source
    row.creator_id = discovered.creator_id
    row.location = discovered.location
    row.artifact_storage_backend = stored_artifact.storage_backend
    row.artifact_key = stored_artifact.artifact_key
    row.artifact_digest = stored_artifact.artifact_digest
    row.artifact_size_bytes = stored_artifact.size_bytes
    row.filename = discovered.filename
    row.md5 = discovered.md5
    row.github_repo_url = github_repo_url
    row.github_ref = github_ref
    row.github_ref_type = github_ref_type
    row.github_skill_path = github_skill_path
    row.updated_at = datetime.now(UTC)
    return row


def _install_skill_from_directory(
    session: Session,
    current_user: User,
    *,
    kind: str,
    skill_name: str,
    source: str,
    extracted_dir: Path,
    entry_filename: str,
    github_repo_url: str | None = None,
    github_ref: str | None = None,
    github_ref_type: str | None = None,
    github_skill_path: str | None = None,
    progress: ImportProgressCallback | None = None,
) -> dict[str, Any]:
    """Install a prepared skill directory into the user's workspace."""
    if current_user.id is None:
        raise ValueError("Current user must be persisted before importing skills.")

    base_dir = _user_skills_dir(current_user.username, create=True)
    target_dir = base_dir / skill_name
    if target_dir.exists():
        raise ValueError(f"Skill directory '{skill_name}' already exists.")

    skill_markdown_path = extracted_dir / entry_filename
    if not skill_markdown_path.exists():
        raise ValueError("Imported skill bundle is missing its skill markdown file.")

    rewritten_source = rewrite_skill_name(
        skill_markdown_path.read_text(encoding="utf-8"),
        skill_name,
    )
    _emit_import_progress(
        progress,
        stage="rewriting",
        label="Normalizing skill metadata",
        percent=58,
    )
    skill_markdown_path.write_text(rewritten_source, encoding="utf-8")
    _emit_import_progress(
        progress,
        stage="copying",
        label="Writing skill directory",
        percent=68,
    )
    shutil.copytree(extracted_dir, target_dir)
    _emit_import_progress(
        progress,
        stage="saving_artifact",
        label="Saving skill artifact",
        percent=82,
    )
    stored_artifact = SkillArtifactStorageService().store_directory(
        source_dir=target_dir,
        username=current_user.username,
        skill_name=skill_name,
    )

    _emit_import_progress(
        progress,
        stage="registering",
        label="Registering skill",
        percent=94,
    )
    discovered = _discover_skill(
        base_dir=base_dir,
        skill_path=target_dir / entry_filename,
        kind=kind,
        source=source,
        creator=current_user,
    )
    timestamp = datetime.now(UTC)
    row = session.exec(select(Skill).where(Skill.name == discovered.name)).first()
    if row is not None:
        if row.creator_id != current_user.id:
            shutil.rmtree(target_dir, ignore_errors=True)
            raise ValueError(f"Skill name '{discovered.name}' already exists.")
        _update_skill_row_from_discovery(
            row,
            discovered=discovered,
            source=source,
            stored_artifact=stored_artifact,
            github_repo_url=github_repo_url,
            github_ref=github_ref,
            github_ref_type=github_ref_type,
            github_skill_path=github_skill_path,
        )
    else:
        row = _create_skill_row(
            discovered=discovered,
            creator_id=current_user.id,
            source=source,
            created_at=timestamp,
            stored_artifact=stored_artifact,
            github_repo_url=github_repo_url,
            github_ref=github_ref,
            github_ref_type=github_ref_type,
            github_skill_path=github_skill_path,
        )
    session.add(row)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        shutil.rmtree(target_dir, ignore_errors=True)
        raise ValueError(f"Skill name '{discovered.name}' already exists.") from exc
    session.refresh(row)

    creator_lookup = _creator_name_map(session)
    return _serialize_skill(
        row,
        creator_lookup=creator_lookup,
        current_username=current_user.username,
    )


def apply_private_skill_directory(
    session: Session,
    current_user: User,
    *,
    skill_name: str,
    source_dir: Path,
    source: str = "agent",
) -> dict[str, Any]:
    """Create or replace one creator-owned private skill from a staged directory.

    Args:
        session: Active database session.
        current_user: Authenticated user who owns the target namespace.
        skill_name: Globally unique skill name to create or replace.
        source_dir: Directory whose files will become the private skill bundle.
        source: Persisted source label for the resulting skill row.

    Returns:
        Serialized metadata for the applied private skill.

    Raises:
        PermissionError: If the name belongs to a shared or foreign skill.
        ValueError: If the skill layout is invalid.
    """
    _validate_skill_name(skill_name)
    if current_user.id is None:
        raise ValueError("Current user must be persisted before writing skills.")
    if not source_dir.exists() or not source_dir.is_dir():
        raise ValueError("Skill source directory does not exist.")

    sync_skill_registry(session)
    existing = session.exec(select(Skill).where(Skill.name == skill_name)).first()
    if existing is not None:
        if existing.creator_id != current_user.id:
            raise PermissionError(
                f"Skill '{skill_name}' is owned by another creator and is read-only."
            )
        if existing.kind != "private":
            raise PermissionError(
                f"Skill '{skill_name}' is a {existing.kind} skill and cannot be updated "
                "through agent submissions."
            )

    entry_filename = _detect_skill_entry_filename(
        source_dir,
        label=f"Skill directory '{skill_name}'",
    )
    entry_path = source_dir / entry_filename
    rewritten_source = rewrite_skill_name(
        entry_path.read_text(encoding="utf-8"),
        skill_name,
    )
    entry_path.write_text(rewritten_source, encoding="utf-8")

    base_dir = _user_skills_dir(current_user.username, create=True)
    target_dir = base_dir / skill_name
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    _replace_directory_contents(source_dir, target_dir)
    stored_artifact = SkillArtifactStorageService().store_directory(
        source_dir=target_dir,
        username=current_user.username,
        skill_name=skill_name,
    )

    discovered = _discover_skill(
        base_dir=base_dir,
        skill_path=target_dir / entry_filename,
        kind="private",
        source=source,
        creator=current_user,
    )
    old_artifact_key: str | None = None

    if existing is None:
        timestamp = datetime.now(UTC)
        row = _create_skill_row(
            discovered=discovered,
            creator_id=current_user.id,
            source=source,
            created_at=timestamp,
            stored_artifact=stored_artifact,
        )
    else:
        old_artifact_key = existing.artifact_key
        row = existing
        row.description = discovered.description
        row.location = discovered.location
        row.artifact_storage_backend = stored_artifact.storage_backend
        row.artifact_key = stored_artifact.artifact_key
        row.artifact_digest = stored_artifact.artifact_digest
        row.artifact_size_bytes = stored_artifact.size_bytes
        row.filename = discovered.filename
        row.md5 = discovered.md5
        row.updated_at = discovered.updated_at
        row.source = source

    session.add(row)
    session.commit()
    session.refresh(row)
    if (
        existing is not None
        and old_artifact_key is not None
        and old_artifact_key != row.artifact_key
    ):
        SkillArtifactStorageService().delete_artifact(artifact_key=old_artifact_key)

    creator_lookup = _creator_name_map(session)
    return _serialize_skill(
        row,
        creator_lookup=creator_lookup,
        current_username=current_user.username,
    )


def upsert_user_skill(
    session: Session,
    current_user: User,
    kind: str,
    skill_name: str,
    source: str,
) -> dict[str, Any]:
    """Create or update one user-owned skill and persist its metadata.

    Args:
        session: Active database session.
        current_user: Authenticated user who owns the writable namespace.
        kind: Skill scope, either ``private`` or ``shared``.
        skill_name: Globally unique skill name to write.
        source: Markdown skill source.

    Returns:
        Serialized metadata for the saved skill.

    Raises:
        PermissionError: If the target name belongs to another creator.
        ValueError: If the name or scope is invalid.
    """
    _validate_skill_name(skill_name)
    if kind not in _ALLOWED_KINDS:
        raise ValueError(f"Invalid skill kind: {kind}")
    if current_user.id is None:
        raise ValueError("Current user must be persisted before writing skills.")

    sync_skill_registry(session)
    existing = session.exec(select(Skill).where(Skill.name == skill_name)).first()
    if existing is not None:
        if existing.creator_id != current_user.id:
            raise PermissionError(
                f"Skill '{skill_name}' is owned by another creator and is read-only."
            )
        if existing.kind != kind:
            raise ValueError(
                f"Skill '{skill_name}' already exists as a {existing.kind} skill."
            )

    normalized_source = rewrite_skill_name(source, skill_name)
    base_dir = _user_skills_dir(current_user.username, create=True)
    canonical_path = _canonical_skill_path(base_dir, skill_name)
    canonical_path.parent.mkdir(parents=True, exist_ok=True)
    canonical_path.write_text(normalized_source, encoding="utf-8")
    for legacy_kind in _ALLOWED_KINDS:
        legacy_root = _legacy_user_skills_dir(
            current_user.username,
            legacy_kind,
            create=False,
        )
        legacy_path = _legacy_skill_path(legacy_root, skill_name)
        if legacy_path.exists():
            legacy_path.unlink()

    discovered = _discover_skill(
        base_dir=base_dir,
        skill_path=canonical_path,
        kind=kind,
        source="manual",
        creator=current_user,
    )
    stored_artifact = SkillArtifactStorageService().store_directory(
        source_dir=canonical_path.parent,
        username=current_user.username,
        skill_name=skill_name,
    )
    old_artifact_key: str | None = None

    if existing is None:
        created_at = discovered.updated_at
        row = _create_skill_row(
            discovered=discovered,
            creator_id=current_user.id,
            source="manual",
            created_at=created_at,
            stored_artifact=stored_artifact,
        )
    else:
        old_artifact_key = existing.artifact_key
        row = existing
        row.description = discovered.description
        row.location = discovered.location
        row.artifact_storage_backend = stored_artifact.storage_backend
        row.artifact_key = stored_artifact.artifact_key
        row.artifact_digest = stored_artifact.artifact_digest
        row.artifact_size_bytes = stored_artifact.size_bytes
        row.filename = discovered.filename
        row.md5 = discovered.md5
        row.updated_at = discovered.updated_at
        row.source = _normalize_user_skill_source(row.source)

    session.add(row)
    session.commit()
    session.refresh(row)
    if (
        existing is not None
        and old_artifact_key is not None
        and old_artifact_key != row.artifact_key
    ):
        SkillArtifactStorageService().delete_artifact(artifact_key=old_artifact_key)

    logger.info(
        "Saved %s skill '%s' for user '%s'",
        kind,
        skill_name,
        current_user.username,
    )
    creator_lookup = _creator_name_map(session)
    return _serialize_skill(
        row,
        creator_lookup=creator_lookup,
        current_username=current_user.username,
    )


def delete_user_skill(
    session: Session,
    current_user: User,
    kind: str,
    skill_name: str,
) -> None:
    """Delete one user-owned skill and its persistent metadata row.

    Args:
        session: Active database session.
        current_user: Authenticated user who owns the writable namespace.
        kind: Skill scope, either ``private`` or ``shared``.
        skill_name: Globally unique skill name to delete.

    Raises:
        FileNotFoundError: If the skill does not exist.
        PermissionError: If the skill exists but is not owned by the current user.
        ValueError: If the name or scope is invalid.
    """
    _validate_skill_name(skill_name)
    if kind not in _ALLOWED_KINDS:
        raise ValueError(f"Invalid skill kind: {kind}")
    if current_user.id is None:
        raise ValueError("Current user must be persisted before deleting skills.")

    sync_skill_registry(session)
    skill = session.exec(select(Skill).where(Skill.name == skill_name)).first()
    if skill is None:
        raise FileNotFoundError(f"Skill '{skill_name}' not found.")
    if skill.creator_id != current_user.id or skill.kind != kind:
        raise PermissionError(f"Skill '{skill_name}' is not editable by this user.")

    skill_dir = Path(skill.location)
    canonical_path = skill_dir / skill.filename
    legacy_path = _legacy_skill_path(
        _user_skills_dir(current_user.username, create=True),
        skill_name,
    )

    if canonical_path.exists():
        shutil.rmtree(skill_dir, ignore_errors=True)
    if legacy_path.exists():
        legacy_path.unlink()
    for legacy_kind in _ALLOWED_KINDS:
        legacy_root = _legacy_user_skills_dir(
            current_user.username,
            legacy_kind,
            create=False,
        )
        legacy_dir = legacy_root / skill_name
        legacy_file = _legacy_skill_path(legacy_root, skill_name)
        if legacy_dir.exists():
            shutil.rmtree(legacy_dir, ignore_errors=True)
        if legacy_file.exists():
            legacy_file.unlink()
    if skill.artifact_key:
        SkillArtifactStorageService().delete_artifact(artifact_key=skill.artifact_key)

    session.delete(skill)
    session.commit()
    logger.info(
        "Deleted %s skill '%s' for user '%s'",
        kind,
        skill_name,
        current_user.username,
    )
