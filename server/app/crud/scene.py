from typing import Any, Generic, TypeVar

from app.models.agent import Agent, Connection, Scene, Subscene
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

    def get_all(
        self, session: Session, skip: int = 0, limit: int = 100
    ) -> list[ModelType]:
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

    def create(self, session: Session, **kwargs: Any) -> ModelType:
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

    def update(self, id: int, session: Session, **kwargs: Any) -> ModelType | None:
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


class SceneCRUD(CRUDBase[Scene]):
    """CRUD operations for Scene model.

    Extends base CRUD operations with scene-specific queries
    for filtering by agent and name.
    """

    def get_by_agent_id(
        self, agent_id: int, session: Session, skip: int = 0, limit: int = 100
    ) -> list[Scene]:
        """Retrieve all scenes associated with a specific agent.

        Args:
            agent_id: The ID of the agent to filter scenes by.
            session: The database session to use for the query.
            skip: Number of records to skip (for pagination).
            limit: Maximum number of records to return.

        Returns:
            A list of Scene instances belonging to the agent.
        """
        statement = (
            select(Scene).where(Scene.agent_id == agent_id).offset(skip).limit(limit)
        )
        return session.exec(statement).all()

    def get_by_name(self, name: str, session: Session) -> Scene | None:
        """Retrieve a scene by its name.

        Args:
            name: The name of the scene to retrieve.
            session: The database session to use for the query.

        Returns:
            The Scene instance if found, None otherwise.
        """
        statement = select(Scene).where(Scene.name == name)
        return session.exec(statement).first()

    def get_with_subscenes(self, id: int, session: Session) -> Scene | None:
        """Retrieve a scene and refresh to load related subscenes.

        Args:
            id: The primary key of the scene to retrieve.
            session: The database session to use for the query.

        Returns:
            The Scene instance with subscenes loaded if found, None otherwise.
        """
        scene = self.get(id, session)
        if scene:
            session.refresh(scene)
        return scene


class SubsceneCRUD(CRUDBase[Subscene]):
    """CRUD operations for Subscene model.

    Extends base CRUD operations with subscene-specific queries
    for filtering by scene and name.
    """

    def get_by_scene_id(self, scene_id: int, session: Session) -> list[Subscene]:
        """Retrieve all subscenes belonging to a specific scene.

        Args:
            scene_id: The ID of the scene to filter subscenes by.
            session: The database session to use for the query.

        Returns:
            A list of Subscene instances belonging to the scene.
        """
        statement = select(Subscene).where(Subscene.scene_id == scene_id)
        return session.exec(statement).all()

    def get_by_name(
        self, name: str, scene_id: int, session: Session
    ) -> Subscene | None:
        """Retrieve a subscene by name within a specific scene.

        Args:
            name: The name of the subscene to retrieve.
            scene_id: The ID of the scene the subscene belongs to.
            session: The database session to use for the query.

        Returns:
            The Subscene instance if found, None otherwise.
        """
        statement = select(Subscene).where(
            (Subscene.name == name) & (Subscene.scene_id == scene_id)
        )
        return session.exec(statement).first()


class ConnectionCRUD(CRUDBase[Connection]):
    """CRUD operations for Connection model.

    Extends base CRUD operations with connection-specific queries
    for filtering by source subscene.
    """

    def get_by_from_subscene(
        self, from_subscene: str, session: Session
    ) -> list[Connection]:
        """Retrieve all connections originating from a specific subscene.

        Args:
            from_subscene: The name of the source subscene.
            session: The database session to use for the query.

        Returns:
            A list of Connection instances originating from the subscene.
        """
        statement = select(Connection).where(Connection.from_subscene == from_subscene)
        return session.exec(statement).all()


agent = CRUDBase(Agent)
scene = SceneCRUD(Scene)
subscene = SubsceneCRUD(Subscene)
connection = ConnectionCRUD(Connection)
