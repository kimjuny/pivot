from typing import Generic, TypeVar

from sqlmodel import Session, SQLModel, select

from app.models.agent import Connection

ModelType = TypeVar("ModelType", bound=SQLModel)


class CRUDBase(Generic[ModelType]):
    def __init__(self, model: type[ModelType]):
        self.model = model

    def get(self, id: int, session: Session) -> ModelType | None:
        return session.get(self.model, id)

    def get_all(self, session: Session, skip: int = 0, limit: int = 100) -> list[ModelType]:
        statement = select(self.model).offset(skip).limit(limit)
        return session.exec(statement).all()

    def create(self, session: Session, **kwargs) -> ModelType:
        db_obj = self.model(**kwargs)
        session.add(db_obj)
        session.commit()
        session.refresh(db_obj)
        return db_obj

    def update(self, id: int, session: Session, **kwargs) -> ModelType | None:
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


class ConnectionCRUD(CRUDBase[Connection]):
    def get_by_from_subscene(self, from_subscene: str, session: Session) -> list[Connection]:
        statement = select(Connection).where(Connection.from_subscene == from_subscene)
        return session.exec(statement).all()

    def get_by_from_subscene_id(self, from_subscene_id: int, session: Session) -> list[Connection]:
        statement = select(Connection).where(Connection.from_subscene_id == from_subscene_id)
        return session.exec(statement).all()


connection = ConnectionCRUD(Connection)
