"""Services for channel bindings, external identity linking, and message routing."""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime
from time import perf_counter
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from app.channels.providers import TelegramProvider
from app.channels.work_wechat_socket import (
    decrypt_work_wechat_media,
    download_work_wechat_media,
    infer_work_wechat_filename,
)
from app.config import get_settings
from app.models.agent import Agent
from app.models.channel import (
    AgentChannelBinding,
    ChannelEventLog,
    ChannelLinkToken,
    ChannelSession,
    ExternalIdentityBinding,
)
from app.models.react import ReactRecursion, ReactTask
from app.models.user import User
from app.schemas.channel import (
    ChannelBindingResponse,
    ChannelLinkCompletionResponse,
    ChannelLinkTokenResponse,
    ChannelLinkTokenStatusResponse,
)
from app.services.agent_release_runtime_service import AgentReleaseRuntimeService
from app.services.extension_service import ExtensionService
from app.services.file_service import FileService
from app.services.provider_registry_service import ProviderRegistryService
from app.services.react_task_supervisor import (
    ReactTaskLaunchRequest,
    get_react_task_supervisor,
)
from app.services.session_service import SessionService
from fastapi.concurrency import run_in_threadpool
from sqlmodel import Session, col, desc, select

if TYPE_CHECKING:
    from app.channels.types import (
        ChannelInboundEvent,
        ChannelMessageContext,
        ChannelOutboundAction,
        ChannelProgressView,
        ChannelProvider,
    )
    from app.orchestration.tool.manager import ToolManager


def _load_json_object(raw_value: str | None) -> dict[str, Any]:
    """Parse a JSON object stored in a text column.

    Args:
        raw_value: Stored JSON text or ``None``.

    Returns:
        Parsed object, or an empty dict if the stored value is blank or invalid.
    """
    if not raw_value:
        return {}
    try:
        parsed = json.loads(raw_value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _dump_json_object(payload: dict[str, Any]) -> str:
    """Serialize a JSON object consistently for text storage."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _ensure_utc(value: datetime) -> datetime:
    """Normalize a possibly naive datetime to explicit UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class ChannelService:
    """Application service for channel catalog, bindings, and routing."""

    def __init__(self, db: Session) -> None:
        """Store the active database session for channel operations."""
        self.db = db

    def _list_channel_providers(self) -> list[ChannelProvider]:
        """Return built-in and extension-backed channel providers."""
        return ProviderRegistryService(self.db).list_channel_providers()

    def _get_channel_provider(self, channel_key: str) -> ChannelProvider:
        """Resolve one channel provider from the unified provider registry."""
        return ProviderRegistryService(self.db).get_channel_provider(channel_key)

    def _is_provider_available_to_agent(
        self,
        *,
        agent_id: int,
        provider: ChannelProvider,
        enabled_only: bool = True,
    ) -> bool:
        """Return whether one channel provider is available to an agent."""
        extension_package_id = provider.manifest.extension_name
        if not extension_package_id:
            return True
        return ExtensionService(self.db).is_agent_extension_package_bound(
            agent_id=agent_id,
            package_id=extension_package_id,
            enabled_only=enabled_only,
        )

    def is_provider_usable_by_user(
        self,
        *,
        user: User | None,
        provider: ChannelProvider,
    ) -> bool:
        """Return whether one provider is selectable by the current Studio user."""
        extension_package_id = provider.manifest.extension_name
        if not extension_package_id or user is None:
            return True
        return ExtensionService(self.db).is_package_usable_by_user(
            user=user,
            package_id=extension_package_id,
        )

    def list_catalog(
        self,
        agent_id: int | None = None,
        user: User | None = None,
    ) -> list[dict[str, Any]]:
        """Return installed channel providers visible to the current agent."""
        providers = self._list_channel_providers()
        providers = [
            provider
            for provider in providers
            if self.is_provider_usable_by_user(user=user, provider=provider)
        ]
        if agent_id is not None:
            providers = [
                provider
                for provider in providers
                if self._is_provider_available_to_agent(
                    agent_id=agent_id,
                    provider=provider,
                    enabled_only=True,
                )
            ]
        return [{"manifest": provider.manifest.model_dump()} for provider in providers]

    def _serialize_binding(
        self, binding: AgentChannelBinding
    ) -> ChannelBindingResponse:
        """Render one binding with manifest metadata and generated endpoints."""
        provider = self._get_channel_provider(binding.channel_key)
        effective_available, disabled_reason = ExtensionService(
            self.db
        ).get_agent_child_availability(
            agent_id=binding.agent_id,
            package_id=provider.manifest.extension_name,
        )
        auth_config = _load_json_object(binding.auth_config)
        return ChannelBindingResponse(
            id=binding.id or 0,
            agent_id=binding.agent_id,
            channel_key=binding.channel_key,
            name=binding.name,
            enabled=binding.enabled,
            effective_enabled=binding.enabled and effective_available,
            disabled_reason=disabled_reason,
            auth_config={key: str(value) for key, value in auth_config.items()},
            runtime_config=_load_json_object(binding.runtime_config),
            manifest=provider.manifest.model_dump(),
            endpoint_infos=[
                item.model_dump()
                for item in provider.build_endpoint_infos(binding.id or 0)
            ],
            last_health_status=binding.last_health_status,
            last_health_message=binding.last_health_message,
            last_health_check_at=(
                binding.last_health_check_at.replace(tzinfo=UTC).isoformat()
                if binding.last_health_check_at is not None
                else None
            ),
            created_at=binding.created_at.replace(tzinfo=UTC).isoformat(),
            updated_at=binding.updated_at.replace(tzinfo=UTC).isoformat(),
        )

    def list_agent_bindings(self, agent_id: int) -> list[ChannelBindingResponse]:
        """List all channel bindings attached to one agent."""
        statement = (
            select(AgentChannelBinding)
            .where(AgentChannelBinding.agent_id == agent_id)
            .order_by(col(AgentChannelBinding.created_at))
        )
        rows = self.db.exec(statement).all()
        return [self._serialize_binding(row) for row in rows]

    def create_binding(
        self,
        *,
        agent_id: int,
        channel_key: str,
        name: str,
        enabled: bool,
        auth_config: dict[str, Any],
        runtime_config: dict[str, Any],
        user: User | None = None,
    ) -> ChannelBindingResponse:
        """Create a new agent channel binding after provider validation."""
        provider = self._get_channel_provider(channel_key)
        if not self.is_provider_usable_by_user(user=user, provider=provider):
            raise ValueError("Channel provider is not available to the caller.")
        if not self._is_provider_available_to_agent(
            agent_id=agent_id,
            provider=provider,
            enabled_only=False,
        ):
            raise ValueError(
                "Install and enable the owning extension on this agent before creating this channel."
            )
        provider.validate_config(auth_config, runtime_config)
        binding = AgentChannelBinding(
            agent_id=agent_id,
            channel_key=channel_key,
            name=name,
            enabled=enabled,
            auth_config=_dump_json_object(auth_config),
            runtime_config=_dump_json_object(runtime_config),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.db.add(binding)
        self.db.commit()
        self.db.refresh(binding)
        return self._serialize_binding(binding)

    def update_binding(
        self,
        binding_id: int,
        *,
        name: str | None = None,
        enabled: bool | None = None,
        auth_config: dict[str, Any] | None = None,
        runtime_config: dict[str, Any] | None = None,
    ) -> ChannelBindingResponse:
        """Update one agent channel binding."""
        binding = self.db.get(AgentChannelBinding, binding_id)
        if binding is None:
            raise ValueError("Channel binding not found.")

        provider = self._get_channel_provider(binding.channel_key)
        next_auth = (
            auth_config
            if auth_config is not None
            else _load_json_object(binding.auth_config)
        )
        next_runtime = (
            runtime_config
            if runtime_config is not None
            else _load_json_object(binding.runtime_config)
        )
        provider.validate_config(next_auth, next_runtime)

        if name is not None:
            binding.name = name
        if enabled is not None:
            binding.enabled = enabled
        if auth_config is not None:
            binding.auth_config = _dump_json_object(auth_config)
        if runtime_config is not None:
            binding.runtime_config = _dump_json_object(runtime_config)
        binding.updated_at = datetime.now(UTC)
        self.db.add(binding)
        self.db.commit()
        self.db.refresh(binding)
        return self._serialize_binding(binding)

    def delete_binding(self, binding_id: int) -> None:
        """Delete one binding and its related short-lived link tokens."""
        binding = self.db.get(AgentChannelBinding, binding_id)
        if binding is None:
            raise ValueError("Channel binding not found.")

        token_rows = self.db.exec(
            select(ChannelLinkToken).where(
                ChannelLinkToken.channel_binding_id == binding_id
            )
        ).all()
        for token_row in token_rows:
            self.db.delete(token_row)

        identity_rows = self.db.exec(
            select(ExternalIdentityBinding).where(
                ExternalIdentityBinding.channel_binding_id == binding_id
            )
        ).all()
        for identity_row in identity_rows:
            self.db.delete(identity_row)

        session_rows = self.db.exec(
            select(ChannelSession).where(
                ChannelSession.channel_binding_id == binding_id
            )
        ).all()
        for session_row in session_rows:
            self.db.delete(session_row)

        self.db.delete(binding)
        self.db.commit()

    def test_binding(self, binding_id: int) -> dict[str, Any]:
        """Run the provider-specific health check for one binding."""
        binding = self.db.get(AgentChannelBinding, binding_id)
        if binding is None:
            raise ValueError("Channel binding not found.")
        provider = self._get_channel_provider(binding.channel_key)
        result = provider.test_connection(
            _load_json_object(binding.auth_config),
            _load_json_object(binding.runtime_config),
            binding_id,
        )
        binding.last_health_status = result.status
        binding.last_health_message = result.message
        binding.last_health_check_at = datetime.now(UTC)
        binding.updated_at = datetime.now(UTC)
        self.db.add(binding)
        self.db.commit()
        return {"result": result.model_dump()}

    def test_binding_draft(
        self,
        *,
        channel_key: str,
        auth_config: dict[str, Any],
        runtime_config: dict[str, Any],
        user: User | None = None,
    ) -> dict[str, Any]:
        """Run a provider health check against unsaved form values.

        Why: setup should let users validate credentials before persisting a
        new binding row, otherwise failed experiments leave behind junk rows.
        """
        provider = self._get_channel_provider(channel_key)
        if not self.is_provider_usable_by_user(user=user, provider=provider):
            raise ValueError("Channel provider is not available to the caller.")
        provider.validate_config(auth_config, runtime_config)
        result = provider.test_connection(
            auth_config,
            runtime_config,
            0,
        )
        return {"result": result.model_dump()}

    def get_link_token_status(self, token: str) -> ChannelLinkTokenStatusResponse:
        """Return public metadata for one external identity link token."""
        row = self.db.exec(
            select(ChannelLinkToken).where(ChannelLinkToken.token == token)
        ).first()
        if row is None:
            raise ValueError("Channel link token not found.")

        binding = self.db.get(AgentChannelBinding, row.channel_binding_id)
        if binding is None:
            raise ValueError("Channel binding not found.")
        provider = self._get_channel_provider(row.provider_key)
        status = "used" if row.used_at is not None else "pending"
        if _ensure_utc(row.expires_at) < datetime.now(UTC):
            status = "expired"
        return ChannelLinkTokenStatusResponse(
            token=row.token,
            status=status,
            provider_name=provider.manifest.name,
            binding_name=binding.name,
            agent_id=binding.agent_id,
            external_user_id=row.external_user_id,
            external_conversation_id=row.external_conversation_id,
            expires_at=_ensure_utc(row.expires_at).isoformat(),
            used_at=(
                row.used_at.replace(tzinfo=UTC).isoformat()
                if row.used_at is not None
                else None
            ),
        )

    def complete_link_token(
        self,
        token: str,
        current_user: User,
    ) -> ChannelLinkCompletionResponse:
        """Bind an external identity token to the authenticated Pivot user."""
        row = self.db.exec(
            select(ChannelLinkToken).where(ChannelLinkToken.token == token)
        ).first()
        if row is None:
            raise ValueError("Channel link token not found.")
        if row.used_at is not None:
            raise ValueError("Channel link token was already used.")
        if _ensure_utc(row.expires_at) < datetime.now(UTC):
            raise ValueError("Channel link token has expired.")
        if current_user.id is None:
            raise ValueError("Current user id is missing.")

        existing = self.db.exec(
            select(ExternalIdentityBinding).where(
                ExternalIdentityBinding.channel_binding_id == row.channel_binding_id,
                ExternalIdentityBinding.external_user_id == row.external_user_id,
            )
        ).first()
        now = datetime.now(UTC)
        if existing is None:
            identity = ExternalIdentityBinding(
                channel_binding_id=row.channel_binding_id,
                provider_key=row.provider_key,
                external_user_id=row.external_user_id,
                external_conversation_id=row.external_conversation_id,
                pivot_user_id=current_user.id,
                workspace_owner=current_user.username,
                status="linked",
                auth_method="link_page",
                created_at=now,
                updated_at=now,
                last_seen_at=now,
            )
            self.db.add(identity)
        else:
            existing.pivot_user_id = current_user.id
            existing.workspace_owner = current_user.username
            existing.status = "linked"
            existing.auth_method = "link_page"
            existing.updated_at = now
            existing.last_seen_at = now
            self.db.add(existing)

        row.used_at = now
        self.db.add(row)
        self.db.commit()
        return ChannelLinkCompletionResponse(
            status="linked",
            message="External account linked successfully.",
            pivot_user_id=current_user.id,
            workspace_owner=current_user.username,
            linked_at=now.replace(tzinfo=UTC).isoformat(),
        )

    def create_link_token(
        self,
        *,
        binding: AgentChannelBinding,
        provider_key: str,
        external_user_id: str,
        external_conversation_id: str | None,
    ) -> ChannelLinkTokenResponse:
        """Create or reuse a short-lived external identity link token."""
        candidates = self.db.exec(
            select(ChannelLinkToken).where(
                ChannelLinkToken.channel_binding_id == (binding.id or 0),
                ChannelLinkToken.external_user_id == external_user_id,
            )
        ).all()
        existing = next((item for item in candidates if item.used_at is None), None)
        now = datetime.now(UTC)
        if existing is not None and _ensure_utc(existing.expires_at) > now:
            token_row = existing
        else:
            token_row = ChannelLinkToken(
                token=secrets.token_urlsafe(24),
                channel_binding_id=binding.id or 0,
                provider_key=provider_key,
                external_user_id=external_user_id,
                external_conversation_id=external_conversation_id,
                created_at=now,
            )
            self.db.add(token_row)
            self.db.commit()
            self.db.refresh(token_row)

        link_url = (
            f"{get_settings().web_public_base_url}/channel-link/{token_row.token}"
        )
        return ChannelLinkTokenResponse(
            token=token_row.token,
            link_url=link_url,
            expires_at=_ensure_utc(token_row.expires_at).isoformat(),
        )

    def get_event_log(
        self,
        *,
        channel_binding_id: int,
        external_event_id: str,
        direction: str,
    ) -> ChannelEventLog | None:
        """Look up an existing log row for deduplication."""
        return self.db.exec(
            select(ChannelEventLog).where(
                ChannelEventLog.channel_binding_id == channel_binding_id,
                ChannelEventLog.external_event_id == external_event_id,
                ChannelEventLog.direction == direction,
            )
        ).first()

    def build_message_context(
        self,
        *,
        event: ChannelInboundEvent,
    ) -> ChannelMessageContext:
        """Build the provider-neutral outbound delivery context for an event."""
        from app.channels.types import ChannelMessageContext

        raw_payload = event.raw_payload if isinstance(event.raw_payload, dict) else {}
        provider_state: dict[str, Any] = {}
        headers = raw_payload.get("headers")
        if isinstance(headers, dict):
            provider_state["headers"] = headers
        command = raw_payload.get("cmd")
        if command is not None:
            provider_state["cmd"] = str(command)

        return ChannelMessageContext(
            conversation_id=event.external_conversation_id,
            user_id=event.external_user_id,
            external_event_id=event.external_event_id,
            external_message_id=event.external_message_id,
            message_type=event.message_type,
            event_type=event.event_type,
            provider_state=provider_state,
        )

    def create_event_log(
        self,
        *,
        channel_binding_id: int,
        external_event_id: str | None,
        direction: str,
        status: str,
        payload: dict[str, Any],
        error_message: str | None = None,
    ) -> ChannelEventLog:
        """Persist an event log row for idempotency and diagnostics."""
        now = datetime.now(UTC)
        row = ChannelEventLog(
            channel_binding_id=channel_binding_id,
            external_event_id=external_event_id,
            direction=direction,
            status=status,
            payload_json=json.dumps(payload, ensure_ascii=False),
            error_message=error_message,
            created_at=now,
            updated_at=now,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def update_event_log(
        self,
        row: ChannelEventLog,
        *,
        status: str,
        error_message: str | None = None,
    ) -> ChannelEventLog:
        """Update the status of an existing event log row."""
        row.status = status
        row.error_message = error_message
        row.updated_at = datetime.now(UTC)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def _get_identity_binding(
        self,
        *,
        channel_binding_id: int,
        external_user_id: str,
    ) -> ExternalIdentityBinding | None:
        """Resolve one external identity mapping for a binding/user pair."""
        return self.db.exec(
            select(ExternalIdentityBinding).where(
                ExternalIdentityBinding.channel_binding_id == channel_binding_id,
                ExternalIdentityBinding.external_user_id == external_user_id,
            )
        ).first()

    def _get_or_create_channel_session(
        self,
        *,
        binding: AgentChannelBinding,
        identity: ExternalIdentityBinding,
        external_conversation_id: str,
    ) -> ChannelSession:
        """Resolve the backing Pivot session for one external conversation."""
        session_service = SessionService(self.db)
        now = datetime.now(UTC)
        existing = self.db.exec(
            select(ChannelSession).where(
                ChannelSession.channel_binding_id == (binding.id or 0),
                ChannelSession.external_conversation_id == external_conversation_id,
            )
        ).first()
        if existing is not None:
            user = self.db.get(User, identity.pivot_user_id)
            if user is None:
                raise ValueError("Linked Pivot user not found.")

            pivot_session = session_service.get_session(existing.pivot_session_id)
            if (
                pivot_session is None
                or session_service.has_session_exceeded_idle_timeout(
                    pivot_session,
                    now=now,
                )
            ):
                fresh_session = session_service.create_session(
                    agent_id=binding.agent_id,
                    user=user.username,
                )
                existing.pivot_session_id = fresh_session.session_id

            existing.external_user_id = identity.external_user_id
            existing.pivot_user_id = identity.pivot_user_id
            existing.updated_at = now
            self.db.add(existing)
            self.db.commit()
            self.db.refresh(existing)
            return existing

        user = self.db.get(User, identity.pivot_user_id)
        if user is None:
            raise ValueError("Linked Pivot user not found.")

        session_row = session_service.create_session(
            agent_id=binding.agent_id,
            user=user.username,
        )
        channel_session = ChannelSession(
            channel_binding_id=binding.id or 0,
            external_conversation_id=external_conversation_id,
            external_user_id=identity.external_user_id,
            pivot_user_id=identity.pivot_user_id,
            pivot_session_id=session_row.session_id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.db.add(channel_session)
        self.db.commit()
        self.db.refresh(channel_session)
        return channel_session

    async def stream_inbound_actions(
        self,
        *,
        binding: AgentChannelBinding,
        event: ChannelInboundEvent,
    ) -> AsyncIterator[ChannelOutboundAction]:
        """Route one inbound event into standardized outbound actions."""
        from app.channels.types import ChannelOutboundAction

        if not event.external_user_id:
            return

        identity = self._get_identity_binding(
            channel_binding_id=binding.id or 0,
            external_user_id=event.external_user_id,
        )
        if identity is None:
            link = self.create_link_token(
                binding=binding,
                provider_key=binding.channel_key,
                external_user_id=event.external_user_id,
                external_conversation_id=event.external_conversation_id,
            )
            yield ChannelOutboundAction(
                kind="link_required",
                text=(
                    "Link your Pivot account before chatting with this agent:\n"
                    f"{link.link_url}\n"
                    "After linking, send your message again."
                ),
                delivery_hint="append",
                slot="linking",
                is_terminal=True,
            )
            return

        identity.last_seen_at = datetime.now(UTC)
        identity.updated_at = datetime.now(UTC)
        self.db.add(identity)
        self.db.commit()

        if not event.external_conversation_id:
            yield ChannelOutboundAction(
                kind="error",
                text=(
                    "Received the message, but the channel did not provide "
                    "a conversation id."
                ),
                delivery_hint="append",
                slot="primary",
                is_terminal=True,
            )
            return

        if not event.text and not event.attachments:
            if event.event_type == "enter_chat":
                yield ChannelOutboundAction(
                    kind="system",
                    text=(
                        "Your Pivot account is linked. Send a text message here and "
                        "I will continue in this channel."
                    ),
                    delivery_hint="append",
                    slot="system",
                    is_terminal=True,
                )
            return

        try:
            channel_session = self._get_or_create_channel_session(
                binding=binding,
                identity=identity,
                external_conversation_id=event.external_conversation_id,
            )
        except ValueError as exc:
            yield ChannelOutboundAction(
                kind="error",
                text=str(exc),
                delivery_hint="append",
                slot="primary",
                is_terminal=True,
            )
            return
        yield ChannelOutboundAction(
            kind="progress",
            text="Received, starting the task...",
            delivery_hint="stream",
            slot="assistant_turn",
        )
        channel_file_ids: list[str] = []
        if event.attachments:
            linked_user = self.db.get(User, identity.pivot_user_id)
            channel_file_ids = await self._prepare_channel_attachments(
                username=(
                    linked_user.username
                    if linked_user is not None
                    else identity.workspace_owner
                ),
                external_event=event,
            )
        async for action in self._run_agent_turn(
            agent_id=binding.agent_id,
            pivot_user_id=identity.pivot_user_id,
            session_id=channel_session.pivot_session_id,
            message=event.text or self._default_attachment_message(event),
            channel_file_ids=channel_file_ids,
        ):
            yield action

    async def collect_outbound_actions(
        self,
        *,
        binding: AgentChannelBinding,
        event: ChannelInboundEvent,
    ) -> list[ChannelOutboundAction]:
        """Collect all streamed outbound actions into a list."""
        actions: list[ChannelOutboundAction] = []
        async for action in self.stream_inbound_actions(binding=binding, event=event):
            actions.append(action)
        return actions

    async def route_inbound_event(
        self,
        *,
        binding: AgentChannelBinding,
        event: ChannelInboundEvent,
    ) -> str | None:
        """Return the final visible text for compatibility call sites."""
        actions = await self.collect_outbound_actions(binding=binding, event=event)
        for action in reversed(actions):
            if action.text.strip():
                return action.text
        return None

    async def _run_agent_turn(
        self,
        *,
        agent_id: int,
        pivot_user_id: int,
        session_id: str,
        message: str,
        channel_file_ids: list[str] | None = None,
    ) -> AsyncIterator[ChannelOutboundAction]:
        """Run one ReAct turn and stream standardized outbound actions."""
        from app.channels.types import ChannelOutboundAction

        agent = self.db.get(Agent, agent_id)
        if agent is None:
            yield ChannelOutboundAction(
                kind="error",
                text="The target agent could not be found.",
                delivery_hint="append",
                is_terminal=True,
            )
            return

        user = self.db.get(User, pivot_user_id)
        if user is None:
            yield ChannelOutboundAction(
                kind="error",
                text="The linked Pivot user could not be found.",
                delivery_hint="append",
                is_terminal=True,
            )
            return

        try:
            runtime_config = AgentReleaseRuntimeService(self.db).resolve_for_session(
                session_id
            )
        except ValueError as exc:
            yield ChannelOutboundAction(
                kind="error",
                text=str(exc),
                delivery_hint="append",
                is_terminal=True,
            )
            return

        if runtime_config.llm_id is None:
            yield ChannelOutboundAction(
                kind="error",
                text=f"Agent {runtime_config.agent_name} has no LLM configured yet.",
                delivery_hint="append",
                is_terminal=True,
            )
            return

        supervisor = get_react_task_supervisor()
        resumable_task = self._find_resumable_task(session_id=session_id)
        try:
            launch_result = await supervisor.start_task(
                ReactTaskLaunchRequest(
                    agent_id=agent_id,
                    message=message,
                    username=user.username,
                    session_id=session_id,
                    file_ids=channel_file_ids or [],
                    task_id=resumable_task.task_id if resumable_task else None,
                )
            )
        except ValueError as exc:
            yield ChannelOutboundAction(
                kind="error",
                text=str(exc),
                delivery_hint="append",
                is_terminal=True,
            )
            return

        answer_emitted = False
        last_progress_text = ""
        last_progress_sent_at = 0.0
        pending_progress_text: str | None = None
        pending_progress_view: ChannelProgressView | None = None
        progress_interval_seconds = max(
            get_settings().CHANNEL_PROGRESS_MIN_INTERVAL_SECONDS,
            0.0,
        )

        async def iter_task_events() -> AsyncIterator[dict[str, Any]]:
            for payload in supervisor.list_events(
                session_id=session_id,
                after_id=launch_result.cursor_before_start,
                task_id=launch_result.task_id,
            ):
                yield payload

            subscriber = await supervisor.subscribe(
                session_id=session_id,
                task_id=launch_result.task_id,
            )
            try:
                while True:
                    payload = await subscriber.queue.get()
                    yield payload
                    event_type = payload.get("type")
                    if event_type in {"clarify", "error", "task_complete"}:
                        break
            finally:
                await supervisor.unsubscribe(
                    session_id=session_id,
                    subscriber=subscriber,
                )

        async for event_data in iter_task_events():
            event_type = event_data.get("type")
            if event_type == "summary":
                summary_data = event_data.get("data")
                current_plan = (
                    summary_data.get("current_plan", [])
                    if isinstance(summary_data, dict)
                    else []
                )
                progress_view = self._build_channel_progress_view(
                    current_plan=current_plan,
                    fallback_summary=str(event_data.get("delta") or "").strip(),
                )
                progress_text = (
                    self._render_channel_progress_view(progress_view=progress_view)
                    if progress_view is not None
                    else ""
                )
                if not progress_text or progress_text == last_progress_text:
                    continue
                now = perf_counter()
                if now - last_progress_sent_at >= progress_interval_seconds:
                    yield ChannelOutboundAction(
                        kind="progress",
                        text=progress_text,
                        delivery_hint="stream",
                        slot="assistant_turn",
                        metadata=self._build_action_metadata(event_data),
                        progress_view=progress_view,
                    )
                    last_progress_text = progress_text
                    last_progress_sent_at = now
                    pending_progress_text = None
                    pending_progress_view = None
                else:
                    pending_progress_text = progress_text
                    pending_progress_view = progress_view
                continue

            if pending_progress_text and pending_progress_text != last_progress_text:
                yield ChannelOutboundAction(
                    kind="progress",
                    text=pending_progress_text,
                    delivery_hint="stream",
                    slot="assistant_turn",
                    metadata=self._build_action_metadata(event_data),
                    progress_view=pending_progress_view,
                )
                last_progress_text = pending_progress_text
                last_progress_sent_at = perf_counter()
                pending_progress_text = None
                pending_progress_view = None

            if event_type == "compact_start":
                compact_text = (
                    "Compacting context to preserve continuity. Please wait..."
                )
                if compact_text != last_progress_text:
                    yield ChannelOutboundAction(
                        kind="progress",
                        text=compact_text,
                        delivery_hint="stream",
                        slot="assistant_turn",
                        metadata=self._build_action_metadata(event_data),
                    )
                    last_progress_text = compact_text
                    last_progress_sent_at = perf_counter()
            elif event_type == "compact_complete":
                compact_text = (
                    "Context compacted. Continuing with a smaller prompt window."
                )
                if compact_text != last_progress_text:
                    yield ChannelOutboundAction(
                        kind="progress",
                        text=compact_text,
                        delivery_hint="stream",
                        slot="assistant_turn",
                        metadata=self._build_action_metadata(event_data),
                    )
                    last_progress_text = compact_text
                    last_progress_sent_at = perf_counter()
            elif event_type == "compact_failed":
                compact_text = (
                    "Context compaction failed. Continuing without compaction."
                )
                if compact_text != last_progress_text:
                    yield ChannelOutboundAction(
                        kind="progress",
                        text=compact_text,
                        delivery_hint="stream",
                        slot="assistant_turn",
                        metadata=self._build_action_metadata(event_data),
                    )
                    last_progress_text = compact_text
                    last_progress_sent_at = perf_counter()
            elif event_type == "answer":
                answer_emitted = True
                yield ChannelOutboundAction(
                    kind="answer",
                    text=self._extract_terminal_text(
                        event_data=event_data,
                        preferred_keys=("answer",),
                    ),
                    delivery_hint="stream",
                    slot="assistant_turn",
                    is_terminal=True,
                    metadata=self._build_action_metadata(event_data),
                )
            elif event_type == "clarify":
                answer_emitted = True
                yield ChannelOutboundAction(
                    kind="clarify",
                    text=self._extract_terminal_text(
                        event_data=event_data,
                        preferred_keys=("question", "message"),
                    ),
                    delivery_hint="stream",
                    slot="assistant_turn",
                    is_terminal=True,
                    metadata=self._build_action_metadata(event_data),
                )
            elif event_type == "error":
                answer_emitted = True
                yield ChannelOutboundAction(
                    kind="error",
                    text=self._extract_terminal_text(
                        event_data=event_data,
                        preferred_keys=("error", "message"),
                    ),
                    delivery_hint="stream",
                    slot="assistant_turn",
                    is_terminal=True,
                    metadata=self._build_action_metadata(event_data),
                )
            elif event_type == "task_complete":
                break

        if pending_progress_text and pending_progress_text != last_progress_text:
            yield ChannelOutboundAction(
                kind="progress",
                text=pending_progress_text,
                delivery_hint="stream",
                slot="assistant_turn",
                progress_view=pending_progress_view,
            )

        if not answer_emitted:
            yield ChannelOutboundAction(
                kind="error",
                text="The agent did not return a visible reply.",
                delivery_hint="stream",
                slot="assistant_turn",
                is_terminal=True,
            )

    async def _prepare_channel_attachments(
        self,
        *,
        username: str,
        external_event: ChannelInboundEvent,
    ) -> list[str]:
        """Download, decrypt, and persist channel media attachments."""
        if not external_event.attachments:
            return []

        file_service = FileService(self.db)
        stored_file_ids: list[str] = []
        for attachment in external_event.attachments:
            if attachment.get("provider") != "work_wechat":
                continue
            stored_file = await run_in_threadpool(
                self._store_work_wechat_attachment,
                file_service,
                username,
                attachment,
            )
            stored_file_ids.append(stored_file.file_id)

        return stored_file_ids

    def _store_work_wechat_attachment(
        self,
        file_service: FileService,
        username: str,
        attachment: dict[str, Any],
    ) -> Any:
        """Download, decrypt, and persist one Work WeChat media attachment."""
        encrypted_bytes, header_filename, content_type = download_work_wechat_media(
            str(attachment["url"])
        )
        decrypted_bytes = decrypt_work_wechat_media(
            encrypted_bytes,
            str(attachment["aes_key"]),
        )
        filename = infer_work_wechat_filename(
            message_type=str(attachment.get("message_type") or "file"),
            header_filename=header_filename,
            content_type=content_type,
        )
        return file_service.store_uploaded_file(
            username=username,
            filename=filename,
            source="channel:work_wechat",
            file_bytes=decrypted_bytes,
        )

    def _default_attachment_message(self, event: ChannelInboundEvent) -> str:
        """Create a fallback text prompt for attachment-only channel turns."""
        attachment_count = len(event.attachments)
        noun = "attachment" if attachment_count == 1 else "attachments"
        return f"The user sent {attachment_count} {noun} through the channel."

    def _build_action_metadata(self, event_data: dict[str, Any]) -> dict[str, Any]:
        """Extract stable event metadata for logs and transport adapters."""
        metadata: dict[str, Any] = {}
        for key in ("task_id", "trace_id", "iteration", "timestamp"):
            value = event_data.get(key)
            if value is not None:
                metadata[key] = value
        return metadata

    def _extract_terminal_text(
        self,
        *,
        event_data: dict[str, Any],
        preferred_keys: tuple[str, ...],
    ) -> str:
        """Normalize one terminal ReAct event into visible channel text."""
        payload = event_data.get("data") or {}
        if isinstance(payload, dict):
            for key in preferred_keys:
                value = payload.get(key)
                if value:
                    return str(value)
            return str(payload)
        if payload:
            return str(payload)
        delta = event_data.get("delta")
        if delta:
            return str(delta)
        return "The agent returned an empty response."

    def _build_channel_progress_view(
        self,
        *,
        current_plan: Any,
        fallback_summary: str | None,
    ) -> ChannelProgressView | None:
        """Convert the current plan payload into a transport-neutral view."""
        from app.channels.types import (
            ChannelPlanStepProgressView,
            ChannelProgressView,
        )

        summary = (fallback_summary or "").strip() or None
        if not isinstance(current_plan, list) or not current_plan:
            if summary is None:
                return None
            return ChannelProgressView(mode="text", summary=summary)

        steps: list[ChannelPlanStepProgressView] = []
        for step in current_plan:
            if not isinstance(step, dict):
                continue
            step_id = step.get("step_id")
            general_goal = step.get("general_goal")
            status = step.get("status")
            if not isinstance(step_id, str) or not isinstance(general_goal, str):
                continue
            if not isinstance(status, str) or not status:
                status = "pending"

            summaries: list[str] = []
            raw_history = step.get("recursion_history")
            if isinstance(raw_history, list):
                for history_entry in raw_history:
                    if not isinstance(history_entry, dict):
                        continue
                    entry_summary = history_entry.get("summary")
                    if isinstance(entry_summary, str) and entry_summary.strip():
                        summaries.append(entry_summary.strip())

            steps.append(
                ChannelPlanStepProgressView(
                    step_id=step_id,
                    general_goal=general_goal,
                    status=status,
                    summaries=summaries,
                )
            )

        if not steps:
            if summary is None:
                return None
            return ChannelProgressView(mode="text", summary=summary)

        return ChannelProgressView(
            mode="plan",
            summary=summary,
            steps=steps,
        )

    def _render_channel_progress_view(
        self,
        *,
        progress_view: ChannelProgressView,
    ) -> str:
        """Render a progress view into concise channel-safe text."""
        if progress_view.mode == "text":
            return progress_view.summary or ""

        lines: list[str] = []
        if progress_view.summary:
            lines.append(progress_view.summary)
            lines.append("")

        for step in progress_view.steps:
            # Use explicit status labels instead of nested markdown bullets because
            # channel providers render streamed markdown inconsistently, which can
            # collapse mixed list/paragraph blocks into messy layouts.
            lines.append(
                f"[{self._channel_progress_status_label(step.status)}] "
                f"{step.general_goal}"
            )
            for item in step.summaries:
                lines.append(f"Progress: {item}")
            lines.append("")

        return "\n".join(lines).strip()

    def _channel_progress_status_label(self, status: str) -> str:
        """Normalize internal plan states into compact channel-facing labels."""
        normalized_status = status.strip().lower()
        if normalized_status == "done":
            return "Done"
        if normalized_status == "running":
            return "Running"
        if normalized_status == "error":
            return "Error"
        return "Pending"

    def _find_resumable_task(self, *, session_id: str) -> ReactTask | None:
        """Find the latest waiting-for-input task for a session, if any."""
        statement = (
            select(ReactTask)
            .where(ReactTask.session_id == session_id)
            .order_by(desc(col(ReactTask.created_at)))
        )
        tasks = self.db.exec(statement).all()
        for task in tasks:
            if task.status == "waiting_input" and not task.pending_user_action_json:
                return task
        return None

    def _inject_clarify_reply(self, *, task: ReactTask, reply: str) -> None:
        """Inject a reply into the last CLARIFY recursion so the task can resume."""
        statement = (
            select(ReactRecursion)
            .where(ReactRecursion.task_id == task.task_id)
            .order_by(desc(col(ReactRecursion.iteration_index)))
        )
        last_recursion = self.db.exec(statement).first()
        if last_recursion is None or last_recursion.action_type != "CLARIFY":
            return

        try:
            payload = json.loads(last_recursion.action_output or "{}")
        except json.JSONDecodeError:
            payload = {}
        payload["reply"] = reply
        last_recursion.action_output = json.dumps(payload, ensure_ascii=False)
        last_recursion.updated_at = datetime.now(UTC)
        task.updated_at = datetime.now(UTC)
        self.db.add(last_recursion)
        self.db.add(task)
        self.db.commit()

    def _build_request_tool_manager(
        self,
        *,
        username: str,
        agent_id: int,
        raw_tool_ids: str | None,
        extension_bundle: list[dict[str, Any]],
    ) -> ToolManager:
        """Build the request-scoped tool manager used by ReAct execution."""
        return ExtensionService(self.db).build_request_tool_manager(
            username=username,
            agent_id=agent_id,
            raw_tool_ids=raw_tool_ids,
            extension_bundle=extension_bundle,
        )

    async def poll_binding_once(self, binding_id: int) -> dict[str, Any]:
        """Poll one Telegram binding once and route any fetched updates."""
        binding = self.db.get(AgentChannelBinding, binding_id)
        if binding is None:
            raise ValueError("Channel binding not found.")
        provider = self._get_channel_provider(binding.channel_key)
        if not isinstance(provider, TelegramProvider):
            raise ValueError("This binding does not support manual polling.")

        runtime_config = _load_json_object(binding.runtime_config)
        offset = None
        for session_row in self.db.exec(
            select(ChannelSession).where(
                ChannelSession.channel_binding_id == binding_id
            )
        ).all():
            if session_row.last_cursor and session_row.last_cursor.isdigit():
                offset = max(offset or 0, int(session_row.last_cursor))

        events, next_offset = provider.poll_once(
            _load_json_object(binding.auth_config),
            runtime_config,
            offset=offset,
        )

        replies: list[dict[str, Any]] = []
        for event in events:
            context = self.build_message_context(event=event)
            for action in await self.collect_outbound_actions(
                binding=binding,
                event=event,
            ):
                if not action.text.strip() or context.conversation_id is None:
                    continue
                provider.send_action(
                    _load_json_object(binding.auth_config),
                    runtime_config,
                    context=context,
                    action=action,
                )
                replies.append(
                    {
                        "conversation_id": context.conversation_id,
                        "external_user_id": context.user_id,
                        "action": action.model_dump(),
                    }
                )

            if next_offset is not None and event.external_conversation_id:
                session_row = self.db.exec(
                    select(ChannelSession).where(
                        ChannelSession.channel_binding_id == binding_id,
                        ChannelSession.external_conversation_id
                        == event.external_conversation_id,
                    )
                ).first()
                if session_row is not None:
                    session_row.last_cursor = str(next_offset)
                    session_row.updated_at = datetime.now(UTC)
                    self.db.add(session_row)

        self.db.commit()
        return {
            "fetched": len(events),
            "next_offset": next_offset,
            "replies": replies,
        }
