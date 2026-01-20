from sqlmodel import Session, select

from server.app.models.build import BuildHistory, BuildSession


def create_session(db: Session) -> BuildSession:
    session = BuildSession()
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_session(db: Session, session_id: str) -> BuildSession | None:
    return db.get(BuildSession, session_id)


def add_history(
    db: Session,
    session_id: str,
    role: str,
    content: str,
    agent_snapshot: str | None = None,
) -> BuildHistory:
    history = BuildHistory(
        session_id=session_id, role=role, content=content, agent_snapshot=agent_snapshot
    )
    db.add(history)
    db.commit()
    db.refresh(history)
    return history


def get_session_history(db: Session, session_id: str) -> list[BuildHistory]:
    statement = (
        select(BuildHistory)
        .where(BuildHistory.session_id == session_id)
        .order_by(BuildHistory.created_at)
    )
    return db.exec(statement).all()
