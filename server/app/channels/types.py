"""Shared channel manifest and runtime types."""

from __future__ import annotations

from typing import Any, Literal, Protocol

from app.schemas.base import AppBaseModel
from pydantic import Field

FieldType = Literal["text", "number", "secret", "textarea", "boolean"]
TransportMode = Literal["webhook", "websocket", "polling"]
ChannelDeliveryHint = Literal["append", "replace", "stream"]
ChannelOutboundKind = Literal[
    "progress",
    "answer",
    "clarify",
    "error",
    "system",
    "link_required",
]
ChannelProgressViewMode = Literal["text", "plan"]


class ChannelConfigField(AppBaseModel):
    """Schema-driven field used by the frontend to render config forms."""

    key: str
    label: str
    type: FieldType
    required: bool = False
    placeholder: str | None = None
    description: str | None = None


class ChannelManifest(AppBaseModel):
    """Declarative metadata for one built-in or installed channel provider."""

    key: str
    name: str
    description: str
    icon: str
    docs_url: str
    transport_mode: TransportMode
    visibility: str = "builtin"
    status: str = "active"
    capabilities: list[str]
    auth_schema: list[ChannelConfigField]
    config_schema: list[ChannelConfigField]
    setup_steps: list[str]


class ChannelEndpointInfo(AppBaseModel):
    """Endpoint or link details surfaced to the UI for channel setup."""

    label: str
    method: str
    url: str
    description: str


class ChannelTestResult(AppBaseModel):
    """Health or setup validation result returned by providers."""

    ok: bool
    status: str
    message: str
    endpoint_infos: list[ChannelEndpointInfo] = Field(default_factory=list)


class ChannelInboundEvent(AppBaseModel):
    """Provider-neutral inbound text event produced by an adapter."""

    external_event_id: str | None = None
    external_message_id: str | None = None
    external_user_id: str | None = None
    external_conversation_id: str | None = None
    message_type: str | None = None
    event_type: str | None = None
    text: str | None = None
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    raw_payload: dict[str, Any] | None = None


class ChannelMessageContext(AppBaseModel):
    """Provider-neutral metadata used when delivering outbound actions."""

    conversation_id: str | None = None
    user_id: str | None = None
    external_event_id: str | None = None
    external_message_id: str | None = None
    message_type: str | None = None
    event_type: str | None = None
    provider_state: dict[str, Any] = Field(default_factory=dict)


class ChannelPlanStepProgressView(AppBaseModel):
    """One logical plan step shown in a channel progress projection."""

    step_id: str
    general_goal: str
    status: str
    summaries: list[str] = Field(default_factory=list)


class ChannelProgressView(AppBaseModel):
    """Structured progress view shared by webhooks, sockets, and polling."""

    mode: ChannelProgressViewMode
    summary: str | None = None
    steps: list[ChannelPlanStepProgressView] = Field(default_factory=list)


class ChannelOutboundAction(AppBaseModel):
    """Standardized outbound action emitted by channel orchestration."""

    kind: ChannelOutboundKind
    text: str
    delivery_hint: ChannelDeliveryHint = "append"
    slot: str = "primary"
    is_terminal: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    progress_view: ChannelProgressView | None = None


class ChannelWebhookResult(AppBaseModel):
    """Unified result from webhook processing before runtime dispatch."""

    status_code: int = 200
    content_type: str = "text/plain"
    body_text: str | None = "success"
    body_json: dict[str, Any] | None = None
    inbound_event: ChannelInboundEvent | None = None


class ChannelProvider(Protocol):
    """Runtime contract implemented by each channel adapter."""

    manifest: ChannelManifest

    def validate_config(
        self,
        auth_config: dict[str, Any],
        runtime_config: dict[str, Any],
    ) -> None:
        """Validate one binding's credentials and config."""

    def build_endpoint_infos(self, binding_id: int) -> list[ChannelEndpointInfo]:
        """Build setup endpoint metadata for the configured binding."""
        ...

    def test_connection(
        self,
        auth_config: dict[str, Any],
        runtime_config: dict[str, Any],
        binding_id: int,
    ) -> ChannelTestResult:
        """Execute a setup or connectivity validation for a binding."""
        ...

    def handle_webhook(
        self,
        auth_config: dict[str, Any],
        runtime_config: dict[str, Any],
        *,
        method: str,
        query_params: dict[str, str],
        headers: dict[str, str],
        body: bytes,
    ) -> ChannelWebhookResult:
        """Process one webhook request into a provider-neutral event."""
        ...

    def send_text(
        self,
        auth_config: dict[str, Any],
        runtime_config: dict[str, Any],
        *,
        conversation_id: str,
        user_id: str | None,
        text: str,
    ) -> None:
        """Send a plain-text message through the provider."""
        ...

    def send_action(
        self,
        auth_config: dict[str, Any],
        runtime_config: dict[str, Any],
        *,
        context: ChannelMessageContext,
        action: ChannelOutboundAction,
    ) -> None:
        """Deliver one standardized outbound action through the provider."""
        ...
