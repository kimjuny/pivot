from typing import Generic, TypeVar

from app.models.agent import ChatHistory
from sqlmodel import Session, SQLModel, select

ModelType = TypeVar("ModelType", bound=SQLModel)


class CRUDBase(Generic[ModelType]):
    """Base CRUD operations for SQLModel objects.

    Provides generic Create, Read, Update, Delete (CRUD) operations
    for any SQLModel type. This class is designed to be inherited
    by specific CRUD implementations for different models.

    Type Args:
        ModelType: The SQLModel class this CRUD instance operates on.
    """

    def __init__(self, model: type[ModelType]):
        """Initialize the CRUD base with a specific model.

        Args:
            model: The SQLModel class to perform CRUD operations on.
        """
        self.model = model

    def get(self, id: int, session: Session) -> ModelType | None:
        """Retrieve a single record by its primary key.

        Args:
            id: The primary key of the record to retrieve.
            session: The database session to use for the query.

        Returns:
            The model instance if found, None otherwise.
        """
        return session.get(self.model, id)

    def get_all(self, session: Session, skip: int = 0, limit: int = 100) -> list[ModelType]:
        """Retrieve multiple records with pagination support.

        Args:
            session: The database session to use for the query.
            skip: Number of records to skip (for pagination).
            limit: Maximum number of records to return.

        Returns:
            A list of model instances.
        """
        statement = select(self.model).offset(skip).limit(limit)
        return session.exec(statement).all()

    def create(self, session: Session, **kwargs) -> ModelType:
        """Create a new record in the database.

        Args:
            session: The database session to use for the transaction.
            **kwargs: Field names and values for the new record.

        Returns:
            The created model instance with ID populated.
        """
        db_obj = self.model(**kwargs)
        session.add(db_obj)
        session.commit()
        session.refresh(db_obj)
        return db_obj

    def update(self, id: int, session: Session, **kwargs) -> ModelType | None:
        """Update an existing record by its primary key.

        Args:
            id: The primary key of the record to update.
            session: The database session to use for the transaction.
            **kwargs: Field names and values to update.

        Returns:
            The updated model instance if found, None otherwise.
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
        """Delete a record by its primary key.

        Args:
            id: The primary key of the record to delete.
            session: The database session to use for the transaction.

        Returns:
            True if the record was deleted, False if not found.
        """
        db_obj = self.get(id, session)
        if db_obj:
            session.delete(db_obj)
            session.commit()
            return True
        return False


class ChatHistoryCRUD(CRUDBase[ChatHistory]):
    """CRUD operations for ChatHistory model.

    Extends base CRUD operations with chat history-specific queries
    for filtering by agent, user, and managing conversation state.
    """

    def get_by_agent_and_user(
        self,
        agent_id: int,
        user: str,
        session: Session,
        skip: int = 0,
        limit: int = 100
    ) -> list[ChatHistory]:
        """Get chat history for a specific agent and user, ordered by creation time.

        Args:
            agent_id: The ID of the agent.
            user: The username of the user.
            session: The database session to use for the query.
            skip: Number of records to skip (for pagination).
            limit: Maximum number of records to return.

        Returns:
            A list of ChatHistory instances ordered by creation time.
        """
        statement = (
            select(ChatHistory)
            .where(ChatHistory.agent_id == agent_id)
            .where(ChatHistory.user == user)
            .order_by(ChatHistory.create_time)
            .offset(skip)
            .limit(limit)
        )
        return session.exec(statement).all()

    def get_latest_update_scene(
        self,
        agent_id: int,
        user: str,
        session: Session
    ) -> str | None:
        """Get the latest update_scene from chat history for a specific agent and user.

        This is used to restore the conversation state, specifically the
        scene graph state from the most recent agent response.

        Args:
            agent_id: The ID of the agent.
            user: The username of the user.
            session: The database session to use for the query.

        Returns:
            The update_scene JSON string if found, None otherwise.
        """
        statement = (
            select(ChatHistory)
            .where(ChatHistory.agent_id == agent_id)
            .where(ChatHistory.user == user)
            .where(ChatHistory.update_scene.isnot(None))  # type: ignore[arg-type]
            .order_by(ChatHistory.create_time.desc())  # type: ignore[attr-defined]
            .limit(1)
        )
        result = session.exec(statement).first()
        return result.update_scene if result else None

    def create_user_message(
        self,
        agent_id: int,
        user: str,
        message: str,
        session: Session
    ) -> ChatHistory:
        """Create a user message in chat history.

        Args:
            agent_id: The ID of the agent.
            user: The username of the user.
            message: The message content from the user.
            session: The database session to use for the transaction.

        Returns:
            The created ChatHistory instance.
        """
        return self.create(
            session,
            agent_id=agent_id,
            user=user,
            role="user",
            message=message
        )

    def create_agent_message(
        self,
        agent_id: int,
        user: str,
        message: str,
        reason: str | None,
        update_scene: str | None,
        session: Session
    ) -> ChatHistory:
        """Create an agent message in chat history.

        Args:
            agent_id: The ID of the agent.
            user: The username of the user.
            message: The message content from the agent.
            reason: The reasoning behind the agent's response.
            update_scene: The updated scene graph in JSON format.
            session: The database session to use for the transaction.

        Returns:
            The created ChatHistory instance.
        """
        return self.create(
            session,
            agent_id=agent_id,
            user=user,
            role="agent",
            message=message,
            reason=reason,
            update_scene=update_scene
        )

    def delete_by_agent_and_user(
        self,
        agent_id: int,
        user: str,
        session: Session
    ) -> bool:
        """Delete all chat history for a specific agent and user.

        Args:
            agent_id: The ID of the agent.
            user: The username of the user.
            session: The database session to use for the transaction.

        Returns:
            True if any records were deleted, False otherwise.
        """
        statement = (
            select(ChatHistory)
            .where(ChatHistory.agent_id == agent_id)
            .where(ChatHistory.user == user)
        )
        results = session.exec(statement).all()
        for result in results:
            session.delete(result)
        session.commit()
        return len(results) > 0


chat_history = ChatHistoryCRUD(ChatHistory)
