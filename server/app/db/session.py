import os
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlmodel import Session, SQLModel


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
    with Session(engine) as session:
        yield session


def init_db():
    """Initialize the database by creating all tables.

    This function creates all tables defined in SQLModel metadata
    if they don't already exist. It's safe to call this multiple times.
    """
    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    ensure_llm_schema_compatibility()
    ensure_react_schema_compatibility()
    print("Database initialized successfully")


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
    if not inspector.has_table("reacttask"):
        return

    columns = {column["name"] for column in inspector.get_columns("reacttask")}
    with engine.begin() as conn:
        if "skill_selection_result" not in columns:
            conn.execute(text("ALTER TABLE reacttask ADD COLUMN skill_selection_result VARCHAR"))
