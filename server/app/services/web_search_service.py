"""Services for web-search provider catalog, bindings, and execution."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.models.web_search import AgentWebSearchBinding
from app.orchestration.web_search.types import WebSearchProviderBinding
from app.schemas.web_search import WebSearchBindingResponse
from app.services.extension_service import ExtensionService
from app.services.provider_registry_service import ProviderRegistryService
from sqlmodel import Session, col, select

if TYPE_CHECKING:
    from app.models.user import User
    from app.orchestration.web_search.types import (
        WebSearchExecutionResult,
        WebSearchProvider,
        WebSearchQueryRequest,
    )


def _load_json_object(raw_value: str | None) -> dict[str, Any]:
    """Parse a JSON object stored in a text column."""
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


class WebSearchService:
    """Application service for web-search catalog, bindings, and execution."""

    def __init__(self, db: Session) -> None:
        """Store the active database session for web-search operations."""
        self.db = db

    def _list_web_search_providers(self) -> list[WebSearchProvider]:
        """Return built-in and extension-backed web-search providers."""
        return ProviderRegistryService(self.db).list_web_search_providers()

    def _get_web_search_provider(self, provider_key: str) -> WebSearchProvider:
        """Resolve one provider from the unified provider registry."""
        return ProviderRegistryService(self.db).get_web_search_provider(provider_key)

    def _is_provider_available_to_agent(
        self,
        *,
        agent_id: int,
        provider: WebSearchProvider,
        enabled_only: bool = True,
    ) -> bool:
        """Return whether one provider is available to an agent."""
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
        provider: WebSearchProvider,
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
        """Return installed web-search providers visible to the current agent."""
        providers = self._list_web_search_providers()
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
        self, binding: AgentWebSearchBinding
    ) -> WebSearchBindingResponse:
        """Render one binding with provider manifest metadata."""
        provider = self._get_web_search_provider(binding.provider_key)
        effective_available, disabled_reason = ExtensionService(
            self.db
        ).get_agent_child_availability(
            agent_id=binding.agent_id,
            package_id=provider.manifest.extension_name,
        )
        auth_config = _load_json_object(binding.auth_config)
        return WebSearchBindingResponse(
            id=binding.id or 0,
            agent_id=binding.agent_id,
            provider_key=binding.provider_key,
            enabled=binding.enabled,
            effective_enabled=binding.enabled and effective_available,
            disabled_reason=disabled_reason,
            auth_config={key: str(value) for key, value in auth_config.items()},
            runtime_config=_load_json_object(binding.runtime_config),
            manifest=provider.manifest.model_dump(),
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

    def _to_provider_binding(
        self, binding: AgentWebSearchBinding
    ) -> WebSearchProviderBinding:
        """Convert one ORM row into the provider-facing binding payload."""
        return WebSearchProviderBinding(
            provider_key=binding.provider_key,
            enabled=binding.enabled,
            auth_config=_load_json_object(binding.auth_config),
            runtime_config=_load_json_object(binding.runtime_config),
        )

    def list_agent_bindings(self, agent_id: int) -> list[WebSearchBindingResponse]:
        """List all web-search bindings attached to one agent."""
        statement = (
            select(AgentWebSearchBinding)
            .where(AgentWebSearchBinding.agent_id == agent_id)
            .order_by(col(AgentWebSearchBinding.created_at))
        )
        rows = self.db.exec(statement).all()
        return [self._serialize_binding(row) for row in rows]

    def create_binding(
        self,
        *,
        agent_id: int,
        provider_key: str,
        enabled: bool,
        auth_config: dict[str, Any],
        runtime_config: dict[str, Any],
        user: User | None = None,
    ) -> WebSearchBindingResponse:
        """Create a new agent web-search binding after provider validation."""
        provider = self._get_web_search_provider(provider_key)
        if not self.is_provider_usable_by_user(user=user, provider=provider):
            raise ValueError("Web search provider is not available to the caller.")
        if not self._is_provider_available_to_agent(
            agent_id=agent_id,
            provider=provider,
            enabled_only=False,
        ):
            raise ValueError(
                "Install the owning extension on this agent before configuring this provider."
            )
        provider.validate_config(auth_config, runtime_config)

        existing = self.db.exec(
            select(AgentWebSearchBinding).where(
                AgentWebSearchBinding.agent_id == agent_id,
                AgentWebSearchBinding.provider_key == provider_key,
            )
        ).first()
        if existing is not None:
            raise ValueError(
                f"Provider '{provider_key}' is already configured for this agent."
            )

        now = datetime.now(UTC)
        binding = AgentWebSearchBinding(
            agent_id=agent_id,
            provider_key=provider_key,
            enabled=enabled,
            auth_config=_dump_json_object(auth_config),
            runtime_config=_dump_json_object(runtime_config),
            created_at=now,
            updated_at=now,
        )
        self.db.add(binding)
        self.db.commit()
        self.db.refresh(binding)
        return self._serialize_binding(binding)

    def update_binding(
        self,
        binding_id: int,
        *,
        enabled: bool | None = None,
        auth_config: dict[str, Any] | None = None,
        runtime_config: dict[str, Any] | None = None,
    ) -> WebSearchBindingResponse:
        """Update one agent web-search provider binding."""
        binding = self.db.get(AgentWebSearchBinding, binding_id)
        if binding is None:
            raise ValueError("Web search binding not found.")

        provider = self._get_web_search_provider(binding.provider_key)
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
        """Delete one configured web-search binding."""
        binding = self.db.get(AgentWebSearchBinding, binding_id)
        if binding is None:
            raise ValueError("Web search binding not found.")
        self.db.delete(binding)
        self.db.commit()

    def test_binding(self, binding_id: int) -> dict[str, Any]:
        """Run the provider-specific health check for one saved binding."""
        binding = self.db.get(AgentWebSearchBinding, binding_id)
        if binding is None:
            raise ValueError("Web search binding not found.")

        provider = self._get_web_search_provider(binding.provider_key)
        result = provider.test_connection(
            auth_config=_load_json_object(binding.auth_config),
            runtime_config=_load_json_object(binding.runtime_config),
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
        provider_key: str,
        auth_config: dict[str, Any],
        runtime_config: dict[str, Any],
        user: User | None = None,
    ) -> dict[str, Any]:
        """Run a provider health check against unsaved form values."""
        provider = self._get_web_search_provider(provider_key)
        if not self.is_provider_usable_by_user(user=user, provider=provider):
            raise ValueError("Web search provider is not available to the caller.")
        provider.validate_config(auth_config, runtime_config)
        result = provider.test_connection(
            auth_config=auth_config,
            runtime_config=runtime_config,
        )
        return {"result": result.model_dump()}

    def resolve_binding(
        self,
        *,
        agent_id: int,
        provider_key: str | None,
    ) -> AgentWebSearchBinding:
        """Resolve the binding the abstract tool should use for one request."""
        statement = select(AgentWebSearchBinding).where(
            AgentWebSearchBinding.agent_id == agent_id,
            col(AgentWebSearchBinding.enabled).is_(True),
        )
        if provider_key is not None:
            statement = statement.where(
                AgentWebSearchBinding.provider_key == provider_key
            )
        bindings = self.db.exec(statement).all()
        available_bindings = [
            binding
            for binding in bindings
            if self._is_provider_available_to_agent(
                agent_id=agent_id,
                provider=self._get_web_search_provider(binding.provider_key),
                enabled_only=True,
            )
        ]
        if provider_key is not None:
            binding = available_bindings[0] if available_bindings else None
            if binding is None:
                raise ValueError(
                    f"Enabled web search provider '{provider_key}' is not configured "
                    f"for agent {agent_id}."
                )
            return binding

        if not available_bindings:
            raise ValueError(
                "This agent has no enabled web search providers configured."
            )
        if len(available_bindings) > 1:
            provider_names = ", ".join(
                sorted(binding.provider_key for binding in available_bindings)
            )
            raise ValueError(
                "Multiple web search providers are enabled for this agent. "
                f"Specify provider explicitly. Available providers: {provider_names}."
            )
        return available_bindings[0]

    def execute_search(
        self,
        *,
        agent_id: int,
        request: WebSearchQueryRequest,
    ) -> WebSearchExecutionResult:
        """Execute one abstract web search for an agent."""
        binding = self.resolve_binding(
            agent_id=agent_id,
            provider_key=request.provider,
        )
        provider = self._get_web_search_provider(binding.provider_key)
        effective_request = request.model_copy(
            update={"provider": binding.provider_key}
        )
        return provider.search(
            binding=self._to_provider_binding(binding),
            request=effective_request,
        )
