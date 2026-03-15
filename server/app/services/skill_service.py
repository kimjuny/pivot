"""Database-backed skill registry plus markdown source access helpers."""

from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.models.skill import Skill
from app.models.user import User
from app.services.workspace_service import workspace_root
from app.utils.logging_config import get_logger
from sqlmodel import Session, select

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = get_logger("skill_service")

_SKILLS_DIRNAME = "skills"
_ALLOWED_KINDS = {"private", "shared"}
_SKILL_VARIANT_FILENAMES = ("SKILL.md", "skill.md", "Skill.md")


@dataclass(frozen=True)
class SkillMount:
    """Minimal mount information for sandbox skill injection."""

    name: str
    location: str


@dataclass(frozen=True)
class _DiscoveredSkill:
    """Metadata discovered from one markdown skill file on disk."""

    name: str
    description: str
    kind: str
    source: str
    builtin: bool
    creator_id: int | None
    creator_username: str | None
    location: str
    filename: str
    md5: str
    updated_at: datetime


def _builtin_skills_dir() -> Path:
    return (
        Path(__file__).resolve().parent.parent / "orchestration" / "skills" / "builtin"
    )


def _user_skills_dir(username: str, kind: str, *, create: bool) -> Path:
    if kind not in _ALLOWED_KINDS:
        raise ValueError(f"Invalid skill kind: {kind}")
    base = workspace_root() / username / _SKILLS_DIRNAME / kind
    if create:
        base.mkdir(parents=True, exist_ok=True)
    return base


def _canonical_skill_path(base_dir: Path, skill_name: str) -> Path:
    return base_dir / skill_name / f"{skill_name}.md"


def _legacy_skill_path(base_dir: Path, skill_name: str) -> Path:
    return base_dir / f"{skill_name}.md"


def _resolve_skill_path(base_dir: Path, skill_name: str) -> Path | None:
    skill_dir = base_dir / skill_name
    if skill_dir.is_dir():
        canonical = _canonical_skill_path(base_dir, skill_name)
        if canonical.exists():
            return canonical
        for filename in _SKILL_VARIANT_FILENAMES:
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


def _list_skill_paths(base_dir: Path) -> list[Path]:
    """List markdown skill files under one base directory."""
    if not base_dir.exists():
        return []

    paths: list[Path] = []
    directory_skill_names: set[str] = set()

    for item in sorted(base_dir.iterdir()):
        if not item.is_dir() or item.name.startswith("_"):
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
    canonical = _canonical_skill_path(base_dir, skill_name)
    legacy = _legacy_skill_path(base_dir, skill_name)
    if canonical.exists():
        return canonical
    if not legacy.exists():
        return legacy

    canonical.parent.mkdir(parents=True, exist_ok=True)
    legacy.replace(canonical)
    logger.info("Migrated legacy skill layout: %s -> %s", legacy, canonical)
    return canonical


def _read_markdown(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _file_md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()


def _parse_front_matter(source: str) -> dict[str, str]:
    """Parse a minimal YAML-like front matter block from markdown."""
    lines = source.splitlines()
    if len(lines) < 3 or lines[0].strip() != "---":
        return {}

    end_idx = -1
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break
    if end_idx == -1:
        return {}

    meta: dict[str, str] = {}
    for raw_line in lines[1:end_idx]:
        line = raw_line.strip()
        if not line or ":" not in line or line.startswith("#"):
            continue
        key, value = line.split(":", 1)
        meta[key.strip().lower()] = value.strip().strip('"').strip("'")
    return meta


def _validate_skill_name(skill_name: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", skill_name):
        raise ValueError("Skill name can only contain letters, numbers, '_', '-', '.'")


def _discover_skill(
    *,
    base_dir: Path,
    skill_path: Path,
    kind: str,
    source: str,
    builtin: bool,
    creator: User | None,
) -> _DiscoveredSkill:
    """Build one discovered skill record from markdown on disk."""
    fallback_name = _fallback_skill_name(base_dir, skill_path)
    source_text = _read_markdown(skill_path)
    parsed = _parse_front_matter(source_text)
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
        builtin=builtin,
        creator_id=creator.id if creator is not None else None,
        creator_username=creator.username if creator is not None else None,
        location=str(location.resolve()),
        filename=skill_path.name,
        md5=_file_md5(skill_path),
        updated_at=updated_at,
    )


def _discover_builtin_skills() -> list[_DiscoveredSkill]:
    root = _builtin_skills_dir()
    if not root.exists():
        return []

    return [
        _discover_skill(
            base_dir=root,
            skill_path=skill_path,
            kind="shared",
            source="builtin",
            builtin=True,
            creator=None,
        )
        for skill_path in _list_skill_paths(root)
    ]


def _discover_user_skills(users: Sequence[User]) -> list[_DiscoveredSkill]:
    discovered: list[_DiscoveredSkill] = []
    for user in users:
        for kind in ("private", "shared"):
            base_dir = _user_skills_dir(user.username, kind, create=False)
            if not base_dir.exists():
                continue
            for skill_path in _list_skill_paths(base_dir):
                fallback_name = _fallback_skill_name(base_dir, skill_path)
                if skill_path == _legacy_skill_path(base_dir, fallback_name):
                    skill_path = _migrate_legacy_user_skill(base_dir, fallback_name)
                if not skill_path.exists():
                    continue
                discovered.append(
                    _discover_skill(
                        base_dir=base_dir,
                        skill_path=skill_path,
                        kind=kind,
                        source="user",
                        builtin=False,
                        creator=user,
                    )
                )
    return discovered


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
    read_only = bool(skill.builtin)
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
        "kind": skill.kind,
        "source": skill.source,
        "creator": creator,
        "builtin": skill.builtin,
        "read_only": read_only,
        "md5": skill.md5,
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
                builtin=discovered.builtin,
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
    new_values = {
        "name": discovered.name,
        "description": discovered.description,
        "kind": discovered.kind,
        "source": discovered.source,
        "builtin": discovered.builtin,
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
    discovered = [*_discover_builtin_skills(), *_discover_user_skills(users)]
    _assert_unique_discovered_names(discovered)

    existing_rows = _all_skills_query(session)
    existing_by_location = {item.location: item for item in existing_rows}
    existing_by_name = {item.name: item for item in existing_rows}
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
    statement = select(Skill).where(Skill.kind == "shared").order_by(Skill.name)
    skills = session.exec(statement).all()
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
        Serialized metadata for builtin, shared, and user-private skills.
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

    skill = session.exec(
        select(Skill).where(Skill.name == skill_name, Skill.kind == "shared")
    ).first()
    if skill is None:
        raise FileNotFoundError(f"Shared skill '{skill_name}' not found.")

    return _read_skill_payload(session, skill=skill, username=username)


def build_selected_skills_prompt_block(
    session: Session,
    username: str,
    selected_skills: list[str],
) -> str:
    """Build prompt-injection markdown from selected visible skills.

    Args:
        session: Active database session.
        username: Authenticated username.
        selected_skills: Selected globally unique skill names.

    Returns:
        Concatenated markdown block for once-per-task bootstrap user-prompt injection.
    """
    if not selected_skills:
        return ""

    sync_skill_registry(session)
    visible_skills = _visible_skills_query(session, username)
    by_name = {skill.name: skill for skill in visible_skills}

    blocks: list[str] = []
    for index, skill_name in enumerate(selected_skills, start=1):
        skill = by_name.get(skill_name)
        if skill is None:
            continue
        try:
            content = _read_markdown(_skill_content_path(skill)).strip()
        except FileNotFoundError:
            logger.warning("Selected skill source disappeared: %s", skill.location)
            continue
        blocks.append(f"### Skill {index}: {skill.name}\n\n{content}\n")
    return "\n".join(blocks).strip()


def build_skill_mounts(
    session: Session,
    username: str,
    skill_names: list[str],
) -> list[dict[str, str]]:
    """Build sandbox mount metadata for visible skills.

    Args:
        session: Active database session.
        username: Authenticated username.
        skill_names: Allowed globally unique skill names.

    Returns:
        List of ``{"name": ..., "location": ...}`` payloads for sandbox-manager.
    """
    sync_skill_registry(session)
    visible_skills = _visible_skills_query(session, username)
    by_name = {skill.name: skill for skill in visible_skills}

    mounts: list[dict[str, str]] = []
    seen_names: set[str] = set()
    for skill_name in skill_names:
        if skill_name in seen_names:
            continue
        skill = by_name.get(skill_name)
        if skill is None:
            continue
        seen_names.add(skill_name)
        mounts.append({"name": skill.name, "location": skill.location})
    return mounts


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
        PermissionError: If the target name belongs to another creator or builtin.
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
        if existing.builtin:
            raise PermissionError(f"Skill '{skill_name}' is built-in and read-only.")
        if existing.creator_id != current_user.id:
            raise PermissionError(
                f"Skill '{skill_name}' is owned by another creator and is read-only."
            )
        if existing.kind != kind:
            raise ValueError(
                f"Skill '{skill_name}' already exists as a {existing.kind} skill."
            )

    base_dir = _user_skills_dir(current_user.username, kind, create=True)
    legacy_path = _legacy_skill_path(base_dir, skill_name)
    canonical_path = _canonical_skill_path(base_dir, skill_name)
    canonical_path.parent.mkdir(parents=True, exist_ok=True)
    canonical_path.write_text(source, encoding="utf-8")
    if legacy_path.exists():
        legacy_path.unlink()

    discovered = _discover_skill(
        base_dir=base_dir,
        skill_path=canonical_path,
        kind=kind,
        source="user",
        builtin=False,
        creator=current_user,
    )

    if existing is None:
        created_at = discovered.updated_at
        row = Skill(
            name=discovered.name,
            description=discovered.description,
            kind=kind,
            source="user",
            builtin=False,
            creator_id=current_user.id,
            location=discovered.location,
            filename=discovered.filename,
            md5=discovered.md5,
            created_at=created_at,
            updated_at=discovered.updated_at,
        )
    else:
        row = existing
        row.description = discovered.description
        row.location = discovered.location
        row.filename = discovered.filename
        row.md5 = discovered.md5
        row.updated_at = discovered.updated_at

    session.add(row)
    session.commit()
    session.refresh(row)

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
    if skill.builtin or skill.creator_id != current_user.id or skill.kind != kind:
        raise PermissionError(f"Skill '{skill_name}' is not editable by this user.")

    skill_dir = Path(skill.location)
    canonical_path = skill_dir / skill.filename
    legacy_path = _legacy_skill_path(
        _user_skills_dir(current_user.username, kind, create=True),
        skill_name,
    )

    if canonical_path.exists():
        shutil.rmtree(skill_dir, ignore_errors=True)
    if legacy_path.exists():
        legacy_path.unlink()

    session.delete(skill)
    session.commit()
    logger.info(
        "Deleted %s skill '%s' for user '%s'",
        kind,
        skill_name,
        current_user.username,
    )
