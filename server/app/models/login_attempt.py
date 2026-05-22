"""Login attempt tracking for IP-based rate limiting."""

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class LoginAttempt(SQLModel, table=True):
    """Tracks failed login attempts for IP-based rate limiting.

    Attributes:
        id: Primary key.
        ip_address: Client IP address (supports IPv4 and IPv6).
        attempted_at: UTC timestamp of the failed attempt.
    """

    id: int | None = Field(default=None, primary_key=True)
    ip_address: str = Field(index=True, max_length=45)
    attempted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
