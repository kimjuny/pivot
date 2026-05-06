"""Persistence service for extension hook execution logs."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from app.models.extension import ExtensionHookExecution
from sqlmodel import Session, col, select


def _dump_optional_json(payload: Any) -> str | None:
    """Serialize one optional payload into compact JSON text."""
    if payload is None:
        return None
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class ExtensionHookExecutionService:
    """Append-only CRUD service for packaged hook execution records."""

    def __init__(self, db: Session) -> None:
        """Store the active database session."""
        self.db = db

    def create_execution(
        self,
        *,
        session_id: str | None,
        task_id: str,
        trace_id: str | None,
        iteration: int,
        agent_id: int,
        release_id: int | None,
        extension_package_id: str,
        extension_version: str,
        hook_event: str,
        hook_callable: str,
        status: str,
        hook_context_payload: Any = None,
        effects_payload: Any = None,
        error_payload: Any = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        duration_ms: int = 0,
    ) -> ExtensionHookExecution:
        """Persist one hook execution row.

        Args:
            session_id: Owning session UUID when available.
            task_id: Owning task UUID.
            trace_id: Iteration trace identifier when available.
            iteration: Iteration index associated with the hook.
            agent_id: Agent executing the extension bundle.
            release_id: Pinned release identifier when available.
            extension_package_id: Canonical package id such as ``@acme/providers``.
            extension_version: Installed package version that ran the hook.
            hook_event: Lifecycle event name.
            hook_callable: Exported callable invoked for the hook.
            status: Execution status such as ``succeeded`` or ``failed``.
            hook_context_payload: Structured hook context passed to the callable.
            effects_payload: Structured effects returned by the hook.
            error_payload: Structured failure payload when execution failed.
            started_at: Optional explicit start timestamp.
            finished_at: Optional explicit finish timestamp.
            duration_ms: Hook wall-clock duration in milliseconds.

        Returns:
            The persisted execution row.
        """
        normalized_started_at = started_at or datetime.now(UTC)
        normalized_finished_at = finished_at or datetime.now(UTC)
        row = ExtensionHookExecution(
            session_id=session_id,
            task_id=task_id,
            trace_id=trace_id,
            iteration=iteration,
            agent_id=agent_id,
            release_id=release_id,
            extension_package_id=extension_package_id,
            extension_version=extension_version,
            hook_event=hook_event,
            hook_callable=hook_callable,
            status=status,
            hook_context_json=_dump_optional_json(hook_context_payload),
            effects_json=_dump_optional_json(effects_payload),
            error_json=_dump_optional_json(error_payload),
            started_at=normalized_started_at,
            finished_at=normalized_finished_at,
            duration_ms=duration_ms,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def list_executions(
        self,
        *,
        session_id: str | None = None,
        task_id: str | None = None,
        trace_id: str | None = None,
        iteration: int | None = None,
        extension_package_id: str | None = None,
        extension_package_ids: set[str] | None = None,
        hook_event: str | None = None,
        limit: int = 200,
    ) -> list[ExtensionHookExecution]:
        """List recent hook execution records using optional filters."""
        if extension_package_ids is not None and not extension_package_ids:
            return []

        statement = select(ExtensionHookExecution)
        if session_id is not None:
            statement = statement.where(ExtensionHookExecution.session_id == session_id)
        if task_id is not None:
            statement = statement.where(ExtensionHookExecution.task_id == task_id)
        if trace_id is not None:
            statement = statement.where(ExtensionHookExecution.trace_id == trace_id)
        if iteration is not None:
            statement = statement.where(ExtensionHookExecution.iteration == iteration)
        if extension_package_id is not None:
            statement = statement.where(
                ExtensionHookExecution.extension_package_id == extension_package_id
            )
        if extension_package_ids is not None:
            statement = statement.where(
                col(ExtensionHookExecution.extension_package_id).in_(
                    extension_package_ids
                )
            )
        if hook_event is not None:
            statement = statement.where(ExtensionHookExecution.hook_event == hook_event)

        normalized_limit = max(1, min(limit, 1000))
        statement = statement.order_by(col(ExtensionHookExecution.id).desc()).limit(
            normalized_limit
        )
        return list(self.db.exec(statement).all())

    def get_execution(self, execution_id: int) -> ExtensionHookExecution | None:
        """Return one hook execution row by primary key."""
        return self.db.get(ExtensionHookExecution, execution_id)
