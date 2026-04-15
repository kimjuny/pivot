"""Services for image-generation provider catalog, bindings, and execution."""

from __future__ import annotations

import base64
import json
import posixpath
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib import request as urllib_request

from app.image_generation.types import (
    ImageGenerationArtifact,
    ImageGenerationExecutionResult,
    ImageGenerationProviderBinding,
    ImageGenerationRequest,
)
from app.models.image_generation import (
    AgentImageProviderBinding,
    ImageGenerationUsageLog,
)
from app.schemas.image_generation import ImageProviderBindingResponse
from app.services.file_service import FileService
from app.services.provider_registry_service import ProviderRegistryService
from sqlmodel import Session, col, select


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


class ImageGenerationService:
    """Application service for image-generation bindings and execution."""

    def __init__(self, db: Session) -> None:
        """Store the active database session for image-generation operations."""
        self.db = db

    def _list_image_generation_providers(self) -> list[Any]:
        """Return built-in and extension-backed image-generation providers."""
        return ProviderRegistryService(self.db).list_image_generation_providers()

    def _get_image_generation_provider(self, provider_key: str) -> Any:
        """Resolve one image-generation provider from the unified registry."""
        return ProviderRegistryService(self.db).get_image_generation_provider(
            provider_key
        )

    def list_catalog(self) -> list[dict[str, Any]]:
        """Return all installed image-generation provider manifests."""
        return [
            {"manifest": provider.manifest.model_dump()}
            for provider in self._list_image_generation_providers()
        ]

    def _serialize_binding(
        self,
        binding: AgentImageProviderBinding,
    ) -> ImageProviderBindingResponse:
        """Render one binding with provider manifest metadata."""
        provider = self._get_image_generation_provider(binding.provider_key)
        auth_config = _load_json_object(binding.auth_config)
        return ImageProviderBindingResponse(
            id=binding.id or 0,
            agent_id=binding.agent_id,
            provider_key=binding.provider_key,
            enabled=binding.enabled,
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
        binding: AgentImageProviderBinding,
    ) -> ImageGenerationProviderBinding:
        """Convert one ORM row into the provider-facing binding payload."""
        return ImageGenerationProviderBinding(
            provider_key=binding.provider_key,
            enabled=binding.enabled,
            auth_config=_load_json_object(binding.auth_config),
            runtime_config=_load_json_object(binding.runtime_config),
        )

    def list_agent_bindings(self, agent_id: int) -> list[ImageProviderBindingResponse]:
        """List all image-generation bindings attached to one agent."""
        statement = (
            select(AgentImageProviderBinding)
            .where(AgentImageProviderBinding.agent_id == agent_id)
            .order_by(col(AgentImageProviderBinding.created_at))
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
    ) -> ImageProviderBindingResponse:
        """Create a new agent image-provider binding after validation."""
        provider = self._get_image_generation_provider(provider_key)
        provider.validate_config(auth_config, runtime_config)

        existing = self.db.exec(
            select(AgentImageProviderBinding).where(
                AgentImageProviderBinding.agent_id == agent_id,
                AgentImageProviderBinding.provider_key == provider_key,
            )
        ).first()
        if existing is not None:
            raise ValueError(
                f"Provider '{provider_key}' is already configured for this agent."
            )

        now = datetime.now(UTC)
        binding = AgentImageProviderBinding(
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
    ) -> ImageProviderBindingResponse:
        """Update one agent image-generation provider binding."""
        binding = self.db.get(AgentImageProviderBinding, binding_id)
        if binding is None:
            raise ValueError("Image provider binding not found.")

        provider = self._get_image_generation_provider(binding.provider_key)
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
        """Delete one configured image-generation binding."""
        binding = self.db.get(AgentImageProviderBinding, binding_id)
        if binding is None:
            raise ValueError("Image provider binding not found.")
        self.db.delete(binding)
        self.db.commit()

    def test_binding(self, binding_id: int) -> dict[str, Any]:
        """Run the provider-specific health check for one saved binding."""
        binding = self.db.get(AgentImageProviderBinding, binding_id)
        if binding is None:
            raise ValueError("Image provider binding not found.")

        provider = self._get_image_generation_provider(binding.provider_key)
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
    ) -> dict[str, Any]:
        """Run a provider health check against unsaved form values."""
        provider = self._get_image_generation_provider(provider_key)
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
    ) -> AgentImageProviderBinding:
        """Resolve the binding the current tool invocation should use."""
        statement = select(AgentImageProviderBinding).where(
            AgentImageProviderBinding.agent_id == agent_id,
            col(AgentImageProviderBinding.enabled).is_(True),
        )
        if provider_key is not None:
            statement = statement.where(
                AgentImageProviderBinding.provider_key == provider_key
            )
        bindings = self.db.exec(statement).all()
        if provider_key is not None:
            binding = bindings[0] if bindings else None
            if binding is None:
                raise ValueError(
                    f"Enabled image provider '{provider_key}' is not configured "
                    f"for agent {agent_id}."
                )
            return binding

        if not bindings:
            raise ValueError(
                "This agent has no enabled image-generation providers configured."
            )
        if len(bindings) > 1:
            provider_names = ", ".join(
                sorted(binding.provider_key for binding in bindings)
            )
            raise ValueError(
                "Multiple enabled image-generation providers are configured for "
                f"this agent. Select one explicitly: {provider_names}."
            )
        return bindings[0]

    def execute_request(
        self,
        *,
        agent_id: int,
        username: str,
        workspace_id: str,
        workspace_backend_path: str,
        request: ImageGenerationRequest,
        provider_key: str | None = None,
    ) -> ImageGenerationExecutionResult:
        """Execute one provider-backed image-generation request."""
        binding_row = self.resolve_binding(agent_id=agent_id, provider_key=provider_key)
        binding = self._to_provider_binding(binding_row)
        provider = self._get_image_generation_provider(binding.provider_key)
        provider.validate_config(binding.auth_config, binding.runtime_config)

        usage_log = self._create_usage_log(
            agent_id=agent_id,
            workspace_id=workspace_id,
            username=username,
            provider_key=binding.provider_key,
            operation=request.operation,
        )

        result: ImageGenerationCollectResult | None = None

        try:
            handle = provider.start(binding=binding, request=request)
            usage_log.request_id = handle.request_id
            usage_log.provider_task_id = handle.provider_task_id
            usage_log.updated_at = datetime.now(UTC)
            self.db.add(usage_log)
            self.db.commit()

            deadline = time.monotonic() + float(request.poll_timeout_seconds)
            while True:
                state = provider.poll(binding=binding, handle=handle)
                handle.status = state.status
                if state.request_id is not None:
                    handle.request_id = state.request_id
                    usage_log.request_id = state.request_id
                if state.status == "failed":
                    raise RuntimeError(
                        state.error_message or "Image generation provider failed."
                    )
                if state.status == "succeeded":
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        "Image generation timed out while waiting for the provider "
                        "to finish."
                    )
                time.sleep(request.poll_interval_seconds)

            result = provider.collect(binding=binding, handle=handle)
            output_paths = self._persist_artifacts(
                workspace_backend_path=workspace_backend_path,
                output_path=request.output_path,
                artifacts=result.artifacts,
            )
            usage_log.status = "succeeded"
            usage_log.request_id = result.request_id
            usage_log.provider_task_id = result.provider_task_id
            usage_log.image_count = len(output_paths)
            usage_log.output_paths_json = _dump_json_array(output_paths)
            usage_log.usage_json = _dump_json_object(result.usage)
            usage_log.provider_payload_json = _dump_json_object(result.raw_payload)
            usage_log.updated_at = datetime.now(UTC)
            usage_log.finished_at = datetime.now(UTC)
            self.db.add(usage_log)
            self.db.commit()
            return ImageGenerationExecutionResult(
                provider={
                    "key": provider.manifest.key,
                    "name": provider.manifest.name,
                },
                operation=request.operation,
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

    def _create_usage_log(
        self,
        *,
        agent_id: int,
        workspace_id: str,
        username: str,
        provider_key: str,
        operation: str,
    ) -> ImageGenerationUsageLog:
        """Create one pending usage-log row before provider execution."""
        row = ImageGenerationUsageLog(
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
        artifacts: list[ImageGenerationArtifact],
    ) -> list[str]:
        """Persist provider-returned artifacts under the active workspace root."""
        if not artifacts:
            raise RuntimeError("The provider completed without returning any images.")

        normalized_output_path = _workspace_path(output_path)
        file_service = FileService(self.db)
        output_paths: list[str] = []

        for index, artifact in enumerate(artifacts, start=1):
            file_bytes = self._read_artifact_bytes(artifact)
            verified = file_service.verify_image_upload(
                artifact.suggested_name or "generated-image.png",
                file_bytes,
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

    def _read_artifact_bytes(self, artifact: ImageGenerationArtifact) -> bytes:
        """Materialize one provider artifact into raw image bytes."""
        if artifact.base64_data:
            try:
                return base64.b64decode(artifact.base64_data, validate=True)
            except ValueError as exc:
                raise RuntimeError(
                    "Provider returned invalid base64 image data."
                ) from exc

        if artifact.url:
            with urllib_request.urlopen(artifact.url, timeout=120) as response:
                return response.read()

        raise RuntimeError("Provider artifact is missing both URL and base64 data.")

    def _build_output_path(
        self,
        *,
        base_output_path: str,
        artifact_count: int,
        artifact_index: int,
        extension: str,
    ) -> str:
        """Return the final sandbox path for one persisted generated image."""
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
