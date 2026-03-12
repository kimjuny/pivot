"""Database models for channel bindings, identities, and sessions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlmodel import Field, SQLModel


class AgentChannelBinding(SQLModel, table=True):
    """One configured channel instance attached to a specific agent.

    Attributes:
        id: Primary key of the binding.
        agent_id: Agent that owns this configured binding.
        channel_key: Stable provider identifier, such as ``work_wechat``.
        name: User-facing alias for this binding.
        enabled: Whether the binding is active for inbound/outbound traffic.
        auth_config: JSON-encoded auth payload. Stored as text for V1.
        runtime_config: JSON-encoded non-secret configuration payload.
        last_health_status: Latest health check outcome.
        last_health_message: Human-readable health details.
        last_health_check_at: UTC timestamp of the most recent health check.
        created_at: UTC timestamp when the binding was created.
        updated_at: UTC timestamp when the binding was last updated.
    """

    id: int | None = Field(default=None, primary_key=True)
    agent_id: int = Field(foreign_key="agent.id", index=True)
    channel_key: str = Field(index=True, max_length=100)
    name: str = Field(index=True, max_length=120)
    enabled: bool = Field(default=True)
    auth_config: str = Field(default="{}")
    runtime_config: str = Field(default="{}")
    last_health_status: str | None = Field(default=None, max_length=32)
    last_health_message: str | None = Field(default=None, max_length=500)
    last_health_check_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ExternalIdentityBinding(SQLModel, table=True):
    """Maps one external channel identity to one Pivot user.

    Attributes:
        id: Primary key of the identity mapping.
        channel_binding_id: Channel binding where this identity was observed.
        provider_key: Provider identifier matching the binding's ``channel_key``.
        external_user_id: Provider-side sender/user identifier.
        external_conversation_id: Provider-side chat/thread identifier.
        pivot_user_id: Authenticated Pivot user bound to this external identity.
        workspace_owner: Current V1 workspace key, aligned with Pivot username.
        status: Current mapping state, usually ``linked``.
        auth_method: Binding method, such as ``link_page``.
        created_at: UTC timestamp when the mapping was created.
        updated_at: UTC timestamp when the mapping was last updated.
        last_seen_at: UTC timestamp of the most recent inbound event.
    """

    id: int | None = Field(default=None, primary_key=True)
    channel_binding_id: int = Field(foreign_key="agentchannelbinding.id", index=True)
    provider_key: str = Field(index=True, max_length=100)
    external_user_id: str = Field(index=True, max_length=255)
    external_conversation_id: str | None = Field(default=None, max_length=255)
    pivot_user_id: int = Field(foreign_key="user.id", index=True)
    workspace_owner: str = Field(max_length=120)
    status: str = Field(default="linked", max_length=32)
    auth_method: str = Field(default="link_page", max_length=64)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_seen_at: datetime | None = Field(default=None)


class ChannelLinkToken(SQLModel, table=True):
    """Short-lived token used to bind an external identity to a Pivot user."""

    id: int | None = Field(default=None, primary_key=True)
    token: str = Field(index=True, unique=True, max_length=255)
    channel_binding_id: int = Field(foreign_key="agentchannelbinding.id", index=True)
    provider_key: str = Field(index=True, max_length=100)
    external_user_id: str = Field(index=True, max_length=255)
    external_conversation_id: str | None = Field(default=None, max_length=255)
    expires_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC) + timedelta(minutes=30)
    )
    used_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ChannelSession(SQLModel, table=True):
    """Maps one external conversation to one Pivot session.

    Attributes:
        id: Primary key of the mapping row.
        channel_binding_id: Channel binding that owns the external thread.
        external_conversation_id: Provider-side chat/thread identifier.
        external_user_id: Provider-side sender identifier.
        pivot_user_id: Bound Pivot user id.
        pivot_session_id: Session identifier from the existing Pivot session table.
        active_context: Freeform context marker for future project/workspace routing.
        last_cursor: Provider cursor or offset for polling/websocket flows.
        last_event_id: Most recent processed provider event id.
        created_at: UTC timestamp when the mapping was created.
        updated_at: UTC timestamp when the mapping was last updated.
    """

    id: int | None = Field(default=None, primary_key=True)
    channel_binding_id: int = Field(foreign_key="agentchannelbinding.id", index=True)
    external_conversation_id: str = Field(index=True, max_length=255)
    external_user_id: str | None = Field(default=None, max_length=255)
    pivot_user_id: int = Field(foreign_key="user.id", index=True)
    pivot_session_id: str = Field(index=True, max_length=255)
    active_context: str | None = Field(default=None, max_length=255)
    last_cursor: str | None = Field(default=None, max_length=255)
    last_event_id: str | None = Field(default=None, max_length=255)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ChannelEventLog(SQLModel, table=True):
    """Inbound/outbound event log for idempotency and debugging.

    Attributes:
        id: Primary key of the log entry.
        channel_binding_id: Binding that received or sent the event.
        external_event_id: Provider-side event identifier when available.
        direction: ``inbound`` or ``outbound``.
        status: Processing status, such as ``received``, ``processed``, or ``failed``.
        payload_json: Raw event or action payload serialized as JSON.
        error_message: Failure detail when processing or delivery fails.
        created_at: UTC timestamp when the log row was created.
        updated_at: UTC timestamp when the log row was last updated.
    """

    id: int | None = Field(default=None, primary_key=True)
    channel_binding_id: int = Field(foreign_key="agentchannelbinding.id", index=True)
    external_event_id: str | None = Field(default=None, index=True, max_length=255)
    direction: str = Field(max_length=16)
    status: str = Field(max_length=32)
    payload_json: str = Field(default="{}")
    error_message: str | None = Field(default=None, max_length=1000)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
