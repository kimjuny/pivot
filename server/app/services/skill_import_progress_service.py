"""In-memory progress events for local skill imports."""

from __future__ import annotations

import asyncio
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class SkillImportSubscriber:
    """One live SSE subscriber for a skill import job."""

    queue: asyncio.Queue[dict[str, Any]]
    loop: asyncio.AbstractEventLoop


@dataclass
class SkillImportJob:
    """Mutable import job state shared between upload and SSE endpoints."""

    job_id: str
    user_id: int
    created_at: datetime
    events: list[dict[str, Any]] = field(default_factory=list)
    subscribers: list[SkillImportSubscriber] = field(default_factory=list)
    completed: bool = False


class SkillImportProgressService:
    """Coordinate skill import progress across upload and stream requests."""

    def __init__(self) -> None:
        self._jobs: dict[str, SkillImportJob] = {}
        self._lock = threading.Lock()

    def create_job(self, *, user_id: int) -> SkillImportJob:
        """Create one import job owned by a user."""
        job = SkillImportJob(
            job_id=uuid.uuid4().hex,
            user_id=user_id,
            created_at=datetime.now(UTC),
        )
        with self._lock:
            self._jobs[job.job_id] = job
        self.publish(
            job.job_id,
            stage="created",
            label="Preparing import",
            percent=0,
            status="running",
        )
        return job

    def get_job(self, *, job_id: str, user_id: int) -> SkillImportJob | None:
        """Return one user-owned job when present."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.user_id != user_id:
                return None
            return job

    def list_events(
        self, *, job_id: str, user_id: int, after_id: int = 0
    ) -> list[dict[str, Any]]:
        """Return persisted progress events newer than a cursor."""
        job = self.get_job(job_id=job_id, user_id=user_id)
        if job is None:
            return []
        with self._lock:
            return [event for event in job.events if int(event["event_id"]) > after_id]

    async def subscribe(
        self,
        *,
        job_id: str,
        user_id: int,
    ) -> SkillImportSubscriber:
        """Register one live subscriber for a job."""
        job = self.get_job(job_id=job_id, user_id=user_id)
        if job is None:
            raise ValueError("Skill import job not found.")
        subscriber = SkillImportSubscriber(
            queue=asyncio.Queue(),
            loop=asyncio.get_running_loop(),
        )
        with self._lock:
            job.subscribers.append(subscriber)
        return subscriber

    async def unsubscribe(
        self,
        *,
        job_id: str,
        subscriber: SkillImportSubscriber,
    ) -> None:
        """Remove one live subscriber."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.subscribers = [
                item for item in job.subscribers if item is not subscriber
            ]

    def publish(
        self,
        job_id: str,
        *,
        stage: str,
        label: str,
        percent: int,
        status: str = "running",
        detail: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Publish one progress event from any thread."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            event = {
                "event_id": len(job.events) + 1,
                "job_id": job_id,
                "stage": stage,
                "label": label,
                "percent": max(0, min(100, percent)),
                "status": status,
                "detail": detail,
                "metadata": metadata,
                "timestamp": datetime.now(UTC).isoformat(),
            }
            job.events.append(event)
            if status in {"complete", "failed"}:
                job.completed = True
            subscribers = list(job.subscribers)

        for subscriber in subscribers:
            subscriber.loop.call_soon_threadsafe(subscriber.queue.put_nowait, event)
        return event


_skill_import_progress_service = SkillImportProgressService()


def get_skill_import_progress_service() -> SkillImportProgressService:
    """Return the process-local skill import progress coordinator."""
    return _skill_import_progress_service
