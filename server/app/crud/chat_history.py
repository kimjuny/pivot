from typing import Generic, Optional, TypeVar

from sqlmodel import Session, SQLModel, select

from app.models.agent import ChatHistory

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


class ChatHistoryCRUD(CRUDBase[ChatHistory]):
    def get_by_agent_and_user(
        self, 
        agent_id: int, 
        user: str, 
        session: Session,
        skip: int = 0, 
        limit: int = 100
    ) -> list[ChatHistory]:
        """
        Get chat history for a specific agent and user, ordered by creation time.
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
    ) -> Optional[str]:
        """
        Get the latest update_scene from chat history for a specific agent and user.
        Returns update_scene JSON string or None if not found.
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
        """
        Create a user message in chat history.
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
        reason: Optional[str],
        update_scene: Optional[str],
        session: Session
    ) -> ChatHistory:
        """
        Create an agent message in chat history.
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
        """
        Delete all chat history for a specific agent and user.
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
