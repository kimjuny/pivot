from typing import Any, Generic, TypeVar

from app.models.agent import Agent
from sqlmodel import Session, SQLModel, select

ModelType = TypeVar("ModelType", bound=SQLModel)


class CRUDBase(Generic[ModelType]):
    """Base CRUD operations for SQLModel objects."""

    def __init__(self, model: type[ModelType]):
        self.model = model

    def get(self, id: int, session: Session) -> ModelType | None:
        return session.get(self.model, id)

    def get_all(
        self, session: Session, skip: int = 0, limit: int = 100
    ) -> list[ModelType]:
        statement = select(self.model).offset(skip).limit(limit)
        return list(session.exec(statement).all())

    def create(self, session: Session, **kwargs: Any) -> ModelType:
        db_obj = self.model(**kwargs)
        session.add(db_obj)
        session.commit()
        session.refresh(db_obj)
        return db_obj

    def update(self, id: int, session: Session, **kwargs: Any) -> ModelType | None:
        db_obj = self.get(id, session)
        if db_obj:
            for key, value in kwargs.items():
                setattr(db_obj, key, value)
            session.commit()
            session.refresh(db_obj)
            return db_obj
        return None

    def delete(self, id: int, session: Session) -> bool:
        db_obj = self.get(id, session)
        if db_obj:
            session.delete(db_obj)
            session.commit()
            return True
        return False


class AgentCRUD(CRUDBase[Agent]):
    """CRUD operations for Agent model."""

    def get_by_name(self, name: str, session: Session) -> Agent | None:
        statement = select(Agent).where(Agent.name == name)
        return session.exec(statement).first()


agent = AgentCRUD(Agent)
