"""Service for the session-level task queue.

Serializes work items on the same Pivot session so that automations and
future user-input injections do not conflict with a running ReactTask.
"""

from datetime import UTC, datetime

from app.models.session_task_queue import SessionTaskQueue
from app.utils.logging_config import get_logger
from sqlalchemy import case, literal
from sqlmodel import Session, col, select

logger = get_logger("session_task_queue_service")


class SessionTaskQueueService:
    """CRUD and queue operations for ``SessionTaskQueue`` rows."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def enqueue(
        self,
        *,
        session_id: str,
        queue_type: str,
        source: str,
        source_ref_id: int | None = None,
        prompt: str,
    ) -> SessionTaskQueue:
        """Insert a new pending item into the queue."""
        item = SessionTaskQueue(
            session_id=session_id,
            queue_type=queue_type,
            source=source,
            source_ref_id=source_ref_id,
            prompt=prompt,
            status="pending",
            created_at=datetime.now(UTC),
        )
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item

    def dequeue_next(self, session_id: str) -> SessionTaskQueue | None:
        """Claim the highest-priority pending item for a session.

        Ordering: ``user_input`` before ``automation``, then FIFO by
        ``created_at``.  The item's status is atomically set to
        ``"processing"``.
        """
        is_user = SessionTaskQueue.source == "user_input"
        priority_order = case(
            (is_user, literal(0)),  # type: ignore[arg-type]
            else_=literal(1),
        )
        stmt = (
            select(SessionTaskQueue)
            .where(
                SessionTaskQueue.session_id == session_id,
                SessionTaskQueue.status == "pending",
            )
            .order_by(priority_order, col(SessionTaskQueue.created_at).asc())
            .limit(1)
            .with_for_update()
        )
        item = self.db.exec(stmt).first()
        if item is None:
            return None
        item.status = "processing"
        item.started_at = datetime.now(UTC)
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item

    def mark_completed(self, item: SessionTaskQueue) -> None:
        """Mark a queue item as successfully completed."""
        item.status = "completed"
        item.finished_at = datetime.now(UTC)
        self.db.add(item)
        self.db.commit()

    def mark_failed(self, item: SessionTaskQueue, error: str) -> None:
        """Mark a queue item as failed with an error message."""
        item.status = "failed"
        item.finished_at = datetime.now(UTC)
        self.db.add(item)
        self.db.commit()
        logger.warning("Queue item %s failed: %s", item.queue_id, error)

    def get_pending_for_session(self, session_id: str) -> list[SessionTaskQueue]:
        """Return all pending items for a session (used by executor to check)."""
        stmt = (
            select(SessionTaskQueue)
            .where(
                SessionTaskQueue.session_id == session_id,
                SessionTaskQueue.status == "pending",
            )
            .order_by(col(SessionTaskQueue.created_at).asc())
        )
        return list(self.db.exec(stmt).all())

    def has_pending_for_source_ref(self, source_ref_id: int) -> bool:
        """Check whether a source reference already has a pending item."""
        stmt = select(SessionTaskQueue).where(
            SessionTaskQueue.source_ref_id == source_ref_id,
            SessionTaskQueue.status == "pending",
        )
        return self.db.exec(stmt).first() is not None

    def cancel_pending_by_source_ref(self, source_ref_id: int) -> None:
        """Cancel all pending items for a given source reference."""
        stmt = select(SessionTaskQueue).where(
            SessionTaskQueue.source_ref_id == source_ref_id,
            SessionTaskQueue.status == "pending",
        )
        for item in self.db.exec(stmt).all():
            item.status = "cancelled"
            item.finished_at = datetime.now(UTC)
            self.db.add(item)
        self.db.commit()

    def get_all_pending(self) -> list[SessionTaskQueue]:
        """Return all pending items grouped for the scheduler to scan."""
        stmt = (
            select(SessionTaskQueue)
            .where(
                SessionTaskQueue.status == "pending",
            )
            .order_by(col(SessionTaskQueue.created_at).asc())
        )
        return list(self.db.exec(stmt).all())

    def reap_stale_items(self, timeout_seconds: int = 600) -> list[SessionTaskQueue]:
        """Mark processing items older than *timeout_seconds* as failed.

        Returns the list of reaped items so the caller can update
        associated records (e.g. AutomationRun).
        """
        cutoff = datetime.now(UTC).timestamp() - timeout_seconds
        stmt = select(SessionTaskQueue).where(
            SessionTaskQueue.status == "processing",
        )
        reaped: list[SessionTaskQueue] = []
        for item in self.db.exec(stmt).all():
            if item.started_at is not None and item.started_at.timestamp() < cutoff:
                self.mark_failed(item, "Reaped by stale-queue watchdog")
                reaped.append(item)
        return reaped
