"""Database-backed skill registry plus markdown source access helpers."""

from __future__ import annotations

import hashlib
import re
import shutil
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
from app.services.workspace_service import workspace_root
from app.utils.logging_config import get_logger
from sqlmodel import Session, select

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = get_logger("skill_service")

_SKILLS_DIRNAME = "skills"
_ALLOWED_KINDS = {"private", "shared"}
_ALLOWED_USER_SOURCES = {"manual", "network", "bundle", "agent"}
_LEGACY_USER_SKILL_DIRS = frozenset(_ALLOWED_KINDS)


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


def _user_skills_dir(username: str, *, create: bool) -> Path:
    """Return the unified user skill root.

    Why: the filesystem now stores all creator-owned skills under one directory.
    Visibility and sharing rules live in persistent metadata instead of the
    on-disk path shape, which keeps future ACL changes out of storage layout.
    """
    base = workspace_root() / username / _SKILLS_DIRNAME
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
    return base_dir / skill_name / f"{skill_name}.md"


def _legacy_skill_path(base_dir: Path, skill_name: str) -> Path:
    return base_dir / f"{skill_name}.md"


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

    canonical_path = target_dir / f"{skill_name}.md"
    if not canonical_path.exists():
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
    builtin: bool,
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
                        builtin=False,
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
                        skill_path=migrated_path,
                        kind=kind,
                        source="manual",
                        builtin=False,
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
    next_source = (
        discovered.source
        if discovered.builtin
        else _normalize_user_skill_source(skill.source)
    )
    new_values = {
        "name": discovered.name,
        "description": discovered.description,
        "kind": discovered.kind,
        "source": next_source,
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
    existing_rows = _all_skills_query(session)
    existing_by_location = {item.location: item for item in existing_rows}
    existing_by_name = {item.name: item for item in existing_rows}
    discovered = [
        *_discover_builtin_skills(),
        *_discover_user_skills(
            users,
            existing_by_name=existing_by_name,
            existing_by_location=existing_by_location,
        ),
    ]
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
    user = session.exec(select(User).where(User.username == username)).first()
    if user is None or user.id is None:
        raise ValueError(f"User '{username}' not found.")

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
        builtin=False,
        creator_id=creator_id,
        location=discovered.location,
        filename=discovered.filename,
        md5=discovered.md5,
        github_repo_url=github_repo_url,
        github_ref=github_ref,
        github_ref_type=github_ref_type,
        github_skill_path=github_skill_path,
        created_at=created_at,
        updated_at=created_at,
    )


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
    skill_markdown_path.write_text(rewritten_source, encoding="utf-8")
    shutil.copytree(extracted_dir, target_dir)

    discovered = _discover_skill(
        base_dir=base_dir,
        skill_path=target_dir / entry_filename,
        kind=kind,
        source=source,
        builtin=False,
        creator=current_user,
    )
    timestamp = datetime.now(UTC)
    row = _create_skill_row(
        discovered=discovered,
        creator_id=current_user.id,
        source=source,
        created_at=timestamp,
        github_repo_url=github_repo_url,
        github_ref=github_ref,
        github_ref_type=github_ref_type,
        github_skill_path=github_skill_path,
    )
    session.add(row)
    session.commit()
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
        PermissionError: If the name belongs to a builtin, shared, or foreign skill.
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
        if existing.builtin:
            raise PermissionError(f"Skill '{skill_name}' is built-in and read-only.")
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

    discovered = _discover_skill(
        base_dir=base_dir,
        skill_path=target_dir / entry_filename,
        kind="private",
        source=source,
        builtin=False,
        creator=current_user,
    )

    if existing is None:
        timestamp = datetime.now(UTC)
        row = _create_skill_row(
            discovered=discovered,
            creator_id=current_user.id,
            source=source,
            created_at=timestamp,
        )
    else:
        row = existing
        row.description = discovered.description
        row.location = discovered.location
        row.filename = discovered.filename
        row.md5 = discovered.md5
        row.updated_at = discovered.updated_at
        row.source = source

    session.add(row)
    session.commit()
    session.refresh(row)

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
        builtin=False,
        creator=current_user,
    )

    if existing is None:
        created_at = discovered.updated_at
        row = _create_skill_row(
            discovered=discovered,
            creator_id=current_user.id,
            source="manual",
            created_at=created_at,
        )
    else:
        row = existing
        row.description = discovered.description
        row.location = discovered.location
        row.filename = discovered.filename
        row.md5 = discovered.md5
        row.updated_at = discovered.updated_at
        row.source = _normalize_user_skill_source(row.source)

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

    session.delete(skill)
    session.commit()
    logger.info(
        "Deleted %s skill '%s' for user '%s'",
        kind,
        skill_name,
        current_user.username,
    )
