from typing import Optional, List, TypeVar, Generic, Type
from sqlmodel import Session, select, SQLModel
from app.models.agent import Agent, Scene, Subscene, Connection


ModelType = TypeVar("ModelType", bound=SQLModel)


class CRUDBase(Generic[ModelType]):
    def __init__(self, model: Type[ModelType]):
        self.model = model

    def get(self, id: int, session: Session) -> Optional[ModelType]:
        return session.get(self.model, id)

    def get_all(self, session: Session, skip: int = 0, limit: int = 100) -> List[ModelType]:
        statement = select(self.model).offset(skip).limit(limit)
        return session.exec(statement).all()

    def create(self, session: Session, **kwargs) -> ModelType:
        db_obj = self.model(**kwargs)
        session.add(db_obj)
        session.commit()
        session.refresh(db_obj)
        return db_obj

    def update(self, id: int, session: Session, **kwargs) -> Optional[ModelType]:
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


class SubsceneCRUD(CRUDBase[Subscene]):
    def get_by_scene_id(self, scene_id: int, session: Session) -> List[Subscene]:
        statement = select(Subscene).where(Subscene.scene_id == scene_id)
        return session.exec(statement).all()

    def get_by_name(self, name: str, scene_id: int, session: Session) -> Optional[Subscene]:
        statement = select(Subscene).where(
            (Subscene.name == name) & (Subscene.scene_id == scene_id)
        )
        return session.exec(statement).first()


subscene = SubsceneCRUD(Subscene)
