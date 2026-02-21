import os
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
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
        if database_url.startswith("sqlite:////"):
            # Absolute path form sqlite:////abs/path
            db_path = Path("/" + database_url.removeprefix("sqlite:////"))
        else:
            db_path = Path(database_url.removeprefix("sqlite:///"))
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
    print("Database initialized successfully")
