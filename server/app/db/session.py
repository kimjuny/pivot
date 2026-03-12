import os
from collections.abc import Generator
from importlib import import_module
from pathlib import Path
from typing import Final

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel

_REQUIRED_TABLES: Final[set[str]] = {
    "agent",
    "agentchannelbinding",
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
    "scene",
    "session",
    "sessionmemory",
    "skill",
    "subscene",
    "user",
}


def get_engine():
    """Create and return a SQLAlchemy database engine.

    The database URL is read from the DATABASE_URL environment variable,
    with a default fallback to SQLite.

    Returns:
        A SQLAlchemy engine instance configured for the database.
    """
    database_url = os.getenv("DATABASE_URL", "sqlite:///./pivot.db")

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

    ensure_llm_schema_compatibility()
    ensure_react_schema_compatibility()
    ensure_file_schema_compatibility()

    from app.api.auth import init_default_user
    from app.services.skill_service import sync_skill_registry

    with Session(engine) as session:
        init_default_user(session)
        sync_skill_registry(session)


def ensure_llm_schema_compatibility() -> None:
    """Apply additive schema updates for legacy LLM tables.

    Why: SQLModel's ``create_all`` does not add newly introduced columns
    to existing tables. We backfill additive LLM columns in-place so
    upgrades remain non-breaking for existing deployments.
    """
    engine = get_engine()
    inspector = inspect(engine)
    if not inspector.has_table("llm"):
        return

    columns = {column["name"] for column in inspector.get_columns("llm")}
    with engine.begin() as conn:
        if "thinking" not in columns:
            conn.execute(text("ALTER TABLE llm ADD COLUMN thinking VARCHAR"))
            conn.execute(
                text("UPDATE llm SET thinking = 'auto' WHERE thinking IS NULL")
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
