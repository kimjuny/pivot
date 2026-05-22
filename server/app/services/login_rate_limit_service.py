"""Login rate limiting service using database-backed sliding window."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from app.models.login_attempt import LoginAttempt
from sqlalchemy import func
from sqlmodel import select

if TYPE_CHECKING:
    from sqlmodel import Session as DBSession

_WINDOW_SECONDS = 60


class LoginRateLimitService:
    """IP-based login rate limiting backed by the database.

    Uses a sliding-window approach: each failed login attempt is recorded
    with its timestamp. Before accepting a new login, expired records for
    the IP are pruned and the remaining count is compared against the
    configured limit.
    """

    def __init__(self, db: DBSession) -> None:
        self.db = db

    def _prune_expired(self, ip_address: str | None = None) -> int:
        """Delete expired login attempt records.

        Args:
            ip_address: When provided, only prune records for this IP.
                Otherwise prune all expired records.

        Returns:
            Number of deleted records.
        """
        cutoff = datetime.now(UTC) - timedelta(seconds=_WINDOW_SECONDS)
        statement = select(LoginAttempt).where(LoginAttempt.attempted_at < cutoff)
        if ip_address is not None:
            statement = statement.where(LoginAttempt.ip_address == ip_address)
        expired = self.db.exec(statement).all()
        for record in expired:
            self.db.delete(record)
        if expired:
            self.db.commit()
        return len(expired)

    def is_rate_limited(self, ip_address: str, max_attempts: int) -> bool:
        """Check whether an IP has exceeded the allowed failed-login count.

        Prunes expired attempts for the IP before counting.

        Args:
            ip_address: Client IP address.
            max_attempts: Maximum allowed failed attempts within the window.

        Returns:
            True if the IP should be rejected.
        """
        self._prune_expired(ip_address)
        count = self.db.exec(
            select(func.count())
            .select_from(LoginAttempt)
            .where(LoginAttempt.ip_address == ip_address)
        ).one()
        return count >= max_attempts

    def record_failed_attempt(self, ip_address: str) -> None:
        """Record one failed login attempt.

        Args:
            ip_address: Client IP address.
        """
        self.db.add(LoginAttempt(ip_address=ip_address))
        self.db.commit()

    def cleanup_expired(self) -> int:
        """Delete all expired login attempt records across all IPs.

        Returns:
            Number of deleted records.
        """
        return self._prune_expired()
