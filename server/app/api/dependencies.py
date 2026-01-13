"""Database session dependency for API endpoints.

This module provides the database session dependency injection
used across all API endpoints.
"""
from collections.abc import Generator

from app.db.session import get_session
from sqlmodel import Session


def get_db() -> Generator[Session, None, None]:
    """Get database session for dependency injection.

    Yields:
        A database session that will be automatically closed after use.
    """
    yield from get_session()
