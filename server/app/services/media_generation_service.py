"""Services for media-generation provider catalog, bindings, and execution."""

from __future__ import annotations

import base64
import json
import posixpath
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any
from urllib import request as urllib_request

from app.media_generation.types import (
    MediaGenerationArtifact,
    MediaGenerationCollectResult,
    MediaGenerationExecutionResult,
    MediaGenerationInput,
    MediaGenerationProviderBinding,
    MediaGenerationRequest,
)
from app.models.media_generation import (
    AgentMediaProviderBinding,
    MediaGenerationUsageLog,
)
from app.schemas.media_generation import MediaProviderBindingResponse
from app.services.extension_service import ExtensionService
from app.services.file_service import FileService
from app.services.provider_registry_service import ProviderRegistryService
from sqlmodel import Session, col, select

if TYPE_CHECKING:
    from app.models.user import User


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


def _dump_json_array(payload: list[str]) -> str:
    """Serialize a JSON array consistently for text storage."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _workspace_path(path: str) -> str:
    """Resolve and validate a path inside ``/workspace``."""
    raw = (path or ".").strip()
    if raw == "":
        raw = "."

    if raw.startswith("/"):
        full = posixpath.normpath(raw)
    else:
        full = posixpath.normpath(posixpath.join("/workspace", raw))

    if full == "/workspace" or full.startswith("/workspace/"):
        return full
    raise ValueError("Path must stay within /workspace.")


def _host_path_for_workspace_file(
    *,
    workspace_backend_path: str,
    sandbox_path: str,
) -> Path:
    """Resolve one sandbox workspace path to its host-side path."""
    normalized_path = _workspace_path(sandbox_path)
    relative_path = normalized_path.removeprefix("/workspace/") or "."
    return Path(workspace_backend_path).joinpath(*PurePosixPath(relative_path).parts)


class MediaGenerationService:
    """Application service for media-generation bindings and execution."""

    def __init__(self, db: Session) -> None:
        """Store the active database session for media-generation operations."""
        self.db = db

    def _list_media_generation_providers(self) -> list[Any]:
        """Return built-in and extension-backed media-generation providers."""
        return ProviderRegistryService(self.db).list_media_generation_providers()

    def _get_media_generation_provider(self, provider_key: str) -> Any:
        """Resolve one media-generation provider from the unified registry."""
        return ProviderRegistryService(self.db).get_media_generation_provider(
            provider_key
        )

    def _is_provider_available_to_agent(
        self,
        *,
        agent_id: int,
        provider: Any,
        enabled_only: bool = True,
    ) -> bool:
        """Return whether one media provider is available to an agent."""
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
        provider: Any,
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
        """Return installed media-generation providers visible to the agent."""
        providers = self._list_media_generation_providers()
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
        self,
        binding: AgentMediaProviderBinding,
    ) -> MediaProviderBindingResponse:
        """Render one binding with provider manifest metadata."""
        provider = self._get_media_generation_provider(binding.provider_key)
        effective_available, disabled_reason = ExtensionService(
            self.db
        ).get_agent_child_availability(
            agent_id=binding.agent_id,
            package_id=provider.manifest.extension_name,
        )
        auth_config = _load_json_object(binding.auth_config)
        return MediaProviderBindingResponse(
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
        self,
        binding: AgentMediaProviderBinding,
    ) -> MediaGenerationProviderBinding:
        """Convert one ORM row into the provider-facing binding payload."""
        return MediaGenerationProviderBinding(
            provider_key=binding.provider_key,
            enabled=binding.enabled,
            auth_config=_load_json_object(binding.auth_config),
            runtime_config=_load_json_object(binding.runtime_config),
        )

    def list_agent_bindings(self, agent_id: int) -> list[MediaProviderBindingResponse]:
        """List all media-generation bindings attached to one agent."""
        statement = (
            select(AgentMediaProviderBinding)
            .where(AgentMediaProviderBinding.agent_id == agent_id)
            .order_by(col(AgentMediaProviderBinding.created_at))
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
    ) -> MediaProviderBindingResponse:
        """Create a new agent media-provider binding after validation."""
        provider = self._get_media_generation_provider(provider_key)
        if not self.is_provider_usable_by_user(user=user, provider=provider):
            raise ValueError(
                "Media generation provider is not available to the caller."
            )
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
            select(AgentMediaProviderBinding).where(
                AgentMediaProviderBinding.agent_id == agent_id,
                AgentMediaProviderBinding.provider_key == provider_key,
            )
        ).first()
        if existing is not None:
            raise ValueError(
                f"Provider '{provider_key}' is already configured for this agent."
            )

        now = datetime.now(UTC)
        binding = AgentMediaProviderBinding(
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
    ) -> MediaProviderBindingResponse:
        """Update one agent media-generation provider binding."""
        binding = self.db.get(AgentMediaProviderBinding, binding_id)
        if binding is None:
            raise ValueError("Media provider binding not found.")

        provider = self._get_media_generation_provider(binding.provider_key)
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
        """Delete one configured media-generation binding."""
        binding = self.db.get(AgentMediaProviderBinding, binding_id)
        if binding is None:
            raise ValueError("Media provider binding not found.")
        self.db.delete(binding)
        self.db.commit()

    def test_binding(self, binding_id: int) -> dict[str, Any]:
        """Run the provider-specific health check for one saved binding."""
        binding = self.db.get(AgentMediaProviderBinding, binding_id)
        if binding is None:
            raise ValueError("Media provider binding not found.")

        provider = self._get_media_generation_provider(binding.provider_key)
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
        provider = self._get_media_generation_provider(provider_key)
        if not self.is_provider_usable_by_user(user=user, provider=provider):
            raise ValueError(
                "Media generation provider is not available to the caller."
            )
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
    ) -> AgentMediaProviderBinding:
        """Resolve the binding the current tool invocation should use."""
        statement = select(AgentMediaProviderBinding).where(
            AgentMediaProviderBinding.agent_id == agent_id,
            col(AgentMediaProviderBinding.enabled).is_(True),
        )
        if provider_key is not None:
            statement = statement.where(
                AgentMediaProviderBinding.provider_key == provider_key
            )
        bindings = self.db.exec(statement).all()
        available_bindings = [
            binding
            for binding in bindings
            if self._is_provider_available_to_agent(
                agent_id=agent_id,
                provider=self._get_media_generation_provider(binding.provider_key),
                enabled_only=True,
            )
        ]
        if provider_key is not None:
            binding = available_bindings[0] if available_bindings else None
            if binding is None:
                raise ValueError(
                    f"Enabled media provider '{provider_key}' is not configured "
                    f"for agent {agent_id}."
                )
            return binding

        if not available_bindings:
            raise ValueError(
                "This agent has no enabled media-generation providers configured."
            )
        if len(available_bindings) > 1:
            provider_names = ", ".join(
                sorted(binding.provider_key for binding in available_bindings)
            )
            raise ValueError(
                "Multiple enabled media-generation providers are configured for "
                f"this agent. Select one explicitly: {provider_names}."
            )
        return available_bindings[0]

    def execute_request(
        self,
        *,
        agent_id: int,
        username: str,
        workspace_id: str,
        workspace_backend_path: str,
        request: MediaGenerationRequest,
        provider_key: str | None = None,
    ) -> MediaGenerationExecutionResult:
        """Execute one provider-backed media-generation request."""
        binding_row = self.resolve_binding(agent_id=agent_id, provider_key=provider_key)
        binding = self._to_provider_binding(binding_row)
        provider = self._get_media_generation_provider(binding.provider_key)
        provider.validate_config(binding.auth_config, binding.runtime_config)
        prepared_request = self._prepare_request(
            request=request,
            workspace_backend_path=workspace_backend_path,
        )

        usage_log = self._create_usage_log(
            agent_id=agent_id,
            workspace_id=workspace_id,
            username=username,
            provider_key=binding.provider_key,
            operation=prepared_request.operation,
        )

        result: MediaGenerationCollectResult | None = None

        try:
            handle = provider.start(binding=binding, request=prepared_request)
            usage_log.request_id = handle.request_id
            usage_log.provider_task_id = handle.provider_task_id
            usage_log.updated_at = datetime.now(UTC)
            self.db.add(usage_log)
            self.db.commit()

            deadline = time.monotonic() + float(prepared_request.poll_timeout_seconds)
            while True:
                state = provider.poll(binding=binding, handle=handle)
                handle.status = state.status
                if state.request_id is not None:
                    handle.request_id = state.request_id
                    usage_log.request_id = state.request_id
                if state.status == "failed":
                    raise RuntimeError(
                        state.error_message or "Media generation provider failed."
                    )
                if state.status == "succeeded":
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        "Media generation timed out while waiting for the provider "
                        "to finish."
                    )
                time.sleep(prepared_request.poll_interval_seconds)

            result = provider.collect(binding=binding, handle=handle)
            if result is None:
                raise RuntimeError(
                    "Media generation completed without a collected result."
                )
            output_paths = self._persist_artifacts(
                workspace_backend_path=workspace_backend_path,
                output_path=request.output_path,
                artifacts=result.artifacts,
            )
            usage_log.status = "succeeded"
            usage_log.request_id = result.request_id
            usage_log.provider_task_id = result.provider_task_id
            usage_log.artifact_count = len(output_paths)
            usage_log.output_paths_json = _dump_json_array(output_paths)
            usage_log.usage_json = _dump_json_object(result.usage)
            usage_log.provider_payload_json = _dump_json_object(result.raw_payload)
            usage_log.updated_at = datetime.now(UTC)
            usage_log.finished_at = datetime.now(UTC)
            self.db.add(usage_log)
            self.db.commit()
            return MediaGenerationExecutionResult(
                provider={
                    "key": provider.manifest.key,
                    "name": provider.manifest.name,
                },
                operation=prepared_request.operation,
                output_paths=output_paths,
                primary_output_path=output_paths[0] if output_paths else None,
                provider_task_id=result.provider_task_id,
                request_id=result.request_id,
                status=result.status,
                usage=result.usage,
                provider_payload=result.raw_payload,
            )
        except Exception as exc:
            usage_log.status = "failed"
            usage_log.error_message = str(exc)
            if result is not None:
                usage_log.request_id = result.request_id
                usage_log.provider_task_id = result.provider_task_id
                usage_log.usage_json = _dump_json_object(result.usage)
                usage_log.provider_payload_json = _dump_json_object(result.raw_payload)
            usage_log.updated_at = datetime.now(UTC)
            usage_log.finished_at = datetime.now(UTC)
            self.db.add(usage_log)
            self.db.commit()
            raise

    def _prepare_request(
        self,
        *,
        request: MediaGenerationRequest,
        workspace_backend_path: str,
    ) -> MediaGenerationRequest:
        """Resolve workspace-backed media inputs into provider-ready payloads."""
        if not request.inputs:
            return request

        resolved_inputs = [
            self._resolve_input_media(
                item=input_item,
                workspace_backend_path=workspace_backend_path,
            )
            for input_item in request.inputs
        ]
        return request.model_copy(update={"inputs": resolved_inputs})

    def _resolve_input_media(
        self,
        *,
        item: MediaGenerationInput,
        workspace_backend_path: str,
    ) -> MediaGenerationInput:
        """Resolve one input media item into validated bytes and base64."""
        if item.base64_data:
            return item

        if not item.source_path:
            raise ValueError(
                f"Media input '{item.role}' requires source_path or base64_data."
            )

        host_path = _host_path_for_workspace_file(
            workspace_backend_path=workspace_backend_path,
            sandbox_path=item.source_path,
        )
        if not host_path.exists():
            raise ValueError(f"Media input path does not exist: {item.source_path}")
        if not host_path.is_file():
            raise ValueError(f"Media input path must be a file: {item.source_path}")

        file_bytes = host_path.read_bytes()
        file_service = FileService(self.db)
        if item.media_type == "image":
            verified = file_service.verify_image_upload(host_path.name, file_bytes)
            return item.model_copy(
                update={
                    "base64_data": base64.b64encode(verified.file_bytes).decode(
                        "ascii"
                    ),
                    "mime_type": verified.mime_type,
                    "file_name": host_path.name,
                    "source_path": _workspace_path(item.source_path),
                }
            )

        raise ValueError(f"Unsupported input media type: {item.media_type}")

    def _create_usage_log(
        self,
        *,
        agent_id: int,
        workspace_id: str,
        username: str,
        provider_key: str,
        operation: str,
    ) -> MediaGenerationUsageLog:
        """Create one pending usage-log row before provider execution."""
        row = MediaGenerationUsageLog(
            agent_id=agent_id,
            workspace_id=workspace_id,
            username=username,
            provider_key=provider_key,
            operation=operation,
            status="running",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def _persist_artifacts(
        self,
        *,
        workspace_backend_path: str,
        output_path: str,
        artifacts: list[MediaGenerationArtifact],
    ) -> list[str]:
        """Persist provider-returned artifacts under the active workspace root."""
        if not artifacts:
            raise RuntimeError(
                "The provider completed without returning any artifacts."
            )

        normalized_output_path = _workspace_path(output_path)
        file_service = FileService(self.db)
        output_paths: list[str] = []

        for index, artifact in enumerate(artifacts, start=1):
            file_bytes = self._read_artifact_bytes(artifact)
            suggested_name = artifact.suggested_name or self._default_artifact_name(
                artifact
            )
            verified = self._verify_artifact(
                file_service=file_service,
                artifact=artifact,
                file_bytes=file_bytes,
                suggested_name=suggested_name,
            )
            target_sandbox_path = self._build_output_path(
                base_output_path=normalized_output_path,
                artifact_count=len(artifacts),
                artifact_index=index,
                extension=verified.extension,
            )
            relative_path = target_sandbox_path.removeprefix("/workspace/") or "."
            target_host_path = Path(workspace_backend_path).joinpath(
                *PurePosixPath(relative_path).parts
            )
            target_host_path.parent.mkdir(parents=True, exist_ok=True)
            target_host_path.write_bytes(verified.file_bytes)
            output_paths.append(target_sandbox_path)

        return output_paths

    def _read_artifact_bytes(self, artifact: MediaGenerationArtifact) -> bytes:
        """Materialize one provider artifact into raw media bytes."""
        if artifact.base64_data:
            try:
                return base64.b64decode(artifact.base64_data, validate=True)
            except ValueError as exc:
                raise RuntimeError(
                    "Provider returned invalid base64 media data."
                ) from exc

        if artifact.url:
            with urllib_request.urlopen(artifact.url, timeout=120) as response:
                return response.read()

        raise RuntimeError("Provider artifact is missing both URL and base64 data.")

    def _default_artifact_name(self, artifact: MediaGenerationArtifact) -> str:
        """Build a stable fallback filename for one provider artifact."""
        if artifact.media_type == "video":
            return "generated-video.mp4"
        return "generated-image.png"

    def _verify_artifact(
        self,
        *,
        file_service: FileService,
        artifact: MediaGenerationArtifact,
        file_bytes: bytes,
        suggested_name: str,
    ) -> Any:
        """Validate one artifact based on its declared media type."""
        if artifact.media_type == "video":
            return file_service.verify_video_upload(
                suggested_name,
                file_bytes,
                mime_type_hint=artifact.mime_type,
            )
        return file_service.verify_image_upload(suggested_name, file_bytes)

    def _build_output_path(
        self,
        *,
        base_output_path: str,
        artifact_count: int,
        artifact_index: int,
        extension: str,
    ) -> str:
        """Return the final sandbox path for one persisted generated artifact."""
        normalized_extension = extension.lstrip(".")
        path = PurePosixPath(base_output_path)
        suffix = path.suffix
        if artifact_count == 1:
            if suffix:
                return path.as_posix()
            return path.with_name(f"{path.name}.{normalized_extension}").as_posix()

        stem_name = path.stem if suffix else path.name
        parent = path.parent
        return (
            parent / f"{stem_name}-{artifact_index}.{normalized_extension}"
        ).as_posix()
