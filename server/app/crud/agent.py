from typing import Generic, Optional, TypeVar

from sqlmodel import Session, SQLModel, select

from app.models.agent import Agent, Connection, Scene, Subscene

ModelType = TypeVar("ModelType", bound=SQLModel)


class CRUDBase(Generic[ModelType]):
    def __init__(self, model: type[ModelType]):
        self.model = model

    def get(self, id: int, session: Session) -> Optional[ModelType]:
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


class AgentCRUD(CRUDBase[Agent]):
    pass


class SceneCRUD(CRUDBase[Scene]):
    def get_by_agent_id(self, agent_id: int, session: Session) -> list[Scene]:
        statement = select(Scene).where(Scene.agent_id == agent_id)
        return session.exec(statement).all()

    def get_by_name(self, name: str, session: Session) -> Optional[Scene]:
        statement = select(Scene).where(Scene.name == name)
        return session.exec(statement).first()

    def get_with_subscenes(self, id: int, session: Session) -> Optional[Scene]:
        scene = self.get(id, session)
        if scene:
            session.refresh(scene)
        return scene


class SubsceneCRUD(CRUDBase[Subscene]):
    def get_by_scene_id(self, scene_id: int, session: Session) -> list[Subscene]:
        statement = select(Subscene).where(Subscene.scene_id == scene_id)
        return session.exec(statement).all()

    def get_by_name(self, name: str, scene_id: int, session: Session) -> Optional[Subscene]:
        statement = select(Subscene).where(
            (Subscene.name == name) & (Subscene.scene_id == scene_id)
        )
        return session.exec(statement).first()


class ConnectionCRUD(CRUDBase[Connection]):
    def get_by_from_subscene(self, from_subscene: str, session: Session) -> list[Connection]:
        statement = select(Connection).where(Connection.from_subscene == from_subscene)
        return session.exec(statement).all()


agent = AgentCRUD(Agent)
scene = SceneCRUD(Scene)
subscene = SubsceneCRUD(Subscene)
connection = ConnectionCRUD(Connection)
