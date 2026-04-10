"""API tests for extension bundle import and agent binding flows."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

if TYPE_CHECKING:
    from collections.abc import Generator

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

import_module("app.models")
Agent = import_module("app.models.agent").Agent
User = import_module("app.models.user").User
auth_module = import_module("app.api.auth")
dependencies_module = import_module("app.api.dependencies")
extensions_api_module = import_module("app.api.extensions")
hook_execution_service_module = import_module(
    "app.services.extension_hook_execution_service"
)
extension_service_module = import_module("app.services.extension_service")
artifact_storage_service_module = import_module("app.services.artifact_storage_service")
workspace_service = import_module("app.services.workspace_service")
ExtensionHookExecutionService = (
    hook_execution_service_module.ExtensionHookExecutionService
)
LocalFilesystemObjectStorageProvider = import_module(
    "app.storage.providers.local_fs"
).LocalFilesystemObjectStorageProvider


class ExtensionsApiTestCase(unittest.TestCase):
    """Verify extension API flows for local bundle import and agent binding."""

    def setUp(self) -> None:
        """Create one isolated app, database, and workspace root."""
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)

        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.workspace_root = self.root / "workspace"
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.external_workspace_root = self.root / "external-posix"
        self.external_workspace_root.mkdir(parents=True, exist_ok=True)
        self.runtime_cache_root = self.root / "runtime-cache"
        self.runtime_cache_root.mkdir(parents=True, exist_ok=True)
        self.object_storage_root = self.root / "object-storage"
        self.object_storage_root.mkdir(parents=True, exist_ok=True)

        self.workspace_patch = patch.object(
            workspace_service,
            "workspace_root",
            return_value=self.workspace_root,
        )
        self.artifact_workspace_patch = patch.object(
            artifact_storage_service_module,
            "workspace_root",
            return_value=self.workspace_root,
        )
        self.workspace_patch.start()
        self.artifact_workspace_patch.start()

        self.agent = Agent(
            name="api-agent",
            llm_id=1,
            active_release_id=None,
        )
        self.user = User(username="alice", password_hash="hash")
        self.session.add(self.agent)
        self.session.add(self.user)
        self.session.commit()
        self.session.refresh(self.agent)
        self.session.refresh(self.user)

        self.app = FastAPI()
        self.app.include_router(extensions_api_module.router, prefix="/api")
        self.app.dependency_overrides[dependencies_module.get_db] = self._get_db
        self.app.dependency_overrides[auth_module.get_current_user] = (
            self._get_current_user
        )
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        """Release test resources and dependency overrides."""
        self.client.close()
        self.app.dependency_overrides.clear()
        self.workspace_patch.stop()
        self.artifact_workspace_patch.stop()
        self.session.close()
        self.tmpdir.cleanup()

    def _get_db(self) -> Generator[Session, None, None]:
        """Yield the shared test database session used by the API app."""
        yield self.session

    def _get_current_user(self) -> Any:
        """Return the authenticated test user for protected endpoints."""
        return self.user

    def _sample_extension_root(self) -> Path:
        """Create one local provider extension used across bundle API tests."""
        extension_root = self.root / "acme-providers"
        provider_dir = extension_root / "web_search_providers" / "acme_search"
        provider_dir.mkdir(parents=True, exist_ok=True)

        manifest = {
            "schema_version": 1,
            "scope": "acme",
            "name": "providers",
            "display_name": "ACME Providers",
            "version": "1.0.0",
            "description": "Sample provider extension for API tests.",
            "contributions": {
                "web_search_providers": [
                    {
                        "entrypoint": (
                            "web_search_providers/acme_search/provider.py"
                        ),
                    }
                ]
            },
        }

        (extension_root / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (provider_dir / "provider.py").write_text(
            (
                "from app.orchestration.web_search.base import BaseWebSearchProvider\n"
                "from app.orchestration.web_search.types import (\n"
                "    WebSearchExecutionResult,\n"
                "    WebSearchProviderBinding,\n"
                "    WebSearchProviderManifest,\n"
                "    WebSearchQueryRequest,\n"
                "    WebSearchTestResult,\n"
                ")\n\n"
                "class SampleSearchProvider(BaseWebSearchProvider):\n"
                "    manifest = WebSearchProviderManifest(\n"
                '        key="acme@search",\n'
                '        name="ACME Search",\n'
                '        description="Search provider for API tests.",\n'
                '        docs_url="https://example.com/search",\n'
                "        auth_schema=[],\n"
                "        config_schema=[],\n"
                '        setup_steps=["Save the extension to enable the sample provider."],\n'
                '        supported_parameters=["query"],\n'
                "    )\n\n"
                "    def _search_with_binding(\n"
                "        self,\n"
                "        *,\n"
                "        request: WebSearchQueryRequest,\n"
                "        api_key: str,\n"
                "        runtime_config: dict[str, object],\n"
                "    ) -> WebSearchExecutionResult:\n"
                "        del api_key, runtime_config\n"
                "        return WebSearchExecutionResult(\n"
                "            provider={'key': self.manifest.key, 'name': self.manifest.name},\n"
                "            query=request.query,\n"
                "            results=[],\n"
                "            provider_request={'query': request.query},\n"
                "        )\n\n"
                "    def test_connection(\n"
                "        self,\n"
                "        *,\n"
                "        auth_config: dict[str, object],\n"
                "        runtime_config: dict[str, object],\n"
                "    ) -> WebSearchTestResult:\n"
                "        del auth_config, runtime_config\n"
                "        return WebSearchTestResult(\n"
                "            ok=True,\n"
                "            status='ok',\n"
                "            message='Sample search provider is healthy.',\n"
                "        )\n\n"
                "PROVIDER = SampleSearchProvider()\n"
            ),
            encoding="utf-8",
        )
        return extension_root

    def _write_hook_extension(self) -> Path:
        """Create one minimal local extension that contributes a lifecycle hook."""
        extension_root = self.root / "acme-hooks"
        (extension_root / "hooks").mkdir(parents=True, exist_ok=True)
        manifest = {
            "schema_version": 1,
            "scope": "acme",
            "name": "hooks",
            "display_name": "ACME Hooks",
            "version": "1.0.0",
            "description": "Sample hook extension for API replay tests.",
            "configuration": {
                "installation": {
                    "fields": [
                        {
                            "key": "base_url",
                            "type": "string",
                            "label": "Base URL",
                            "required": True,
                            "default": "http://localhost:8080",
                        }
                    ]
                },
                "binding": {
                    "fields": [
                        {
                            "key": "namespace",
                            "type": "string",
                            "default": "default",
                        }
                    ]
                },
            },
            "contributions": {
                "hooks": [
                    {
                        "name": "Recall Memory Context",
                        "description": "Loads relevant memory before task execution begins.",
                        "event": "task.before_start",
                        "callable": "handle_task_event",
                        "mode": "sync",
                        "entrypoint": "hooks/lifecycle.py",
                    }
                ]
            },
        }
        (extension_root / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (extension_root / "hooks" / "lifecycle.py").write_text(
            (
                "def handle_task_event(context: dict[str, object]) -> list[dict[str, object]]:\n"
                "    return [\n"
                "        {\n"
                '            "type": "emit_event",\n'
                '            "payload": {\n'
                '                "type": "observe",\n'
                '                "data": {\n'
                '                    "task_id": context.get("task_id"),\n'
                "                },\n"
                "            },\n"
                "        }\n"
                "    ]\n"
            ),
            encoding="utf-8",
        )
        return extension_root

    def _build_bundle_upload(
        self,
        extension_root: Path,
        *,
        bundle_name: str,
        trust_confirmed: bool | None = None,
    ) -> tuple[
        list[tuple[str, tuple[str, bytes, str]]],
        dict[str, str | list[str]],
    ]:
        """Return one multipart payload split into files plus form fields."""
        relative_paths: list[str] = []
        data: dict[str, str | list[str]] = {"bundle_name": bundle_name}
        if trust_confirmed is not None:
            data["trust_confirmed"] = "true" if trust_confirmed else "false"

        files: list[tuple[str, tuple[str, bytes, str]]] = []

        for file_path in sorted(
            path for path in extension_root.rglob("*") if path.is_file()
        ):
            relative_path = file_path.relative_to(extension_root).as_posix()
            files.append(
                (
                    "files",
                    (
                        file_path.name,
                        file_path.read_bytes(),
                        "application/octet-stream",
                    ),
                )
            )
            relative_paths.append(f"{bundle_name}/{relative_path}")

        data["relative_paths"] = relative_paths

        return files, data

    def test_preview_and_import_bundle_endpoints(self) -> None:
        """Bundle preview and import should expose trust and artifact metadata."""
        preview_files, preview_data = self._build_bundle_upload(
            self._sample_extension_root(),
            bundle_name="acme-providers",
        )

        preview_response = self.client.post(
            "/api/extensions/installations/import/bundle/preview",
            files=preview_files,
            data=preview_data,
        )
        self.assertEqual(preview_response.status_code, 200)
        preview_payload = preview_response.json()
        self.assertEqual(preview_payload["package_id"], "@acme/providers")
        self.assertEqual(preview_payload["trust_status"], "unverified")
        self.assertEqual(
            preview_payload["contribution_summary"]["web_search_providers"],
            ["acme@search"],
        )
        self.assertEqual(preview_payload["contribution_summary"]["hooks"], [])

        install_files, install_data = self._build_bundle_upload(
            self._sample_extension_root(),
            bundle_name="acme-providers",
            trust_confirmed=True,
        )
        install_response = self.client.post(
            "/api/extensions/installations/import/bundle",
            files=install_files,
            data=install_data,
        )
        self.assertEqual(install_response.status_code, 200)
        installation_payload = install_response.json()
        self.assertEqual(installation_payload["package_id"], "@acme/providers")
        self.assertEqual(installation_payload["trust_status"], "trusted_local")
        self.assertEqual(
            installation_payload["artifact_storage_backend"],
            artifact_storage_service_module.get_resolved_storage_profile()
            .object_storage.backend_name,
        )
        self.assertTrue(installation_payload["artifact_key"].endswith(".tar.gz"))
        self.assertGreater(installation_payload["artifact_size_bytes"], 0)
        self.assertTrue(installation_payload["created_at"].endswith("+00:00"))
        self.assertTrue(installation_payload["updated_at"].endswith("+00:00"))
        self.assertEqual(installation_payload["contribution_summary"]["hooks"], [])

        hook_install_files, hook_install_data = self._build_bundle_upload(
            self._write_hook_extension(),
            bundle_name="acme-hooks",
            trust_confirmed=True,
        )
        hook_install_response = self.client.post(
            "/api/extensions/installations/import/bundle",
            files=hook_install_files,
            data=hook_install_data,
        )
        self.assertEqual(hook_install_response.status_code, 200)
        self.assertEqual(
            hook_install_response.json()["contribution_summary"]["hooks"],
            ["Recall Memory Context"],
        )

    def test_import_bundle_keeps_runtime_cache_outside_external_workspace_root(
        self,
    ) -> None:
        """External workspaces must not receive extracted extension runtime files."""
        external_profile = type(
            "ResolvedProfile",
            (),
            {
                "object_storage": LocalFilesystemObjectStorageProvider(
                    self.object_storage_root
                ),
            },
        )()

        install_files, install_data = self._build_bundle_upload(
            self._sample_extension_root(),
            bundle_name="acme-providers",
            trust_confirmed=True,
        )

        with (
            patch.object(
                workspace_service,
                "workspace_root",
                return_value=self.external_workspace_root,
            ),
            patch.object(
                artifact_storage_service_module,
                "workspace_root",
                return_value=self.external_workspace_root,
            ),
            patch.object(
                extension_service_module,
                "_extensions_root",
                return_value=self.runtime_cache_root / "extensions",
            ),
            patch.object(
                artifact_storage_service_module,
                "get_resolved_storage_profile",
                return_value=external_profile,
            ),
        ):
            install_response = self.client.post(
                "/api/extensions/installations/import/bundle",
                files=install_files,
                data=install_data,
            )

        self.assertEqual(install_response.status_code, 200)
        installation_payload = install_response.json()

        install_root = Path(installation_payload["install_root"])
        artifact_path = self.object_storage_root / Path(
            installation_payload["artifact_key"]
        )

        self.assertTrue(install_root.joinpath("manifest.json").is_file())
        self.assertTrue(install_root.is_relative_to(self.runtime_cache_root))
        self.assertFalse(install_root.is_relative_to(self.external_workspace_root))
        self.assertTrue(artifact_path.is_file())
        self.assertTrue(artifact_path.is_relative_to(self.object_storage_root))
        self.assertFalse(artifact_path.is_relative_to(self.external_workspace_root))

    def test_hook_contributions_are_exposed_in_preview_and_install_payloads(
        self,
    ) -> None:
        """Hook packages should expose lifecycle contributions in preview and install APIs."""
        extension_root = self._write_hook_extension()
        preview_files, preview_data = self._build_bundle_upload(
            extension_root,
            bundle_name="acme-hooks",
            trust_confirmed=False,
        )
        preview_response = self.client.post(
            "/api/extensions/installations/import/bundle/preview",
            files=preview_files,
            data=preview_data,
        )

        self.assertEqual(preview_response.status_code, 200)
        self.assertEqual(
            preview_response.json()["contribution_summary"]["hooks"],
            ["Recall Memory Context"],
        )
        self.assertEqual(
            preview_response.json()["contribution_items"][0],
            {
                "type": "hook",
                "name": "Recall Memory Context",
                "description": "Loads relevant memory before task execution begins.",
            },
        )

        install_files, install_data = self._build_bundle_upload(
            extension_root,
            bundle_name="acme-hooks",
            trust_confirmed=True,
        )
        install_response = self.client.post(
            "/api/extensions/installations/import/bundle",
            files=install_files,
            data=install_data,
        )

        self.assertEqual(install_response.status_code, 200)
        self.assertEqual(
            install_response.json()["contribution_summary"]["hooks"],
            ["Recall Memory Context"],
        )
        self.assertEqual(
            install_response.json()["contribution_items"][0],
            {
                "type": "hook",
                "name": "Recall Memory Context",
                "description": "Loads relevant memory before task execution begins.",
            },
        )

    def test_extension_logo_endpoints_expose_installation_and_package_logo_urls(
        self,
    ) -> None:
        """Extension APIs should expose one stable logo URL when a package ships a logo."""
        extension_root = self._write_hook_extension()
        (extension_root / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        install_files, install_data = self._build_bundle_upload(
            extension_root,
            bundle_name="acme-hooks",
            trust_confirmed=True,
        )

        install_response = self.client.post(
            "/api/extensions/installations/import/bundle",
            files=install_files,
            data=install_data,
        )

        self.assertEqual(install_response.status_code, 200)
        installation_payload = install_response.json()
        installation_id = int(installation_payload["id"])
        expected_logo_url = (
            f"/api/extensions/installations/{installation_id}/logo"
            f"?v={installation_payload['artifact_digest']}"
        )
        self.assertEqual(
            installation_payload["logo_url"],
            expected_logo_url,
        )

        packages_response = self.client.get("/api/extensions/packages")
        self.assertEqual(packages_response.status_code, 200)
        packages_payload = packages_response.json()
        self.assertEqual(len(packages_payload), 1)
        self.assertEqual(
            packages_payload[0]["logo_url"],
            expected_logo_url,
        )

        logo_response = self.client.get(
            f"/api/extensions/installations/{installation_id}/logo"
        )
        self.assertEqual(logo_response.status_code, 200)
        self.assertEqual(logo_response.headers["content-type"], "image/png")
        self.assertEqual(logo_response.content, b"\x89PNG\r\n\x1a\n")

        del self.app.dependency_overrides[auth_module.get_current_user]
        unauthenticated_logo_response = self.client.get(
            f"/api/extensions/installations/{installation_id}/logo"
        )
        self.assertEqual(unauthenticated_logo_response.status_code, 200)
        self.assertEqual(unauthenticated_logo_response.content, b"\x89PNG\r\n\x1a\n")
        self.app.dependency_overrides[auth_module.get_current_user] = (
            self._get_current_user
        )

    def test_extension_logo_endpoint_returns_webp_media_type(self) -> None:
        """The logo endpoint should preserve explicit webp assets for browsers."""
        extension_root = self._write_hook_extension()
        (extension_root / "logo.webp").write_bytes(b"RIFFtestWEBP")
        install_files, install_data = self._build_bundle_upload(
            extension_root,
            bundle_name="acme-hooks",
            trust_confirmed=True,
        )

        install_response = self.client.post(
            "/api/extensions/installations/import/bundle",
            files=install_files,
            data=install_data,
        )

        self.assertEqual(install_response.status_code, 200)
        installation_id = int(install_response.json()["id"])
        logo_response = self.client.get(
            f"/api/extensions/installations/{installation_id}/logo"
        )

        self.assertEqual(logo_response.status_code, 200)
        self.assertEqual(logo_response.headers["content-type"], "image/webp")
        self.assertEqual(logo_response.content, b"RIFFtestWEBP")

    def test_installation_configuration_endpoints(self) -> None:
        """Configuration endpoints should expose schema and persist values."""
        extension_root = self._write_hook_extension()
        install_files, install_data = self._build_bundle_upload(
            extension_root,
            bundle_name="acme-hooks",
            trust_confirmed=True,
        )
        install_response = self.client.post(
            "/api/extensions/installations/import/bundle",
            files=install_files,
            data=install_data,
        )
        self.assertEqual(install_response.status_code, 200)
        installation_id = int(install_response.json()["id"])

        state_response = self.client.get(
            f"/api/extensions/installations/{installation_id}/configuration"
        )
        self.assertEqual(state_response.status_code, 200)
        state_payload = state_response.json()
        self.assertEqual(state_payload["config"], {"base_url": "http://localhost:8080"})
        self.assertEqual(
            state_payload["configuration_schema"]["installation"]["fields"][0]["key"],
            "base_url",
        )
        update_response = self.client.put(
            f"/api/extensions/installations/{installation_id}/configuration",
            json={"config": {"base_url": "http://mem0.local"}},
        )
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(
            update_response.json()["config"],
            {"base_url": "http://mem0.local"},
        )

    def test_agent_extension_binding_api_flow(self) -> None:
        """Agent extension endpoints should expose selection state after binding."""
        install_files, install_data = self._build_bundle_upload(
            self._sample_extension_root(),
            bundle_name="acme-providers",
            trust_confirmed=True,
        )
        install_response = self.client.post(
            "/api/extensions/installations/import/bundle",
            files=install_files,
            data=install_data,
        )
        self.assertEqual(install_response.status_code, 200)
        installation_payload = install_response.json()
        installation_id = int(installation_payload["id"])

        bind_response = self.client.put(
            f"/api/agents/{self.agent.id}/extensions/{installation_id}",
            json={
                "enabled": True,
                "priority": 25,
                "config": {"channel_alias": "support"},
            },
        )
        self.assertEqual(bind_response.status_code, 200)
        binding_payload = bind_response.json()
        self.assertEqual(binding_payload["priority"], 25)
        self.assertEqual(
            binding_payload["installation"]["package_id"], "@acme/providers"
        )

        packages_response = self.client.get(
            f"/api/agents/{self.agent.id}/extensions/packages"
        )
        self.assertEqual(packages_response.status_code, 200)
        packages_payload = packages_response.json()
        self.assertEqual(len(packages_payload), 1)
        self.assertEqual(packages_payload[0]["package_id"], "@acme/providers")
        self.assertFalse(packages_payload[0]["has_update_available"])
        self.assertEqual(
            packages_payload[0]["selected_binding"]["installation"]["id"],
            installation_id,
        )

        delete_response = self.client.delete(
            f"/api/agents/{self.agent.id}/extensions/{installation_id}"
        )
        self.assertEqual(delete_response.status_code, 204)

        list_response = self.client.get(f"/api/agents/{self.agent.id}/extensions")
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.json(), [])

    def test_bundle_import_requires_explicit_trust(self) -> None:
        """Local bundle import should fail until trust is explicitly confirmed."""
        install_files, install_data = self._build_bundle_upload(
            self._sample_extension_root(),
            bundle_name="acme-providers",
        )

        response = self.client.post(
            "/api/extensions/installations/import/bundle",
            files=install_files,
            data=install_data,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(
            "explicitly trusted before installation",
            str(response.json()["detail"]),
        )

    def test_hook_execution_logs_endpoint_returns_filtered_rows(self) -> None:
        """Hook execution API should return append-only logs with task filters."""
        execution_service = ExtensionHookExecutionService(self.session)
        execution_service.create_execution(
            session_id="session-1",
            task_id="task-1",
            trace_id="trace-1",
            iteration=2,
            agent_id=self.agent.id or 0,
            release_id=None,
            extension_package_id="@acme/providers",
            extension_version="1.0.0",
            hook_event="iteration.after_tool_result",
            hook_callable="handle_task_event",
            status="succeeded",
            hook_context_payload={"task_id": "task-1", "event_payload": {}},
            effects_payload=[{"type": "emit_event"}],
            error_payload=None,
            duration_ms=12,
        )
        execution_service.create_execution(
            session_id="session-2",
            task_id="task-2",
            trace_id=None,
            iteration=0,
            agent_id=self.agent.id or 0,
            release_id=None,
            extension_package_id="@acme/other",
            extension_version="1.0.0",
            hook_event="task.before_start",
            hook_callable="handle_task_event",
            status="failed",
            hook_context_payload={"task_id": "task-2", "event_payload": {}},
            effects_payload=None,
            error_payload={"message": "boom"},
            duration_ms=4,
        )

        response = self.client.get(
            "/api/extensions/hook-executions",
            params={"task_id": "task-1"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["task_id"], "task-1")
        self.assertEqual(payload[0]["hook_event"], "iteration.after_tool_result")
        self.assertEqual(payload[0]["extension_package_id"], "@acme/providers")
        self.assertEqual(payload[0]["status"], "succeeded")
        self.assertEqual(payload[0]["hook_context"]["task_id"], "task-1")
        self.assertTrue(payload[0]["started_at"].endswith("+00:00"))
        self.assertTrue(payload[0]["finished_at"].endswith("+00:00"))

    def test_hook_execution_logs_endpoint_filters_by_trace_and_iteration(self) -> None:
        """Hook execution API should support trace-level iteration drill-down."""
        execution_service = ExtensionHookExecutionService(self.session)
        execution_service.create_execution(
            session_id="session-1",
            task_id="task-1",
            trace_id="trace-1",
            iteration=2,
            agent_id=self.agent.id or 0,
            release_id=None,
            extension_package_id="@acme/hooks",
            extension_version="1.0.0",
            hook_event="iteration.after_tool_result",
            hook_callable="handle_task_event",
            status="succeeded",
            hook_context_payload={"task_id": "task-1"},
            effects_payload=[{"type": "emit_event"}],
            error_payload=None,
            duration_ms=9,
        )
        execution_service.create_execution(
            session_id="session-1",
            task_id="task-1",
            trace_id="trace-1",
            iteration=3,
            agent_id=self.agent.id or 0,
            release_id=None,
            extension_package_id="@acme/hooks",
            extension_version="1.0.0",
            hook_event="iteration.after_tool_result",
            hook_callable="handle_task_event",
            status="succeeded",
            hook_context_payload={"task_id": "task-1"},
            effects_payload=[{"type": "emit_event"}],
            error_payload=None,
            duration_ms=11,
        )

        response = self.client.get(
            "/api/extensions/hook-executions",
            params={"session_id": "session-1", "trace_id": "trace-1", "iteration": 2},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["trace_id"], "trace-1")
        self.assertEqual(payload[0]["iteration"], 2)

    def test_replay_hook_execution_endpoint_returns_safe_replay_result(self) -> None:
        """Replay API should rerun one historical hook without mutating live state."""
        extension_root = self._write_hook_extension()
        install_files, install_data = self._build_bundle_upload(
            extension_root,
            bundle_name="acme-hooks",
            trust_confirmed=True,
        )
        install_response = self.client.post(
            "/api/extensions/installations/import/bundle",
            files=install_files,
            data=install_data,
        )
        self.assertEqual(install_response.status_code, 200)
        installation_payload = install_response.json()

        execution_service = ExtensionHookExecutionService(self.session)
        execution = execution_service.create_execution(
            session_id="session-1",
            task_id="task-replay",
            trace_id=None,
            iteration=0,
            agent_id=self.agent.id or 0,
            release_id=None,
            extension_package_id=installation_payload["package_id"],
            extension_version=installation_payload["version"],
            hook_event="task.before_start",
            hook_callable="handle_task_event",
            status="succeeded",
            hook_context_payload={
                "session_id": "session-1",
                "task_id": "task-replay",
                "trace_id": None,
                "iteration": 0,
                "agent_id": self.agent.id or 0,
                "release_id": None,
                "timestamp": "2026-04-02T00:00:00Z",
                "runtime": {"source": "live", "task_status": "pending"},
                "event_payload": {"message": "hello"},
            },
            effects_payload=[],
            error_payload=None,
            duration_ms=1,
        )

        response = self.client.post(
            f"/api/extensions/hook-executions/{execution.id}/replay"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["execution_id"], execution.id)
        self.assertEqual(payload["extension_package_id"], "@acme/hooks")
        self.assertEqual(payload["hook_event"], "task.before_start")
        self.assertEqual(payload["status"], "succeeded")
        self.assertIsInstance(payload["effects"], list)
        self.assertTrue(payload["replayed_at"].endswith("+00:00"))
