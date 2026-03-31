from collections.abc import Generator
from importlib import import_module
from pathlib import Path
from typing import Final

from app.config import get_settings
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel

_REQUIRED_TABLES: Final[set[str]] = {
    "agent",
    "agentrelease",
    "agentsaveddraft",
    "agenttestsnapshot",
    "agentchannelbinding",
    "agentwebsearchbinding",
    "channeleventlog",
    "channellinktoken",
    "channelsession",
    "connection",
    "externalidentitybinding",
    "fileasset",
    "llm",
    "reactplanstep",
    "reactrecursion",
    "reactrecursionstate",
    "reacttask",
    "reacttaskevent",
    "scene",
    "session",
    "skill",
    "skillchangesubmission",
    "subscene",
    "taskattachment",
    "user",
}


def get_engine():
    """Create and return a SQLAlchemy database engine.

    The database URL is read from application settings so runtime code and
    config-file loading stay consistent across entrypoints.

    Returns:
        A SQLAlchemy engine instance configured for the database.
    """
    database_url = get_settings().DATABASE_URL

    if database_url.startswith("sqlite"):
        # For SQLite, ensure the parent directory exists (important in containers
        # where the named volume may be mounted but not yet initialised).
        db_path_str = database_url.removeprefix("sqlite:///").lstrip("/")
        if database_url.startswith("sqlite:////"):
            # Absolute path form sqlite:////abs/path
            db_path = Path("/" + database_url[len("sqlite:////") :])
        else:
            db_path = Path(db_path_str)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return create_engine(database_url, connect_args={"check_same_thread": False})

    return create_engine(database_url)


def get_session() -> Generator[Session, None, None]:
    """Create a database session for use in dependency injection.

    This function is designed to be used with FastAPI's Depends
    to provide database sessions to endpoint functions.

    Yields:
        A database session that will be automatically closed after use.
    """
    engine = get_engine()
    ensure_database_ready(engine)
    with Session(engine) as session:
        yield session


def init_db():
    """Initialize the database by creating all tables.

    This function creates all tables defined in SQLModel metadata
    if they don't already exist. It's safe to call this multiple times.
    """
    engine = get_engine()
    ensure_database_ready(engine)
    print("Database initialized successfully")


def ensure_database_ready(engine: Engine | None = None) -> None:
    """Ensure the active database has all required tables and seed data.

    Why: in development the SQLite file may be deleted while the backend keeps
    running. New requests then create an empty database file on demand, which
    would otherwise fail later during auth lookups with missing-table errors.

    Args:
        engine: Optional engine instance to reuse.
    """
    if engine is None:
        engine = get_engine()

    # Import models lazily so every SQLModel table is registered before create_all.
    import_module("app.models")

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    if not _REQUIRED_TABLES.issubset(existing_tables):
        SQLModel.metadata.create_all(engine)

    ensure_agent_schema_compatibility()
    ensure_session_schema_compatibility()
    ensure_react_schema_compatibility()
    ensure_file_schema_compatibility()
    ensure_skill_schema_compatibility()

    from app.api.auth import init_default_user
    from app.services.skill_service import sync_skill_registry

    with Session(engine) as session:
        init_default_user(session)
        sync_skill_registry(session)


def ensure_agent_schema_compatibility() -> None:
    """Apply additive schema updates for legacy agent tables.

    Why: existing SQLite deployments keep their current columns after startup,
    so newly introduced agent settings must be backfilled manually.
    """
    engine = get_engine()
    inspector = inspect(engine)
    if not inspector.has_table("agent"):
        return

    columns = {column["name"] for column in inspector.get_columns("agent")}
    with engine.begin() as conn:
        if "session_idle_timeout_minutes" not in columns:
            conn.execute(
                text(
                    "ALTER TABLE agent "
                    "ADD COLUMN session_idle_timeout_minutes INTEGER"
                )
            )
        if "sandbox_timeout_seconds" not in columns:
            conn.execute(
                text("ALTER TABLE agent ADD COLUMN sandbox_timeout_seconds INTEGER")
            )
        if "compact_threshold_percent" not in columns:
            conn.execute(
                text(
                    "ALTER TABLE agent " "ADD COLUMN compact_threshold_percent INTEGER"
                )
            )
        if "active_release_id" not in columns:
            conn.execute(text("ALTER TABLE agent ADD COLUMN active_release_id INTEGER"))
        if "serving_enabled" not in columns:
            conn.execute(text("ALTER TABLE agent ADD COLUMN serving_enabled BOOLEAN"))
        conn.execute(
            text(
                "UPDATE agent "
                "SET session_idle_timeout_minutes = 15 "
                "WHERE session_idle_timeout_minutes IS NULL"
            )
        )
        conn.execute(
            text(
                "UPDATE agent "
                "SET sandbox_timeout_seconds = 60 "
                "WHERE sandbox_timeout_seconds IS NULL"
            )
        )
        conn.execute(
            text(
                "UPDATE agent "
                "SET compact_threshold_percent = 60 "
                "WHERE compact_threshold_percent IS NULL"
            )
        )
        conn.execute(
            text(
                "UPDATE agent "
                "SET serving_enabled = 1 "
                "WHERE serving_enabled IS NULL"
            )
        )


def ensure_session_schema_compatibility() -> None:
    """Apply additive schema updates for legacy session tables.

    Why: chat sidebar features rely on explicit title and pin fields so the UI
    can stay simple without reconstructing that state from derived history.
    """
    engine = get_engine()
    inspector = inspect(engine)
    if not inspector.has_table("session"):
        return

    columns = {column["name"] for column in inspector.get_columns("session")}
    with engine.begin() as conn:
        if "title" not in columns:
            conn.execute(text("ALTER TABLE session ADD COLUMN title VARCHAR"))
        if "is_pinned" not in columns:
            conn.execute(text("ALTER TABLE session ADD COLUMN is_pinned BOOLEAN"))
        if "react_compact_result" not in columns:
            conn.execute(
                text("ALTER TABLE session ADD COLUMN react_compact_result VARCHAR")
            )
        if "release_id" not in columns:
            conn.execute(text("ALTER TABLE session ADD COLUMN release_id INTEGER"))
        if "type" not in columns:
            conn.execute(
                text("ALTER TABLE session ADD COLUMN type VARCHAR DEFAULT 'consumer'")
            )
        if "test_snapshot_id" not in columns:
            conn.execute(
                text("ALTER TABLE session ADD COLUMN test_snapshot_id INTEGER")
            )
        if "runtime_status" not in columns:
            conn.execute(text("ALTER TABLE session ADD COLUMN runtime_status VARCHAR"))
        conn.execute(text("UPDATE session SET is_pinned = 0 WHERE is_pinned IS NULL"))
        conn.execute(text("UPDATE session SET type = 'consumer' WHERE type IS NULL"))
        conn.execute(
            text(
                "UPDATE session "
                "SET release_id = ("
                "  SELECT active_release_id FROM agent WHERE agent.id = session.agent_id"
                ") "
                "WHERE release_id IS NULL"
            )
        )
        if inspector.has_table("reacttask"):
            conn.execute(
                text(
                    "UPDATE session "
                    "SET runtime_status = 'running' "
                    "WHERE EXISTS ("
                    "  SELECT 1 FROM reacttask "
                    "  WHERE reacttask.session_id = session.session_id "
                    "    AND reacttask.status IN ('pending', 'running')"
                    ")"
                )
            )
            conn.execute(
                text(
                    "UPDATE session "
                    "SET runtime_status = 'waiting_input' "
                    "WHERE NOT EXISTS ("
                    "  SELECT 1 FROM reacttask "
                    "  WHERE reacttask.session_id = session.session_id "
                    "    AND reacttask.status IN ('pending', 'running')"
                    ") "
                    "AND EXISTS ("
                    "  SELECT 1 FROM reacttask "
                    "  WHERE reacttask.session_id = session.session_id "
                    "    AND reacttask.status = 'waiting_input'"
                    ")"
                )
            )
        conn.execute(
            text(
                "UPDATE session "
                "SET runtime_status = 'idle' "
                "WHERE runtime_status IS NULL"
            )
        )


def ensure_react_schema_compatibility() -> None:
    """Apply additive schema updates for legacy ReAct tables."""
    engine = get_engine()
    inspector = inspect(engine)
    with engine.begin() as conn:
        if inspector.has_table("reacttask"):
            task_columns = {
                column["name"] for column in inspector.get_columns("reacttask")
            }
            if "skill_selection_result" not in task_columns:
                conn.execute(
                    text(
                        "ALTER TABLE reacttask "
                        "ADD COLUMN skill_selection_result VARCHAR"
                    )
                )
            if "cancel_requested_at" not in task_columns:
                conn.execute(
                    text(
                        "ALTER TABLE reacttask "
                        "ADD COLUMN cancel_requested_at DATETIME"
                    )
                )
            if "runtime_message_start_index" not in task_columns:
                conn.execute(
                    text(
                        "ALTER TABLE reacttask "
                        "ADD COLUMN runtime_message_start_index INTEGER"
                    )
                )
            if "stashed_messages" not in task_columns:
                conn.execute(
                    text("ALTER TABLE reacttask " "ADD COLUMN stashed_messages VARCHAR")
                )
            if "pending_user_action_json" not in task_columns:
                conn.execute(
                    text(
                        "ALTER TABLE reacttask "
                        "ADD COLUMN pending_user_action_json VARCHAR"
                    )
                )
            conn.execute(
                text(
                    "UPDATE reacttask "
                    "SET runtime_message_start_index = 0 "
                    "WHERE runtime_message_start_index IS NULL"
                )
            )

        if inspector.has_table("reactrecursion"):
            recursion_columns = {
                column["name"] for column in inspector.get_columns("reactrecursion")
            }
            if "thinking" not in recursion_columns:
                conn.execute(
                    text("ALTER TABLE reactrecursion ADD COLUMN thinking VARCHAR")
                )


def ensure_file_schema_compatibility() -> None:
    """Apply additive schema updates for legacy uploaded-file tables."""
    engine = get_engine()
    inspector = inspect(engine)
    if not inspector.has_table("fileasset"):
        return

    columns = {column["name"] for column in inspector.get_columns("fileasset")}
    with engine.begin() as conn:
        if "kind" not in columns:
            conn.execute(text("ALTER TABLE fileasset ADD COLUMN kind VARCHAR"))
            conn.execute(text("UPDATE fileasset SET kind = 'image' WHERE kind IS NULL"))
        if "page_count" not in columns:
            conn.execute(text("ALTER TABLE fileasset ADD COLUMN page_count INTEGER"))
        if "markdown_path" not in columns:
            conn.execute(text("ALTER TABLE fileasset ADD COLUMN markdown_path VARCHAR"))
        if "can_extract_text" not in columns:
            conn.execute(
                text("ALTER TABLE fileasset ADD COLUMN can_extract_text BOOLEAN")
            )
            conn.execute(
                text(
                    "UPDATE fileasset SET can_extract_text = 0 "
                    "WHERE can_extract_text IS NULL"
                )
            )
        if "suspected_scanned" not in columns:
            conn.execute(
                text("ALTER TABLE fileasset ADD COLUMN suspected_scanned BOOLEAN")
            )
            conn.execute(
                text(
                    "UPDATE fileasset SET suspected_scanned = 0 "
                    "WHERE suspected_scanned IS NULL"
                )
            )
        if "text_encoding" not in columns:
            conn.execute(text("ALTER TABLE fileasset ADD COLUMN text_encoding VARCHAR"))


def ensure_skill_schema_compatibility() -> None:
    """Apply additive schema updates for the evolving skill registry table.

    Why: skill import metadata is still moving quickly pre-launch, so
    startup should keep developer SQLite files usable without hand-written
    migrations every time the skill model grows.
    """
    engine = get_engine()
    inspector = inspect(engine)
    if not inspector.has_table("skill"):
        return

    columns = {column["name"] for column in inspector.get_columns("skill")}
    with engine.begin() as conn:
        if "source" not in columns:
            conn.execute(text("ALTER TABLE skill ADD COLUMN source VARCHAR"))
        if "github_repo_url" not in columns:
            conn.execute(text("ALTER TABLE skill ADD COLUMN github_repo_url VARCHAR"))
        if "github_ref" not in columns:
            conn.execute(text("ALTER TABLE skill ADD COLUMN github_ref VARCHAR"))
        if "github_ref_type" not in columns:
            conn.execute(text("ALTER TABLE skill ADD COLUMN github_ref_type VARCHAR"))
        if "github_skill_path" not in columns:
            conn.execute(text("ALTER TABLE skill ADD COLUMN github_skill_path VARCHAR"))
        conn.execute(
            text(
                "UPDATE skill "
                "SET source = CASE "
                "WHEN builtin = 1 THEN 'builtin' "
                "WHEN source IS NULL OR source = '' OR source = 'user' THEN 'manual' "
                "ELSE source "
                "END"
            )
        )
