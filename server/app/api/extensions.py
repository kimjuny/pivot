"""API endpoints for extension package installation and agent bindings."""

from __future__ import annotations

import json
import mimetypes
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.api.auth import get_current_user
from app.api.dependencies import get_db
from app.models.extension import (
    AgentExtensionBinding,
    ExtensionHookExecution,
    ExtensionInstallation,
)
from app.schemas.extension import (
    AgentExtensionBindingBatchRequest,
    AgentExtensionBindingRequest,
    AgentExtensionBindingResponse,
    AgentExtensionPackageResponse,
    ExtensionConfigurationFieldResponse,
    ExtensionConfigurationSchemaResponse,
    ExtensionConfigurationSectionResponse,
    ExtensionContributionItemResponse,
    ExtensionContributionSummaryResponse,
    ExtensionHookExecutionResponse,
    ExtensionHookReplayResponse,
    ExtensionImportPreviewResponse,
    ExtensionInstallationConfigRequest,
    ExtensionInstallationConfigResponse,
    ExtensionInstallationResponse,
    ExtensionInstallationStatusRequest,
    ExtensionInstallRequest,
    ExtensionPackageResponse,
    ExtensionReferenceSummaryResponse,
    ExtensionUninstallResponse,
)
from app.services.agent_service import AgentService
from app.services.extension_hook_execution_service import ExtensionHookExecutionService
from app.services.extension_hook_replay_service import ExtensionHookReplayService
from app.services.extension_service import (
    ExtensionBundleImportFile,
    ExtensionInstallPreview,
    ExtensionService,
)
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import Session, col, select

if TYPE_CHECKING:
    from app.models.user import User

router = APIRouter()

_EXTENSION_LOGO_MEDIA_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}


def _serialize_utc_timestamp(timestamp: datetime) -> str:
    """Return one explicit UTC ISO timestamp string for API responses."""
    return timestamp.replace(tzinfo=UTC).isoformat()


def _extract_manifest_names(
    raw_items: object,
    *,
    primary_field: str,
) -> list[str]:
    """Return unique contribution identifiers from one manifest section."""
    if not isinstance(raw_items, list):
        return []

    names: list[str] = []
    seen_names: set[str] = set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        raw_name = item.get(primary_field)
        if not isinstance(raw_name, str):
            continue
        normalized_name = raw_name.strip()
        if not normalized_name or normalized_name in seen_names:
            continue
        seen_names.add(normalized_name)
        names.append(normalized_name)
    return names


def _serialize_contribution_summary(
    installation: ExtensionInstallation,
) -> ExtensionContributionSummaryResponse:
    """Expose normalized contribution names for one installed version."""
    try:
        parsed_manifest = json.loads(installation.manifest_json)
    except json.JSONDecodeError:
        parsed_manifest = {}

    contributions = (
        parsed_manifest.get("contributions", {})
        if isinstance(parsed_manifest, dict)
        else {}
    )
    if not isinstance(contributions, dict):
        contributions = {}

    return ExtensionContributionSummaryResponse(
        tools=_extract_manifest_names(
            contributions.get("tools"),
            primary_field="name",
        ),
        skills=_extract_manifest_names(
            contributions.get("skills"),
            primary_field="name",
        ),
        hooks=_extract_manifest_names(
            contributions.get("hooks"),
            primary_field="name",
        ),
        channel_providers=_extract_manifest_names(
            contributions.get("channel_providers"),
            primary_field="key",
        ),
        image_providers=_extract_manifest_names(
            contributions.get("image_providers"),
            primary_field="key",
        ),
        web_search_providers=_extract_manifest_names(
            contributions.get("web_search_providers"),
            primary_field="key",
        ),
    )


def _serialize_installation(
    installation: ExtensionInstallation,
    *,
    service: ExtensionService,
) -> ExtensionInstallationResponse:
    """Convert one installed extension row into an API response."""
    return ExtensionInstallationResponse(
        id=installation.id or 0,
        scope=installation.scope,
        name=installation.name,
        package_id=installation.package_id,
        version=installation.version,
        display_name=installation.display_name,
        description=installation.description,
        logo_url=service.get_installation_logo_url(installation),
        manifest_hash=installation.manifest_hash,
        artifact_storage_backend=installation.artifact_storage_backend,
        artifact_key=installation.artifact_key,
        artifact_digest=installation.artifact_digest,
        artifact_size_bytes=installation.artifact_size_bytes,
        install_root=str(service.get_runtime_install_root(installation)),
        source=installation.source,
        trust_status=installation.trust_status,
        trust_source=installation.trust_source,
        hub_scope=installation.hub_scope,
        hub_package_id=installation.hub_package_id,
        hub_package_version_id=installation.hub_package_version_id,
        hub_artifact_digest=installation.hub_artifact_digest,
        installed_by=installation.installed_by,
        status=installation.status,
        created_at=_serialize_utc_timestamp(installation.created_at),
        updated_at=_serialize_utc_timestamp(installation.updated_at),
        contribution_summary=_serialize_contribution_summary(installation),
        contribution_items=[
            ExtensionContributionItemResponse(**item)
            for item in service.get_installation_contribution_items(installation)
        ],
        reference_summary=_serialize_reference_summary(
            service.get_reference_summary(
                installation_id=installation.id or 0
            ).to_dict()
        ),
    )


def _serialize_configuration_schema(
    payload: object,
) -> ExtensionConfigurationSchemaResponse:
    """Convert one normalized manifest configuration object into an API response."""
    if not isinstance(payload, dict):
        return ExtensionConfigurationSchemaResponse()

    def _serialize_section(section_name: str) -> ExtensionConfigurationSectionResponse:
        raw_section = payload.get(section_name, {})
        if not isinstance(raw_section, dict):
            return ExtensionConfigurationSectionResponse()
        raw_fields = raw_section.get("fields", [])
        if not isinstance(raw_fields, list):
            return ExtensionConfigurationSectionResponse()

        fields: list[ExtensionConfigurationFieldResponse] = []
        for raw_field in raw_fields:
            if not isinstance(raw_field, dict):
                continue
            if not isinstance(raw_field.get("key"), str):
                continue
            field_key = raw_field["key"]
            raw_label = raw_field.get("label")
            raw_type = raw_field.get("type")
            raw_description = raw_field.get("description")
            raw_placeholder = raw_field.get("placeholder")
            fields.append(
                ExtensionConfigurationFieldResponse(
                    key=field_key,
                    label=raw_label if isinstance(raw_label, str) else field_key,
                    type=raw_type if isinstance(raw_type, str) else "string",
                    description=raw_description
                    if isinstance(raw_description, str)
                    else "",
                    required=bool(raw_field.get("required", False)),
                    default=raw_field.get("default"),
                    placeholder=raw_placeholder
                    if isinstance(raw_placeholder, str)
                    else "",
                )
            )
        return ExtensionConfigurationSectionResponse(fields=fields)

    return ExtensionConfigurationSchemaResponse(
        installation=_serialize_section("installation"),
        binding=_serialize_section("binding"),
    )


def _parse_config(raw_value: str | None) -> dict[str, object]:
    """Parse optional binding config JSON into a dictionary."""
    if not raw_value:
        return {}
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _serialize_binding(
    binding: AgentExtensionBinding,
    installation: ExtensionInstallation,
    *,
    service: ExtensionService,
) -> AgentExtensionBindingResponse:
    """Render one binding with its referenced installation metadata."""
    return AgentExtensionBindingResponse(
        id=binding.id or 0,
        agent_id=binding.agent_id,
        extension_installation_id=binding.extension_installation_id,
        enabled=binding.enabled,
        priority=binding.priority,
        config=_parse_config(binding.config_json),
        created_at=_serialize_utc_timestamp(binding.created_at),
        updated_at=_serialize_utc_timestamp(binding.updated_at),
        installation=_serialize_installation(installation, service=service),
    )


def _serialize_preview(
    preview: ExtensionInstallPreview,
) -> ExtensionImportPreviewResponse:
    """Convert one service-layer import preview into an API response."""
    return ExtensionImportPreviewResponse(
        scope=preview.scope,
        name=preview.name,
        package_id=preview.package_id,
        version=preview.version,
        display_name=preview.display_name,
        description=preview.description,
        source=preview.source,
        trust_status=preview.trust_status,
        trust_source=preview.trust_source,
        manifest_hash=preview.manifest_hash,
        contribution_summary=ExtensionContributionSummaryResponse(
            tools=preview.contribution_summary.get("tools", []),
            skills=preview.contribution_summary.get("skills", []),
            hooks=preview.contribution_summary.get("hooks", []),
            channel_providers=preview.contribution_summary.get(
                "channel_providers",
                [],
            ),
            image_providers=preview.contribution_summary.get(
                "image_providers",
                [],
            ),
            web_search_providers=preview.contribution_summary.get(
                "web_search_providers",
                [],
            ),
        ),
        contribution_items=[
            ExtensionContributionItemResponse(**item)
            for item in preview.contribution_items
        ],
        permissions=preview.permissions,
        existing_installation_id=preview.existing_installation_id,
        existing_installation_status=preview.existing_installation_status,
        identical_to_installed=preview.identical_to_installed,
        requires_overwrite_confirmation=preview.requires_overwrite_confirmation,
        overwrite_blocked_reason=preview.overwrite_blocked_reason,
        existing_reference_summary=(
            _serialize_reference_summary(preview.existing_reference_summary.to_dict())
            if preview.existing_reference_summary is not None
            else None
        ),
    )


def _serialize_reference_summary(
    payload: dict[str, int],
) -> ExtensionReferenceSummaryResponse:
    """Convert a reference-summary dictionary into an API response."""
    return ExtensionReferenceSummaryResponse(**payload)


def _parse_optional_json(raw_value: str | None) -> Any:
    """Parse one optional persisted JSON blob into Python data."""
    if raw_value is None:
        return None
    try:
        return json.loads(raw_value)
    except json.JSONDecodeError:
        return None


def _serialize_hook_execution(
    execution: ExtensionHookExecution,
) -> ExtensionHookExecutionResponse:
    """Convert one hook execution row into an API response."""
    hook_context = _parse_optional_json(execution.hook_context_json)
    effects = _parse_optional_json(execution.effects_json)
    error = _parse_optional_json(execution.error_json)
    return ExtensionHookExecutionResponse(
        id=execution.id or 0,
        session_id=execution.session_id,
        task_id=execution.task_id,
        trace_id=execution.trace_id,
        iteration=execution.iteration,
        agent_id=execution.agent_id,
        release_id=execution.release_id,
        extension_package_id=execution.extension_package_id,
        extension_version=execution.extension_version,
        hook_event=execution.hook_event,
        hook_callable=execution.hook_callable,
        status=execution.status,
        hook_context=hook_context if isinstance(hook_context, dict) else None,
        effects=effects if isinstance(effects, list) else None,
        error=error if isinstance(error, dict) else None,
        started_at=_serialize_utc_timestamp(execution.started_at),
        finished_at=_serialize_utc_timestamp(execution.finished_at),
        duration_ms=execution.duration_ms,
    )


def _serialize_package(
    payload: dict[str, object],
    *,
    service: ExtensionService,
) -> ExtensionPackageResponse:
    """Convert one grouped package payload into an API response."""
    raw_versions = payload.get("versions", [])
    active_version_count = payload.get("active_version_count", 0)
    disabled_version_count = payload.get("disabled_version_count", 0)
    versions = (
        [
            _serialize_installation(item, service=service)
            for item in raw_versions
            if isinstance(item, ExtensionInstallation)
        ]
        if isinstance(raw_versions, list)
        else []
    )
    return ExtensionPackageResponse(
        scope=str(payload.get("scope", "")),
        name=str(payload.get("name", "")),
        package_id=str(payload.get("package_id", "")),
        display_name=str(payload.get("display_name", "")),
        description=str(payload.get("description", "")),
        logo_url=next(
            (version.logo_url for version in versions if version.logo_url),
            None,
        ),
        readme_markdown=str(payload.get("readme_markdown", "")),
        latest_version=str(payload.get("latest_version", "")),
        active_version_count=(
            active_version_count if isinstance(active_version_count, int) else 0
        ),
        disabled_version_count=(
            disabled_version_count if isinstance(disabled_version_count, int) else 0
        ),
        versions=versions,
    )


def _serialize_agent_package(
    payload: dict[str, object],
    *,
    service: ExtensionService,
) -> AgentExtensionPackageResponse:
    """Convert one agent-scoped package payload into an API response."""
    package_response = _serialize_package(payload, service=service)
    raw_selected_binding = payload.get("selected_binding")
    raw_versions = payload.get("versions", [])
    selected_binding = None
    if isinstance(raw_selected_binding, AgentExtensionBinding):
        installation = raw_selected_binding.extension_installation_id
        if installation > 0:
            selected_installation = None
            if isinstance(raw_versions, list):
                for item in raw_versions:
                    if (
                        isinstance(item, ExtensionInstallation)
                        and item.id == raw_selected_binding.extension_installation_id
                    ):
                        selected_installation = item
                        break
            if selected_installation is not None:
                selected_binding = _serialize_binding(
                    raw_selected_binding,
                    selected_installation,
                    service=service,
                )

    has_update_available = payload.get("has_update_available", False)
    return AgentExtensionPackageResponse(
        scope=package_response.scope,
        name=package_response.name,
        package_id=package_response.package_id,
        display_name=package_response.display_name,
        description=package_response.description,
        logo_url=package_response.logo_url,
        latest_version=package_response.latest_version,
        active_version_count=package_response.active_version_count,
        disabled_version_count=package_response.disabled_version_count,
        has_update_available=(
            has_update_available if isinstance(has_update_available, bool) else False
        ),
        selected_binding=selected_binding,
        versions=package_response.versions,
    )


@router.get(
    "/extensions/packages",
    response_model=list[ExtensionPackageResponse],
)
async def list_extension_packages(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ExtensionPackageResponse]:
    """List installed extensions grouped by package name."""
    del current_user
    service = ExtensionService(db)
    return [
        _serialize_package(item, service=service) for item in service.list_packages()
    ]


@router.get(
    "/extensions/installations",
    response_model=list[ExtensionInstallationResponse],
)
async def list_extension_installations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ExtensionInstallationResponse]:
    """List all installed extension versions."""
    del current_user
    service = ExtensionService(db)
    return [
        _serialize_installation(item, service=service)
        for item in service.list_installations()
    ]


@router.get("/extensions/installations/{installation_id}/logo", include_in_schema=False)
async def get_extension_installation_logo(
    installation_id: int,
    db: Session = Depends(get_db),
) -> FileResponse:
    """Serve one installation-scoped extension logo asset.

    Why: browser image requests do not attach the Studio bearer token, so logo
    assets need the same public-read behavior as other UI-only brand marks.
    """
    service = ExtensionService(db)
    installation = service.get_installation(installation_id)
    if installation is None:
        raise HTTPException(status_code=404, detail="Extension installation not found")

    logo_path = service.get_installation_logo_path(installation)
    if logo_path is None:
        raise HTTPException(status_code=404, detail="Extension logo not found")

    media_type = _EXTENSION_LOGO_MEDIA_TYPES.get(logo_path.suffix.lower())
    if media_type is None:
        media_type, _ = mimetypes.guess_type(logo_path.name)
    return FileResponse(
        str(logo_path),
        media_type=media_type or "application/octet-stream",
    )


@router.get(
    "/extensions/installations/{installation_id}/configuration",
    response_model=ExtensionInstallationConfigResponse,
)
async def get_extension_installation_configuration(
    installation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExtensionInstallationConfigResponse:
    """Return manifest-declared configuration schema and values for one installation."""
    del current_user
    service = ExtensionService(db)
    try:
        state = service.get_installation_configuration_state(
            installation_id=installation_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ExtensionInstallationConfigResponse(
        installation_id=int(state["installation_id"]),
        package_id=str(state["package_id"]),
        version=str(state["version"]),
        configuration_schema=_serialize_configuration_schema(state.get("schema")),
        config=state.get("config", {}) if isinstance(state.get("config"), dict) else {},
    )


@router.put(
    "/extensions/installations/{installation_id}/configuration",
    response_model=ExtensionInstallationConfigResponse,
)
async def update_extension_installation_configuration(
    installation_id: int,
    payload: ExtensionInstallationConfigRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExtensionInstallationConfigResponse:
    """Validate and persist installation-scoped configuration values."""
    del current_user
    service = ExtensionService(db)
    try:
        service.update_installation_config(
            installation_id=installation_id,
            config=payload.config,
        )
        state = service.get_installation_configuration_state(
            installation_id=installation_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ExtensionInstallationConfigResponse(
        installation_id=int(state["installation_id"]),
        package_id=str(state["package_id"]),
        version=str(state["version"]),
        configuration_schema=_serialize_configuration_schema(state.get("schema")),
        config=state.get("config", {}) if isinstance(state.get("config"), dict) else {},
    )


@router.get(
    "/extensions/hook-executions",
    response_model=list[ExtensionHookExecutionResponse],
)
async def list_extension_hook_executions(
    session_id: str | None = None,
    task_id: str | None = None,
    trace_id: str | None = None,
    iteration: int | None = None,
    extension_package_id: str | None = None,
    hook_event: str | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ExtensionHookExecutionResponse]:
    """List recorded hook execution logs with optional filters."""
    del current_user
    rows = ExtensionHookExecutionService(db).list_executions(
        session_id=session_id,
        task_id=task_id,
        trace_id=trace_id,
        iteration=iteration,
        extension_package_id=extension_package_id,
        hook_event=hook_event,
        limit=limit,
    )
    return [_serialize_hook_execution(row) for row in rows]


@router.post(
    "/extensions/hook-executions/{execution_id}/replay",
    response_model=ExtensionHookReplayResponse,
)
async def replay_hook_execution(
    execution_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExtensionHookReplayResponse:
    """Safely replay one historical packaged hook execution."""
    del current_user
    try:
        payload = await ExtensionHookReplayService(db).replay_execution(
            execution_id=execution_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    payload["replayed_at"] = _serialize_utc_timestamp(payload["replayed_at"])
    return ExtensionHookReplayResponse(**payload)


@router.post(
    "/extensions/installations",
    response_model=ExtensionInstallationResponse,
)
async def install_extension(
    body: ExtensionInstallRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExtensionInstallationResponse:
    """Install one extension folder into the workspace registry."""
    service = ExtensionService(db)
    try:
        installation = service.install_from_path(
            source_dir=body.source_dir,
            installed_by=current_user.username,
            trust_confirmed=body.trust_confirmed,
            overwrite_confirmed=body.overwrite_confirmed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize_installation(installation, service=service)


@router.post(
    "/extensions/installations/import/bundle/preview",
    response_model=ExtensionImportPreviewResponse,
)
async def preview_bundle_extension(
    files: list[UploadFile] = File(...),
    relative_paths: list[str] = Form(...),
    bundle_name: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExtensionImportPreviewResponse:
    """Preview one local extension bundle before the operator trusts it."""
    del current_user
    if len(files) != len(relative_paths):
        raise HTTPException(
            status_code=400,
            detail="Uploaded files and relative paths must have the same length.",
        )

    bundle_files = [
        ExtensionBundleImportFile(
            relative_path=relative_paths[index],
            content=await upload.read(),
        )
        for index, upload in enumerate(files)
    ]
    service = ExtensionService(db)
    try:
        preview = service.preview_bundle(
            bundle_name=bundle_name,
            files=bundle_files,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize_preview(preview)


@router.post(
    "/extensions/installations/import/bundle",
    response_model=ExtensionInstallationResponse,
)
async def import_bundle_extension(
    files: list[UploadFile] = File(...),
    relative_paths: list[str] = Form(...),
    bundle_name: str = Form(...),
    trust_confirmed: bool = Form(False),
    overwrite_confirmed: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExtensionInstallationResponse:
    """Install one extension bundle uploaded from the local machine."""
    if len(files) != len(relative_paths):
        raise HTTPException(
            status_code=400,
            detail="Uploaded files and relative paths must have the same length.",
        )

    bundle_files = [
        ExtensionBundleImportFile(
            relative_path=relative_paths[index],
            content=await upload.read(),
        )
        for index, upload in enumerate(files)
    ]

    service = ExtensionService(db)
    try:
        installation = service.install_bundle(
            bundle_name=bundle_name,
            files=bundle_files,
            installed_by=current_user.username,
            trust_confirmed=trust_confirmed,
            overwrite_confirmed=overwrite_confirmed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize_installation(installation, service=service)


@router.put(
    "/extensions/installations/{installation_id}/status",
    response_model=ExtensionInstallationResponse,
)
async def update_extension_installation_status(
    installation_id: int,
    body: ExtensionInstallationStatusRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExtensionInstallationResponse:
    """Enable or disable one installed extension version."""
    del current_user
    service = ExtensionService(db)
    try:
        installation = service.set_installation_status(
            installation_id=installation_id,
            status=body.status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize_installation(installation, service=service)


@router.get(
    "/extensions/installations/{installation_id}/references",
    response_model=ExtensionReferenceSummaryResponse,
)
async def get_extension_installation_references(
    installation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExtensionReferenceSummaryResponse:
    """Return persisted references that still rely on one extension version."""
    del current_user
    service = ExtensionService(db)
    try:
        summary = service.get_reference_summary(installation_id=installation_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize_reference_summary(summary.to_dict())


@router.delete(
    "/extensions/installations/{installation_id}",
    response_model=ExtensionUninstallResponse,
)
async def uninstall_extension(
    installation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExtensionUninstallResponse:
    """Uninstall one extension version with logical fallback when referenced."""
    del current_user
    service = ExtensionService(db)
    try:
        result = service.uninstall_installation(installation_id=installation_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    installation = result.get("installation")
    return ExtensionUninstallResponse(
        mode=str(result.get("mode", "")),
        references=_serialize_reference_summary(
            result.get("references", {})
            if isinstance(result.get("references"), dict)
            else {}
        ),
        installation=(
            _serialize_installation(installation, service=service)
            if isinstance(installation, ExtensionInstallation)
            else None
        ),
    )


@router.get(
    "/agents/{agent_id}/extensions",
    response_model=list[AgentExtensionBindingResponse],
)
async def list_agent_extensions(
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[AgentExtensionBindingResponse]:
    """List every configured extension binding for one agent."""
    del current_user
    AgentService(db).get_required_agent(agent_id)
    service = ExtensionService(db)
    statement = (
        select(AgentExtensionBinding, ExtensionInstallation)
        .join(
            ExtensionInstallation,
            col(AgentExtensionBinding.extension_installation_id)
            == col(ExtensionInstallation.id),
        )
        .where(AgentExtensionBinding.agent_id == agent_id)
        .order_by(col(AgentExtensionBinding.priority).asc())
    )
    return [
        _serialize_binding(binding, installation, service=service)
        for binding, installation in db.exec(statement).all()
    ]


@router.get(
    "/agents/{agent_id}/extensions/packages",
    response_model=list[AgentExtensionPackageResponse],
)
async def list_agent_extension_packages(
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[AgentExtensionPackageResponse]:
    """List extension packages with agent-specific version selection state."""
    del current_user
    AgentService(db).get_required_agent(agent_id)
    service = ExtensionService(db)
    return [
        _serialize_agent_package(item, service=service)
        for item in service.list_agent_package_choices(agent_id)
    ]


@router.put(
    "/agents/{agent_id}/extensions",
    response_model=list[AgentExtensionBindingResponse],
)
async def replace_agent_extension_bindings(
    agent_id: int,
    body: AgentExtensionBindingBatchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[AgentExtensionBindingResponse]:
    """Replace the full extension binding set for one agent."""
    del current_user
    AgentService(db).get_required_agent(agent_id)
    service = ExtensionService(db)
    try:
        bindings = service.replace_agent_bindings(
            agent_id=agent_id,
            bindings=[
                {
                    "extension_installation_id": item.extension_installation_id,
                    "enabled": item.enabled,
                    "priority": item.priority,
                    "config": item.config,
                }
                for item in body.bindings
            ],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not bindings:
        return []

    installations = {
        installation.id or 0: installation
        for installation in db.exec(
            select(ExtensionInstallation).where(
                col(ExtensionInstallation.id).in_(
                    [binding.extension_installation_id for binding in bindings]
                )
            )
        ).all()
    }
    return [
        _serialize_binding(
            binding,
            installations[binding.extension_installation_id],
            service=service,
        )
        for binding in bindings
        if binding.extension_installation_id in installations
    ]


@router.put(
    "/agents/{agent_id}/extensions/{extension_installation_id}",
    response_model=AgentExtensionBindingResponse,
)
async def upsert_agent_extension_binding(
    agent_id: int,
    extension_installation_id: int,
    body: AgentExtensionBindingRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AgentExtensionBindingResponse:
    """Create or update one agent-extension binding."""
    del current_user
    AgentService(db).get_required_agent(agent_id)
    service = ExtensionService(db)
    try:
        binding = service.upsert_agent_binding(
            agent_id=agent_id,
            extension_installation_id=extension_installation_id,
            enabled=body.enabled,
            priority=body.priority,
            config=body.config,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    installation = db.get(ExtensionInstallation, binding.extension_installation_id)
    if installation is None:
        raise HTTPException(status_code=404, detail="Installed extension not found")
    return _serialize_binding(binding, installation, service=service)


@router.delete(
    "/agents/{agent_id}/extensions/{extension_installation_id}",
    status_code=204,
)
async def delete_agent_extension_binding(
    agent_id: int,
    extension_installation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Delete one agent-extension binding."""
    del current_user
    AgentService(db).get_required_agent(agent_id)
    service = ExtensionService(db)
    try:
        service.delete_agent_binding(
            agent_id=agent_id,
            extension_installation_id=extension_installation_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)
