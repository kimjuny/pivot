import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel


def get_engine():
    database_url = os.getenv("DATABASE_URL", "sqlite:///./pivot.db")
    return create_engine(database_url, connect_args={"check_same_thread": False})


def get_session() -> Generator[Session, None, None]:
    engine = get_engine()
    with Session(engine) as session:
        yield session


def init_db():
    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    print("Database initialized successfully")
