"""Safe replay service for packaged extension lifecycle hooks."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.services.extension_hook_execution_service import (
    ExtensionHookExecutionService,
)
from app.services.extension_hook_service import ExtensionHookService
from app.services.extension_service import ExtensionService

if TYPE_CHECKING:
    from sqlmodel import Session


class ExtensionHookReplayService:
    """Replay one historical hook execution without mutating runtime state.

    Why: lifecycle hooks are now observable and queryable, but debugging still
    needs a safe way to rerun one historical hook input against the exact pinned
    package version. Replay should stay read-only and must not publish emitted
    events back into the live task stream.
    """

    def __init__(self, db: Session) -> None:
        """Store the active database session and dependent CRUD services."""
        self.db = db
        self.execution_service = ExtensionHookExecutionService(db)
        self.extension_service = ExtensionService(db)

    async def replay_execution(self, *, execution_id: int) -> dict[str, Any]:
        """Replay one historical hook execution record.

        Args:
            execution_id: Primary key of the execution record to replay.

        Returns:
            A normalized replay result payload.

        Raises:
            ValueError: If the execution is missing, lacks recorded context, or
                the matching extension version is no longer installed.
        """
        execution = self.execution_service.get_execution(execution_id)
        if execution is None:
            raise ValueError("Hook execution record not found.")

        hook_context = self._load_hook_context(execution_id=execution_id)
        hook_context["execution_mode"] = "replay"
        installation = self.extension_service.get_installation_by_package_version(
            package_id=execution.extension_package_id,
            version=execution.extension_version,
        )
        if installation is None:
            raise ValueError(
                "The recorded extension version is no longer installed locally."
            )

        bundle_entry = self.extension_service.build_installation_runtime_entry(
            installation=installation,
            priority=0,
            config={},
        )
        hook_service = ExtensionHookService([bundle_entry])
        replayed_at = datetime.now(UTC)

        try:
            effects = await hook_service.replay_hook(
                extension_package_id=execution.extension_package_id,
                extension_version=execution.extension_version,
                event_name=execution.hook_event,
                hook_callable=execution.hook_callable,
                hook_context=hook_context,
            )
        except Exception as exc:
            return {
                "execution_id": execution.id or 0,
                "extension_package_id": execution.extension_package_id,
                "extension_version": execution.extension_version,
                "hook_event": execution.hook_event,
                "hook_callable": execution.hook_callable,
                "status": "failed",
                "effects": None,
                "error": {
                    "type": exc.__class__.__name__,
                    "message": str(exc),
                },
                "replayed_at": replayed_at,
            }

        return {
            "execution_id": execution.id or 0,
            "extension_package_id": execution.extension_package_id,
            "extension_version": execution.extension_version,
            "hook_event": execution.hook_event,
            "hook_callable": execution.hook_callable,
            "status": "succeeded",
            "effects": effects,
            "error": None,
            "replayed_at": replayed_at,
        }

    def _load_hook_context(self, *, execution_id: int) -> dict[str, Any]:
        """Load and validate the persisted hook context for one execution row."""
        execution = self.execution_service.get_execution(execution_id)
        if execution is None:
            raise ValueError("Hook execution record not found.")
        if execution.hook_context_json is None:
            raise ValueError("The hook execution does not include replay context.")

        try:
            payload = json.loads(execution.hook_context_json)
        except json.JSONDecodeError as exc:
            raise ValueError("The stored replay context is invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise ValueError("The stored replay context must be a JSON object.")
        return payload
