from typing import Any

from app.models.llm import LLM
from sqlmodel import Session, select


class LLMCRUD:
    """CRUD operations for LLM model.

    Provides Create, Read, Update, Delete operations for LLM configurations.
    """

    def __init__(self, model: type[LLM]):
        """Initialize the CRUD with the LLM model.

        Args:
            model: The LLM model class.
        """
        self.model = model

    def get(self, id: int, session: Session) -> LLM | None:
        """Retrieve a single LLM by its primary key.

        Args:
            id: The primary key of the LLM to retrieve.
            session: The database session to use for the query.

        Returns:
            The LLM instance if found, None otherwise.
        """
        return session.get(self.model, id)

    def get_all(self, session: Session, skip: int = 0, limit: int = 100) -> list[LLM]:
        """Retrieve multiple LLMs with pagination support.

        Args:
            session: The database session to use for the query.
            skip: Number of records to skip (for pagination).
            limit: Maximum number of records to return.

        Returns:
            A list of LLM instances.
        """
        statement = select(self.model).offset(skip).limit(limit)
        return session.exec(statement).all()

    def get_by_name(self, name: str, session: Session) -> LLM | None:
        """Retrieve an LLM by its unique name.

        Args:
            name: The name of the LLM to retrieve.
            session: The database session to use for the query.

        Returns:
            The LLM instance if found, None otherwise.
        """
        statement = select(LLM).where(LLM.name == name)
        return session.exec(statement).first()

    def create(self, session: Session, **kwargs: Any) -> LLM:
        """Create a new LLM record in the database.

        Args:
            session: The database session to use for the transaction.
            **kwargs: Field names and values for the new LLM.

        Returns:
            The created LLM instance with ID populated.
        """
        db_obj = self.model(**kwargs)
        session.add(db_obj)
        session.commit()
        session.refresh(db_obj)
        return db_obj

    def update(self, id: int, session: Session, **kwargs: Any) -> LLM | None:
        """Update an existing LLM by its primary key.

        Args:
            id: The primary key of the LLM to update.
            session: The database session to use for the transaction.
            **kwargs: Field names and values to update.

        Returns:
            The updated LLM instance if found, None otherwise.
        """
        db_obj = self.get(id, session)
        if db_obj:
            for key, value in kwargs.items():
                setattr(db_obj, key, value)
            session.commit()
            session.refresh(db_obj)
            return db_obj
        return None

    def delete(self, id: int, session: Session) -> bool:
        """Delete an LLM by its primary key.

        Args:
            id: The primary key of the LLM to delete.
            session: The database session to use for the transaction.

        Returns:
            True if the LLM was deleted, False if not found.
        """
        db_obj = self.get(id, session)
        if db_obj:
            session.delete(db_obj)
            session.commit()
            return True
        return False


llm = LLMCRUD(LLM)
