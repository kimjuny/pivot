"""Centralized channel runtime health state management."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from app.models.channel import AgentChannelBinding

if TYPE_CHECKING:
    from sqlmodel import Session

ChannelRuntimeHealthStatus = Literal[
    "starting",
    "connecting",
    "healthy",
    "reconnecting",
    "degraded",
    "error",
    "disabled",
]

ChannelRuntimeErrorKind = Literal[
    "configuration",
    "dependency",
    "authentication",
    "network",
    "rate_limit",
    "provider",
    "unknown",
]

_RECOVERABLE_ERROR_KINDS: set[ChannelRuntimeErrorKind] = {
    "network",
    "rate_limit",
    "provider",
    "unknown",
}


class ChannelRuntimeHealthService:
    """Persist and classify channel runtime health for all providers."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def mark_starting(self, binding_id: int, message: str) -> None:
        """Mark a binding as starting without clearing existing failure history."""
        self._update_status(
            binding_id=binding_id,
            status="starting",
            message=message,
        )

    def mark_connecting(self, binding_id: int, message: str) -> None:
        """Mark a binding as connecting."""
        self._update_status(
            binding_id=binding_id,
            status="connecting",
            message=message,
        )

    def mark_healthy(self, binding_id: int, message: str) -> None:
        """Mark a binding as healthy and clear retry/failure state."""
        binding = self.db.get(AgentChannelBinding, binding_id)
        if binding is None:
            return
        now = datetime.now(UTC)
        binding.last_health_status = "healthy"
        binding.last_health_message = message
        binding.last_health_check_at = now
        binding.last_connected_at = now
        binding.consecutive_failure_count = 0
        binding.next_retry_at = None
        binding.last_error_fingerprint = None
        binding.updated_at = now
        self.db.add(binding)
        self.db.commit()

    def mark_disconnected(self, binding_id: int, message: str) -> None:
        """Mark a binding as temporarily disconnected/reconnecting."""
        binding = self.db.get(AgentChannelBinding, binding_id)
        if binding is None:
            return
        now = datetime.now(UTC)
        binding.last_health_status = "reconnecting"
        binding.last_health_message = message
        binding.last_health_check_at = now
        binding.last_disconnected_at = now
        binding.updated_at = now
        self.db.add(binding)
        self.db.commit()

    def mark_disabled(self, binding_id: int, message: str) -> None:
        """Mark a binding as disabled and clear retry state."""
        binding = self.db.get(AgentChannelBinding, binding_id)
        if binding is None:
            return
        now = datetime.now(UTC)
        binding.last_health_status = "disabled"
        binding.last_health_message = message
        binding.last_health_check_at = now
        binding.next_retry_at = None
        binding.updated_at = now
        self.db.add(binding)
        self.db.commit()

    def record_failure(
        self,
        binding_id: int,
        *,
        message: str,
        error_kind: str = "unknown",
        error: BaseException | None = None,
    ) -> None:
        """Record a runtime failure and compute retry/backoff state."""
        binding = self.db.get(AgentChannelBinding, binding_id)
        if binding is None:
            return

        now = datetime.now(UTC)
        failure_count = (binding.consecutive_failure_count or 0) + 1
        is_recoverable = error_kind in _RECOVERABLE_ERROR_KINDS
        retry_delay = self._retry_delay(failure_count) if is_recoverable else None

        binding.last_health_status = "degraded" if is_recoverable else "error"
        binding.last_health_message = message[:500]
        binding.last_health_check_at = now
        binding.last_disconnected_at = now
        binding.consecutive_failure_count = failure_count
        binding.next_retry_at = now + retry_delay if retry_delay is not None else None
        binding.last_error_fingerprint = self._fingerprint(
            message=message,
            error_kind=error_kind,
            error=error,
        )
        binding.updated_at = now
        self.db.add(binding)
        self.db.commit()

    def clear_retry(self, binding_id: int) -> None:
        """Clear retry state after config changes or manual retry."""
        binding = self.db.get(AgentChannelBinding, binding_id)
        if binding is None:
            return
        binding.consecutive_failure_count = 0
        binding.next_retry_at = None
        binding.last_error_fingerprint = None
        binding.updated_at = datetime.now(UTC)
        self.db.add(binding)
        self.db.commit()

    @staticmethod
    def classify_exception(exc: BaseException) -> ChannelRuntimeErrorKind:
        """Classify a provider/runtime exception into a generic health bucket."""
        text = f"{type(exc).__name__}: {exc!s}".lower()
        if isinstance(exc, ImportError | ModuleNotFoundError) or any(
            marker in text
            for marker in (
                "no module named",
                "cannot import",
                "unsupported operand type",
            )
        ):
            return "dependency"
        if any(marker in text for marker in ("missing", "required config")):
            return "configuration"
        if any(
            marker in text
            for marker in (
                "unauthorized",
                "forbidden",
                "invalid token",
                "invalid secret",
                "credential",
                "auth",
            )
        ):
            return "authentication"
        if any(
            marker in text
            for marker in (
                "timeout",
                "connection",
                "network",
                "dns",
                "temporarily unavailable",
                "reset by peer",
            )
        ):
            return "network"
        if "rate" in text and "limit" in text:
            return "rate_limit"
        return "unknown"

    @staticmethod
    def _retry_delay(failure_count: int) -> timedelta:
        seconds = min(300, 5 * (2 ** max(0, failure_count - 1)))
        return timedelta(seconds=seconds)

    @staticmethod
    def _fingerprint(
        *,
        message: str,
        error_kind: str,
        error: BaseException | None,
    ) -> str:
        raw = f"{error_kind}:{type(error).__name__ if error else ''}:{message}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    def _update_status(
        self,
        *,
        binding_id: int,
        status: ChannelRuntimeHealthStatus,
        message: str,
    ) -> None:
        binding = self.db.get(AgentChannelBinding, binding_id)
        if binding is None:
            return
        now = datetime.now(UTC)
        binding.last_health_status = status
        binding.last_health_message = message[:500]
        binding.last_health_check_at = now
        binding.updated_at = now
        self.db.add(binding)
        self.db.commit()
