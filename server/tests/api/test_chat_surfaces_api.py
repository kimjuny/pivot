"""API tests for development chat surface session and file endpoints."""

from __future__ import annotations

import base64
import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import import_module
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from websockets.sync.server import serve

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

import_module("app.models")
SessionModel = import_module("app.models.session").Session
User = import_module("app.models.user").User
auth_module = import_module("app.api.auth")
chat_surfaces_api_module = import_module("app.api.chat_surfaces")
dependencies_module = import_module("app.api.dependencies")
surface_session_service_module = import_module("app.services.surface_session_service")
workspace_service_module = import_module("app.services.workspace_service")
WorkspaceService = workspace_service_module.WorkspaceService
SurfaceSessionService = surface_session_service_module.SurfaceSessionService
PreviewEndpointService = import_module(
    "app.services.preview_endpoint_service"
).PreviewEndpointService
ExtensionInstallation = import_module("app.models.extension").ExtensionInstallation
AgentExtensionBinding = import_module("app.models.extension").AgentExtensionBinding
extension_service_module = import_module("app.services.extension_service")
LocalFilesystemPOSIXWorkspaceProvider = import_module(
    "app.storage.providers.local_fs"
).LocalFilesystemPOSIXWorkspaceProvider


class ChatSurfacesApiTestCase(unittest.TestCase):
    """Verify development chat surface session and workspace file flows."""

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
        self.workspace_root = Path(self.tmpdir.name) / "workspace"
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        resolved_profile = type(
            "ResolvedProfile",
            (),
            {
                "posix_workspace": LocalFilesystemPOSIXWorkspaceProvider(
                    self.workspace_root
                ),
            },
        )()

        self.workspace_profile_patch = patch.object(
            cast(Any, workspace_service_module),
            "get_resolved_storage_profile",
            return_value=resolved_profile,
        )
        self.workspace_profile_patch.start()

        self.user = User(username="alice", password_hash="hash")
        self.session.add(self.user)
        self.session.commit()
        self.session.refresh(self.user)

        self.workspace = WorkspaceService(self.session).create_workspace(
            agent_id=7,
            username="alice",
            scope="session_private",
            session_id="session-1",
        )
        self.session.add(
            SessionModel(
                session_id="session-1",
                agent_id=7,
                user="alice",
                workspace_id=self.workspace.workspace_id,
                chat_history='{"version": 1, "messages": []}',
                react_llm_messages="[]",
                react_llm_cache_state="{}",
            )
        )
        self.session.commit()

        self.app = FastAPI()
        self.app.include_router(chat_surfaces_api_module.router, prefix="/api")
        self.app.dependency_overrides[dependencies_module.get_db] = self._get_db
        self.app.dependency_overrides[auth_module.get_current_user] = (
            self._get_current_user
        )
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        """Release temporary resources and clear dev session state."""
        self.client.close()
        self.app.dependency_overrides.clear()
        SurfaceSessionService.clear_dev_surface_sessions()
        PreviewEndpointService.clear_preview_endpoints()
        self.workspace_profile_patch.stop()
        self.session.close()
        self.tmpdir.cleanup()

    def _get_db(self):
        """Yield the shared database session for the test API app."""
        yield self.session

    def _get_current_user(self) -> Any:
        """Return the authenticated test user for protected endpoints."""
        return self.user

    def test_create_dev_surface_session_returns_bootstrap(self) -> None:
        """Dev surface creation should return a bootstrap payload bound to the workspace."""
        response = self.client.post(
            "/api/chat-surfaces/dev-sessions",
            json={
                "session_id": "session-1",
                "surface_key": "workspace-editor",
                "dev_server_url": "http://127.0.0.1:5173",
            },
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["surface_key"], "workspace-editor")
        self.assertEqual(payload["session_id"], "session-1")
        self.assertEqual(payload["workspace_id"], self.workspace.workspace_id)
        self.assertIn("users/alice/agents/7", payload["workspace_logical_root"])
        self.assertIsInstance(payload["surface_token"], str)
        self.assertEqual(
            payload["bootstrap"]["surface_token"], payload["surface_token"]
        )
        self.assertEqual(
            payload["bootstrap"]["workspace_logical_root"],
            payload["workspace_logical_root"],
        )
        self.assertEqual(
            payload["bootstrap"]["files_api"]["directory_url"],
            f"/api/chat-surfaces/dev-sessions/{payload['surface_session_id']}/files/directory",
        )
        self.assertEqual(
            payload["bootstrap"]["files_api"]["text_url"],
            f"/api/chat-surfaces/dev-sessions/{payload['surface_session_id']}/files/text",
        )
        self.assertEqual(
            payload["bootstrap"]["files_api"]["blob_url"],
            f"/api/chat-surfaces/dev-sessions/{payload['surface_session_id']}/files/blob",
        )
        self.assertEqual(
            payload["bootstrap"]["files_api"]["tree_url"],
            f"/api/chat-surfaces/dev-sessions/{payload['surface_session_id']}/files/tree",
        )

    def test_create_preview_endpoint_returns_proxy_url(self) -> None:
        """Preview creation should return a stable session-scoped proxy URL."""
        with patch.object(
            chat_surfaces_api_module.PreviewEndpointService,
            "connect_preview_endpoint",
            side_effect=lambda *, preview_id, username: PreviewEndpointService(
                self.session
            ).get_preview_endpoint(preview_id=preview_id, username=username),
        ):
            response = self.client.post(
                "/api/chat-previews",
                json={
                    "session_id": "session-1",
                    "preview_name": "App Preview",
                    "start_server": "bash /workspace/.pivot/previews/app-preview.sh",
                    "cwd": "/workspace/apps/site",
                    "port": 3000,
                    "path": "/app",
                },
            )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["session_id"], "session-1")
        self.assertEqual(payload["port"], 3000)
        self.assertEqual(payload["path"], "/app")
        self.assertEqual(payload["title"], "App Preview")
        self.assertTrue(payload["has_launch_recipe"])
        self.assertEqual(
            payload["proxy_url"],
            f"/api/chat-previews/{payload['preview_id']}/proxy/app",
        )
        self.assertIn("users/alice/agents/7", payload["workspace_logical_root"])

    def test_list_preview_endpoints_returns_session_registry(self) -> None:
        """Listing previews should return the current session registry in creation order."""
        service = PreviewEndpointService(self.session)
        first = service.create_preview_endpoint(
            username="alice",
            session_id="session-1",
            port=3000,
            path="/",
            title="First Preview",
            cwd="/workspace/apps/first",
            start_server="bash /workspace/.pivot/previews/first.sh",
        )
        second = service.create_preview_endpoint(
            username="alice",
            session_id="session-1",
            port=3001,
            path="/docs",
            title="Second Preview",
            cwd="/workspace/apps/second",
            start_server="bash /workspace/.pivot/previews/second.sh",
        )

        response = self.client.get(
            "/api/chat-previews",
            params={"session_id": "session-1"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            [item["preview_id"] for item in payload],
            [first.preview_id, second.preview_id],
        )
        self.assertEqual(payload[0]["title"], "First Preview")
        self.assertEqual(payload[1]["title"], "Second Preview")
        self.assertTrue(payload[0]["has_launch_recipe"])
        self.assertTrue(payload[1]["has_launch_recipe"])

    def test_reconnect_surface_preview_returns_registry_payload(self) -> None:
        """Surface reconnect should return the refreshed preview plus registry."""
        create_surface_response = self.client.post(
            "/api/chat-surfaces/dev-sessions",
            json={
                "session_id": "session-1",
                "surface_key": "workspace-editor",
                "dev_server_url": "http://127.0.0.1:4173",
            },
        )
        self.assertEqual(create_surface_response.status_code, 201)
        surface_payload = create_surface_response.json()

        preview_record = PreviewEndpointService(self.session).create_preview_endpoint(
            username="alice",
            session_id="session-1",
            port=3000,
            path="/",
            title="App Preview",
            cwd="/workspace/apps/site",
            start_server="bash /workspace/.pivot/previews/app-preview.sh",
            skills=[{"name": "alpha", "location": "/workspace/skills/alpha"}],
        )

        with patch.object(
            chat_surfaces_api_module.PreviewEndpointService,
            "connect_preview_endpoint",
            return_value=preview_record,
        ):
            reconnect_response = self.client.post(
                "/api/chat-surfaces/sessions/"
                f"{surface_payload['surface_session_id']}/previews/{preview_record.preview_id}/connect"
                f"?surface_token={surface_payload['surface_token']}"
            )

        self.assertEqual(reconnect_response.status_code, 200)
        payload = reconnect_response.json()
        self.assertEqual(payload["preview"]["preview_id"], preview_record.preview_id)
        self.assertTrue(payload["preview"]["has_launch_recipe"])
        self.assertEqual(payload["active_preview_id"], preview_record.preview_id)
        self.assertEqual(len(payload["available_previews"]), 1)

    def test_generic_workspace_file_contract_supports_directory_text_and_blob_flows(
        self,
    ) -> None:
        """Surface sessions should expose reusable directory/text/blob file endpoints."""
        create_surface_response = self.client.post(
            "/api/chat-surfaces/dev-sessions",
            json={
                "session_id": "session-1",
                "surface_key": "workspace-editor",
                "dev_server_url": "http://127.0.0.1:4173",
            },
        )
        self.assertEqual(create_surface_response.status_code, 201)
        surface_payload = create_surface_response.json()
        session_id = surface_payload["surface_session_id"]
        surface_token = surface_payload["surface_token"]

        write_text_response = self.client.put(
            f"/api/chat-surfaces/dev-sessions/{session_id}/files/text",
            params={"surface_token": surface_token},
            json={
                "path": ".pivot/apps/canvas/scene.json",
                "content": '{"version":1,"scene":{"nodes":[]}}',
            },
        )
        self.assertEqual(write_text_response.status_code, 204)

        directory_response = self.client.get(
            f"/api/chat-surfaces/dev-sessions/{session_id}/files/directory",
            params={
                "surface_token": surface_token,
                "path": ".pivot/apps/canvas",
            },
        )
        self.assertEqual(directory_response.status_code, 200)
        self.assertEqual(
            [
                (item["path"], item["kind"])
                for item in directory_response.json()["entries"]
            ],
            [(".pivot/apps/canvas/scene.json", "file")],
        )

        read_text_response = self.client.get(
            f"/api/chat-surfaces/dev-sessions/{session_id}/files/text",
            params={
                "surface_token": surface_token,
                "path": ".pivot/apps/canvas/scene.json",
            },
        )
        self.assertEqual(read_text_response.status_code, 200)
        self.assertEqual(
            read_text_response.json()["content"],
            '{"version":1,"scene":{"nodes":[]}}',
        )

        image_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7ZxV0AAAAASUVORK5CYII="
        )
        write_blob_response = self.client.post(
            f"/api/chat-surfaces/dev-sessions/{session_id}/files/blob",
            params={"surface_token": surface_token},
            data={"path": ".pivot/apps/canvas/assets/example.png"},
            files={"file": ("example.png", image_bytes, "image/png")},
        )
        self.assertEqual(write_blob_response.status_code, 201)
        self.assertEqual(write_blob_response.json()["mime_type"], "image/png")

        read_blob_response = self.client.get(
            f"/api/chat-surfaces/dev-sessions/{session_id}/files/blob",
            params={
                "surface_token": surface_token,
                "path": ".pivot/apps/canvas/assets/example.png",
            },
        )
        self.assertEqual(read_blob_response.status_code, 200)
        self.assertEqual(read_blob_response.content, image_bytes)
        self.assertEqual(read_blob_response.headers["content-type"], "image/png")

    def test_reconnect_surface_preview_can_restore_recipe_from_earlier_session(
        self,
    ) -> None:
        """Surface reconnect should copy a historical preview recipe into the active session."""
        second_workspace = WorkspaceService(self.session).create_workspace(
            agent_id=7,
            username="alice",
            scope="session_private",
            session_id="session-2",
        )
        self.session.add(
            SessionModel(
                session_id="session-2",
                agent_id=7,
                user="alice",
                workspace_id=second_workspace.workspace_id,
                chat_history='{"version": 1, "messages": []}',
                react_llm_messages="[]",
                react_llm_cache_state="{}",
            )
        )
        self.session.commit()

        create_surface_response = self.client.post(
            "/api/chat-surfaces/dev-sessions",
            json={
                "session_id": "session-2",
                "surface_key": "workspace-editor",
                "dev_server_url": "http://127.0.0.1:4173",
            },
        )
        self.assertEqual(create_surface_response.status_code, 201)
        surface_payload = create_surface_response.json()

        historical_preview = PreviewEndpointService(
            self.session
        ).create_preview_endpoint(
            username="alice",
            session_id="session-1",
            port=3000,
            path="/",
            title="Historical Preview",
            cwd="/workspace/apps/site",
            start_server="bash /workspace/.pivot/previews/app-preview.sh",
            skills=[{"name": "alpha", "location": "/workspace/skills/alpha"}],
        )

        with patch.object(
            chat_surfaces_api_module.PreviewEndpointService,
            "connect_preview_endpoint",
            side_effect=lambda *, preview_id, username: PreviewEndpointService(
                self.session
            ).get_preview_endpoint(preview_id=preview_id, username=username),
        ):
            reconnect_response = self.client.post(
                "/api/chat-surfaces/sessions/"
                f"{surface_payload['surface_session_id']}/previews/{historical_preview.preview_id}/connect"
                f"?surface_token={surface_payload['surface_token']}"
            )

        self.assertEqual(reconnect_response.status_code, 200)
        payload = reconnect_response.json()
        self.assertEqual(payload["preview"]["session_id"], "session-2")
        self.assertEqual(
            payload["preview"]["workspace_id"], second_workspace.workspace_id
        )
        self.assertTrue(payload["preview"]["has_launch_recipe"])
        self.assertEqual(payload["active_preview_id"], payload["preview"]["preview_id"])
        self.assertEqual(len(payload["available_previews"]), 1)

    def test_create_installed_surface_session_serves_packaged_runtime(self) -> None:
        """Installed surfaces should create a packaged runtime session and serve HTML."""
        extension_root = Path(self.tmpdir.name) / "installed-surface"
        runtime_dir = extension_root / "ui" / "workspace"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        (runtime_dir / "index.html").write_text(
            (
                "<!doctype html><html><head><title>Workspace</title></head>"
                "<body><div id='root'></div><script type='module' src='./main.js'></script></body></html>"
            ),
            encoding="utf-8",
        )
        (runtime_dir / "main.js").write_text(
            "console.log('installed workspace editor');",
            encoding="utf-8",
        )

        installation = ExtensionInstallation(
            scope="acme",
            name="workspace-tools",
            version="0.1.0",
            display_name="Workspace Tools",
            description="Installed workspace tools",
            manifest_json=json.dumps(
                {
                    "scope": "acme",
                    "name": "workspace-tools",
                    "version": "0.1.0",
                    "display_name": "Workspace Tools",
                    "description": "Installed workspace tools",
                    "contributions": {
                        "chat_surfaces": [
                            {
                                "key": "workspace-editor",
                                "display_name": "Workspace Editor",
                                "entrypoint": "ui/workspace/index.html",
                            }
                        ]
                    },
                }
            ),
            manifest_hash="manifest-hash",
            artifact_storage_backend="local_fs",
            artifact_key="extensions/acme/workspace-tools/0.1.0/artifact/test.tar.gz",
            artifact_digest="digest",
            artifact_size_bytes=1,
            install_root=str(extension_root),
            status="active",
        )
        self.session.add(installation)
        self.session.commit()
        self.session.refresh(installation)
        self.session.add(
            AgentExtensionBinding(
                agent_id=7,
                extension_installation_id=installation.id,
                enabled=True,
                priority=100,
            )
        )
        self.session.commit()

        with patch.object(
            extension_service_module.ExtensionService,
            "_ensure_materialized_installation_root",
            return_value=extension_root,
        ):
            create_response = self.client.post(
                "/api/chat-surfaces/installed-sessions",
                json={
                    "session_id": "session-1",
                    "extension_installation_id": installation.id,
                    "surface_key": "workspace-editor",
                },
            )

            self.assertEqual(create_response.status_code, 201)
            payload = create_response.json()
            self.assertEqual(payload["package_id"], "@acme/workspace-tools")
            self.assertEqual(
                payload["runtime_url"],
                (
                    "/api/chat-surfaces/installed-sessions/"
                    f"{payload['surface_session_id']}/runtime/ui/workspace/"
                ),
            )

            runtime_response = self.client.get(
                payload["runtime_url"],
                params={
                    "surface_token": payload["surface_token"],
                    "theme_preference": "system",
                    "resolved_theme": "light",
                },
            )
            self.assertEqual(runtime_response.status_code, 200)
            self.assertIn("window.__PIVOT_SURFACE_BOOTSTRAP__", runtime_response.text)
            self.assertIn("Workspace Editor", runtime_response.text)
            self.assertIn('"resolved": "light"', runtime_response.text)

            asset_response = self.client.get(
                (
                    "/api/chat-surfaces/installed-sessions/"
                    f"{payload['surface_session_id']}/runtime/ui/workspace/main.js"
                ),
                params={"surface_token": payload["surface_token"]},
            )
            self.assertEqual(asset_response.status_code, 200)
            self.assertIn("installed workspace editor", asset_response.text)

    def test_loopback_dev_surface_targets_include_container_host_aliases(self) -> None:
        """Loopback dev URLs should gain container-reachable fallback targets."""
        candidates = chat_surfaces_api_module._build_upstream_target_candidates(
            base_url="http://127.0.0.1:4173",
            proxy_path="",
            query_string="",
        )

        self.assertEqual(candidates[0].url, "http://127.0.0.1:4173")
        self.assertEqual(candidates[0].host_header, "127.0.0.1:4173")
        self.assertIn(
            "http://host.containers.internal:4173",
            [candidate.url for candidate in candidates],
        )
        self.assertIn(
            "http://host.docker.internal:4173",
            [candidate.url for candidate in candidates],
        )

    def test_loopback_hmr_targets_preserve_original_host_header(self) -> None:
        """Loopback HMR targets should retain the original host for Vite checks."""
        candidates = chat_surfaces_api_module._build_upstream_hmr_target_candidates(
            dev_server_url="http://localhost:5173"
        )

        self.assertEqual(candidates[0].url, "ws://localhost:5173/")
        self.assertEqual(candidates[0].host_header, "localhost:5173")
        self.assertIn(
            "ws://host.containers.internal:5173/",
            [candidate.url for candidate in candidates],
        )

    def test_dev_surface_can_list_read_and_write_workspace_files(self) -> None:
        """Surface-scoped file endpoints should expose a minimal edit loop."""
        workspace_path = WorkspaceService(self.session).get_workspace_path(
            self.workspace
        )
        source_dir = workspace_path / "src"
        source_dir.mkdir(parents=True, exist_ok=True)
        (source_dir / "App.tsx").write_text(
            "export const App = () => <div>hello</div>;\n",
            encoding="utf-8",
        )

        create_response = self.client.post(
            "/api/chat-surfaces/dev-sessions",
            json={
                "session_id": "session-1",
                "surface_key": "workspace-editor",
                "dev_server_url": "http://localhost:5173",
            },
        )
        self.assertEqual(create_response.status_code, 201)
        create_payload = create_response.json()
        surface_session_id = create_payload["surface_session_id"]
        surface_token = create_payload["surface_token"]

        tree_response = self.client.get(
            f"/api/chat-surfaces/dev-sessions/{surface_session_id}/files/tree",
            params={"surface_token": surface_token},
        )
        self.assertEqual(tree_response.status_code, 200)
        self.assertEqual(
            [
                (entry["path"], entry["kind"])
                for entry in tree_response.json()["entries"]
            ],
            [("src", "directory"), ("src/App.tsx", "file")],
        )

        read_response = self.client.get(
            f"/api/chat-surfaces/dev-sessions/{surface_session_id}/files/content",
            params={"path": "src/App.tsx", "surface_token": surface_token},
        )
        self.assertEqual(read_response.status_code, 200)
        self.assertIn("hello", read_response.json()["content"])

        write_response = self.client.put(
            f"/api/chat-surfaces/dev-sessions/{surface_session_id}/files/content",
            params={"surface_token": surface_token},
            json={
                "path": "src/App.tsx",
                "content": "export const App = () => <div>updated</div>;\n",
            },
        )
        self.assertEqual(write_response.status_code, 204)
        self.assertEqual(
            (source_dir / "App.tsx").read_text(encoding="utf-8"),
            "export const App = () => <div>updated</div>;\n",
        )

    def test_dev_surface_can_read_previewable_image_files(self) -> None:
        """Surface file reads should return image payloads for common image formats."""
        workspace_path = WorkspaceService(self.session).get_workspace_path(
            self.workspace
        )
        image_dir = workspace_path / "assets"
        image_dir.mkdir(parents=True, exist_ok=True)
        image_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7ZxV0AAAAASUVORK5CYII="
        )
        (image_dir / "preview.png").write_bytes(image_bytes)

        create_response = self.client.post(
            "/api/chat-surfaces/dev-sessions",
            json={
                "session_id": "session-1",
                "surface_key": "workspace-editor",
                "dev_server_url": "http://localhost:5173",
            },
        )
        self.assertEqual(create_response.status_code, 201)
        create_payload = create_response.json()

        read_response = self.client.get(
            f"/api/chat-surfaces/dev-sessions/{create_payload['surface_session_id']}/files/content",
            params={
                "path": "assets/preview.png",
                "surface_token": create_payload["surface_token"],
            },
        )
        self.assertEqual(read_response.status_code, 200)
        payload = read_response.json()
        self.assertEqual(payload["kind"], "image")
        self.assertEqual(payload["mime_type"], "image/png")
        self.assertEqual(
            payload["data_base64"],
            base64.b64encode(image_bytes).decode("ascii"),
        )

    def test_preview_proxy_uses_surface_token_and_rewrites_root_assets(self) -> None:
        """Preview proxy should accept surface auth and keep root assets under proxy."""
        create_surface_response = self.client.post(
            "/api/chat-surfaces/dev-sessions",
            json={
                "session_id": "session-1",
                "surface_key": "workspace-editor",
                "dev_server_url": "http://127.0.0.1:4173",
            },
        )
        self.assertEqual(create_surface_response.status_code, 201)
        surface_payload = create_surface_response.json()

        with patch.object(
            chat_surfaces_api_module.PreviewEndpointService,
            "connect_preview_endpoint",
            side_effect=lambda *, preview_id, username: PreviewEndpointService(
                self.session
            ).get_preview_endpoint(preview_id=preview_id, username=username),
        ):
            create_preview_response = self.client.post(
                "/api/chat-previews",
                json={
                    "session_id": "session-1",
                    "preview_name": "App Preview",
                    "start_server": "bash /workspace/.pivot/previews/app-preview.sh",
                    "cwd": "/workspace/apps/site",
                    "port": 3000,
                    "path": "/",
                },
            )
        self.assertEqual(create_preview_response.status_code, 201)
        preview_payload = create_preview_response.json()
        preview_id = preview_payload["preview_id"]

        class _SandboxProxyResult:
            def __init__(
                self,
                *,
                status_code: int,
                body: bytes,
                content_type: str,
                headers: dict[str, str] | None = None,
            ) -> None:
                self.status_code = status_code
                self.body = body
                self.content_type = content_type
                self.headers = headers or {"Content-Type": content_type}

        class _StubSandboxService:
            def proxy_http(self, **kwargs: Any) -> _SandboxProxyResult:
                path = kwargs["path"]
                if path == "/":
                    return _SandboxProxyResult(
                        status_code=200,
                        content_type="text/html; charset=utf-8",
                        body=(
                            b"<!doctype html><html><head>"
                            b"<script type='module' src='/src/main.js'></script>"
                            b"</head><body>Preview</body></html>"
                        ),
                    )
                if path == "/src/main.js":
                    return _SandboxProxyResult(
                        status_code=200,
                        content_type="application/javascript",
                        body=b'import "/src/deps.js"; console.log("preview");',
                    )
                return _SandboxProxyResult(
                    status_code=404,
                    content_type="text/plain; charset=utf-8",
                    body=b"missing",
                )

        with patch.object(
            chat_surfaces_api_module,
            "get_sandbox_service",
            return_value=_StubSandboxService(),
        ):
            html_response = self.client.get(
                f"/api/chat-previews/{preview_id}/proxy/",
                params={"surface_token": surface_payload["surface_token"]},
            )
            self.assertEqual(html_response.status_code, 200)
            self.assertIn(
                f"/api/chat-previews/{preview_id}/proxy/src/main.js",
                html_response.text,
            )
            self.assertIn("window.__PIVOT_PREVIEW_WS_BASE__", html_response.text)
            self.assertIn("rewriteRootUrl", html_response.text)
            self.assertIn("HTMLImageElement", html_response.text)
            self.assertIn(
                f"/api/chat-previews/{preview_id}/ws/",
                html_response.text,
            )
            self.assertIn(
                "pivot_surface_access",
                html_response.headers.get("set-cookie", ""),
            )

            js_response = self.client.get(
                f"/api/chat-previews/{preview_id}/proxy/src/main.js",
                params={"surface_token": surface_payload["surface_token"]},
            )
            self.assertEqual(js_response.status_code, 200)
            self.assertIn(
                f"/api/chat-previews/{preview_id}/proxy/src/deps.js",
                js_response.text,
            )

    def test_preview_websocket_tunnel_forwards_frames(self) -> None:
        """Preview websocket tunnel should relay browser frames through manager."""
        create_surface_response = self.client.post(
            "/api/chat-surfaces/dev-sessions",
            json={
                "session_id": "session-1",
                "surface_key": "workspace-editor",
                "dev_server_url": "http://127.0.0.1:4173",
            },
        )
        self.assertEqual(create_surface_response.status_code, 201)
        surface_payload = create_surface_response.json()

        with patch.object(
            chat_surfaces_api_module.PreviewEndpointService,
            "connect_preview_endpoint",
            side_effect=lambda *, preview_id, username: PreviewEndpointService(
                self.session
            ).get_preview_endpoint(preview_id=preview_id, username=username),
        ):
            create_preview_response = self.client.post(
                "/api/chat-previews",
                json={
                    "session_id": "session-1",
                    "preview_name": "Socket Preview",
                    "start_server": "bash /workspace/.pivot/previews/socket-preview.sh",
                    "cwd": "/workspace/apps/site",
                    "port": 3000,
                    "path": "/socket",
                },
            )
        self.assertEqual(create_preview_response.status_code, 201)
        preview_payload = create_preview_response.json()
        preview_id = preview_payload["preview_id"]

        observed_init: dict[str, Any] = {}

        class _StubSandboxService:
            def build_websocket_proxy_url(self) -> str:
                return f"ws://127.0.0.1:{manager_server.port}"

            def build_websocket_proxy_headers(self) -> dict[str, str]:
                return {"X-Sandbox-Token": "test-token"}

        class _ManagerEchoServer:
            def __init__(self) -> None:
                self.ready = threading.Event()
                self.server: Any | None = None
                self.port = 0
                self.thread = threading.Thread(target=self._run, daemon=True)

            def start(self) -> None:
                self.thread.start()
                self.ready.wait(timeout=5)

            def _run(self) -> None:
                def handler(websocket: Any) -> None:
                    observed_init.update(json.loads(websocket.recv()))
                    websocket.send(
                        json.dumps(
                            {
                                "type": "ready",
                                "accepted_subprotocol": None,
                            }
                        )
                    )
                    for message in websocket:
                        if isinstance(message, bytes):
                            websocket.send(message)
                        else:
                            websocket.send(f"echo:{message}")

                with serve(
                    handler,
                    "127.0.0.1",
                    0,
                    ping_interval=None,
                ) as server:
                    self.server = server
                    self.port = server.socket.getsockname()[1]
                    self.ready.set()
                    server.serve_forever()

            def stop(self) -> None:
                if self.server is None:
                    return
                self.server.shutdown()
                self.thread.join(timeout=5)

        manager_server = _ManagerEchoServer()
        manager_server.start()

        try:
            with (
                patch.object(
                    chat_surfaces_api_module,
                    "get_sandbox_service",
                    return_value=_StubSandboxService(),
                ),
                self.client.websocket_connect(
                    f"/api/chat-previews/{preview_id}/ws/socket"
                    f"?surface_token={surface_payload['surface_token']}"
                ) as websocket,
            ):
                websocket.send_text("ping")
                self.assertEqual(websocket.receive_text(), "echo:ping")

            self.assertEqual(observed_init["workspace_id"], self.workspace.workspace_id)
            self.assertEqual(observed_init["port"], 3000)
            self.assertEqual(observed_init["path"], "/socket")
        finally:
            manager_server.stop()

    def test_preview_http_proxy_reuses_registered_skill_mounts(self) -> None:
        """Preview HTTP proxy should forward the skill snapshot stored on creation."""
        create_surface_response = self.client.post(
            "/api/chat-surfaces/dev-sessions",
            json={
                "session_id": "session-1",
                "surface_key": "workspace-editor",
                "dev_server_url": "http://127.0.0.1:4173",
            },
        )
        self.assertEqual(create_surface_response.status_code, 201)
        surface_payload = create_surface_response.json()

        preview_record = PreviewEndpointService(self.session).create_preview_endpoint(
            username="alice",
            session_id="session-1",
            port=3000,
            path="/",
            title="App Preview",
            skills=(
                {
                    "name": "ui-kit",
                    "location": "/app/server/.pivot/skills/ui-kit",
                },
            ),
        )

        observed_kwargs: dict[str, Any] = {}

        class _SandboxProxyResult:
            def __init__(
                self,
                *,
                status_code: int,
                body: bytes,
                content_type: str,
                headers: dict[str, str] | None = None,
            ) -> None:
                self.status_code = status_code
                self.body = body
                self.content_type = content_type
                self.headers = headers or {"Content-Type": content_type}

        class _StubSandboxService:
            def proxy_http(self, **kwargs: Any) -> _SandboxProxyResult:
                observed_kwargs.update(kwargs)
                return _SandboxProxyResult(
                    status_code=200,
                    content_type="text/html; charset=utf-8",
                    body=b"<!doctype html><html><body>Preview</body></html>",
                )

        with patch.object(
            chat_surfaces_api_module,
            "get_sandbox_service",
            return_value=_StubSandboxService(),
        ):
            response = self.client.get(
                f"/api/chat-previews/{preview_record.preview_id}/proxy/",
                params={"surface_token": surface_payload["surface_token"]},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            observed_kwargs["skills"],
            [{"name": "ui-kit", "location": "/app/server/.pivot/skills/ui-kit"}],
        )
        self.assertTrue(observed_kwargs["require_existing"])
        self.assertFalse(observed_kwargs["allow_recreate"])

    def test_preview_websocket_tunnel_reuses_registered_skill_mounts(self) -> None:
        """Preview websocket init should forward the stored preview skill snapshot."""
        create_surface_response = self.client.post(
            "/api/chat-surfaces/dev-sessions",
            json={
                "session_id": "session-1",
                "surface_key": "workspace-editor",
                "dev_server_url": "http://127.0.0.1:4173",
            },
        )
        self.assertEqual(create_surface_response.status_code, 201)
        surface_payload = create_surface_response.json()

        preview_record = PreviewEndpointService(self.session).create_preview_endpoint(
            username="alice",
            session_id="session-1",
            port=3000,
            path="/socket",
            title="Socket Preview",
            skills=(
                {
                    "name": "ui-kit",
                    "location": "/app/server/.pivot/skills/ui-kit",
                },
            ),
        )

        observed_init: dict[str, Any] = {}

        class _StubSandboxService:
            def build_websocket_proxy_url(self) -> str:
                return f"ws://127.0.0.1:{manager_server.port}"

            def build_websocket_proxy_headers(self) -> dict[str, str]:
                return {"X-Sandbox-Token": "test-token"}

        class _ManagerEchoServer:
            def __init__(self) -> None:
                self.ready = threading.Event()
                self.server: Any | None = None
                self.port = 0
                self.thread = threading.Thread(target=self._run, daemon=True)

            def start(self) -> None:
                self.thread.start()
                self.ready.wait(timeout=5)

            def _run(self) -> None:
                def handler(websocket: Any) -> None:
                    observed_init.update(json.loads(websocket.recv()))
                    websocket.send(
                        json.dumps(
                            {
                                "type": "ready",
                                "accepted_subprotocol": None,
                            }
                        )
                    )
                    for message in websocket:
                        if isinstance(message, bytes):
                            websocket.send(message)
                        else:
                            websocket.send(f"echo:{message}")

                with serve(
                    handler,
                    "127.0.0.1",
                    0,
                    ping_interval=None,
                ) as server:
                    self.server = server
                    self.port = server.socket.getsockname()[1]
                    self.ready.set()
                    server.serve_forever()

            def stop(self) -> None:
                if self.server is None:
                    return
                self.server.shutdown()
                self.thread.join(timeout=5)

        manager_server = _ManagerEchoServer()
        manager_server.start()

        try:
            with (
                patch.object(
                    chat_surfaces_api_module,
                    "get_sandbox_service",
                    return_value=_StubSandboxService(),
                ),
                self.client.websocket_connect(
                    f"/api/chat-previews/{preview_record.preview_id}/ws/socket"
                    f"?surface_token={surface_payload['surface_token']}"
                ) as websocket,
            ):
                websocket.send_text("ping")
                self.assertEqual(websocket.receive_text(), "echo:ping")

            self.assertEqual(
                observed_init["skills"],
                [{"name": "ui-kit", "location": "/app/server/.pivot/skills/ui-kit"}],
            )
            self.assertTrue(observed_init["require_existing"])
            self.assertFalse(observed_init["allow_recreate"])
        finally:
            manager_server.stop()

    def test_dev_surface_proxy_injects_bootstrap_into_html(self) -> None:
        """Proxying the local dev server should inject the bootstrap payload into HTML."""

        class _SurfaceDevHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/":
                    body = (
                        b"<!doctype html><html><head><title>Surface</title></head>"
                        b"<body><div id='root'></div></body></html>"
                    )
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(404)
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                del format, args

        server = ThreadingHTTPServer(("127.0.0.1", 0), _SurfaceDevHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            create_response = self.client.post(
                "/api/chat-surfaces/dev-sessions",
                json={
                    "session_id": "session-1",
                    "surface_key": "workspace-editor",
                    "dev_server_url": f"http://127.0.0.1:{server.server_port}",
                },
            )
            self.assertEqual(create_response.status_code, 201)
            create_payload = create_response.json()
            surface_session_id = create_payload["surface_session_id"]
            surface_token = create_payload["surface_token"]

            proxy_response = self.client.get(
                f"/api/chat-surfaces/dev-sessions/{surface_session_id}/proxy",
                params={"surface_token": surface_token},
            )

            self.assertEqual(proxy_response.status_code, 200)
            self.assertIn("window.__PIVOT_SURFACE_BOOTSTRAP__", proxy_response.text)
            self.assertIn(
                "pivot_surface_access", proxy_response.headers.get("set-cookie", "")
            )
            self.assertIn("workspace-editor", proxy_response.text)
            self.assertIn("<div id='root'></div>", proxy_response.text)
        finally:
            server.shutdown()
            server.server_close()

    def test_dev_surface_proxy_supports_entry_html_urls(self) -> None:
        """Proxying should preserve concrete entry-page URLs for sibling assets."""

        class _EntryHtmlHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/sample/index.html":
                    body = (
                        b"<!doctype html><html><head><title>Sample</title></head>"
                        b"<body><script type='module' src='./main.js'></script></body></html>"
                    )
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if self.path == "/sample/main.js":
                    body = b"console.log('workspace-editor');"
                    self.send_response(200)
                    self.send_header("Content-Type", "application/javascript")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(404)
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                del format, args

        server = ThreadingHTTPServer(("127.0.0.1", 0), _EntryHtmlHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            create_response = self.client.post(
                "/api/chat-surfaces/dev-sessions",
                json={
                    "session_id": "session-1",
                    "surface_key": "workspace-editor",
                    "dev_server_url": (
                        f"http://127.0.0.1:{server.server_port}/sample/index.html"
                    ),
                },
            )
            self.assertEqual(create_response.status_code, 201)
            create_payload = create_response.json()
            surface_session_id = create_payload["surface_session_id"]
            surface_token = create_payload["surface_token"]

            proxy_html_response = self.client.get(
                f"/api/chat-surfaces/dev-sessions/{surface_session_id}/proxy/",
                params={"surface_token": surface_token},
            )
            self.assertEqual(proxy_html_response.status_code, 200)
            self.assertIn(
                "window.__PIVOT_SURFACE_BOOTSTRAP__", proxy_html_response.text
            )
            self.assertIn(
                "window.__PIVOT_SURFACE_PROXY_BASE__", proxy_html_response.text
            )

            proxy_asset_response = self.client.get(
                f"/api/chat-surfaces/dev-sessions/{surface_session_id}/proxy/main.js"
            )
            self.assertEqual(proxy_asset_response.status_code, 200)
            self.assertIn("workspace-editor", proxy_asset_response.text)
        finally:
            server.shutdown()
            server.server_close()

    def test_dev_surface_proxy_rewrites_vite_root_asset_urls(self) -> None:
        """Proxying should keep Vite root-relative assets under the proxy prefix."""

        class _ViteHtmlHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/":
                    body = (
                        b"<!doctype html><html><head>"
                        b"<script type='module' src='/@vite/client'></script>"
                        b"</head><body>"
                        b"<script type='module' src='/src/main.tsx'></script>"
                        b"</body></html>"
                    )
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(404)
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                del format, args

        server = ThreadingHTTPServer(("127.0.0.1", 0), _ViteHtmlHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            create_response = self.client.post(
                "/api/chat-surfaces/dev-sessions",
                json={
                    "session_id": "session-1",
                    "surface_key": "workspace-editor",
                    "dev_server_url": f"http://127.0.0.1:{server.server_port}",
                },
            )
            self.assertEqual(create_response.status_code, 201)
            create_payload = create_response.json()
            surface_session_id = create_payload["surface_session_id"]
            surface_token = create_payload["surface_token"]
            proxy_base = f"/api/chat-surfaces/dev-sessions/{surface_session_id}/proxy/"

            proxy_html_response = self.client.get(
                f"/api/chat-surfaces/dev-sessions/{surface_session_id}/proxy/",
                params={"surface_token": surface_token},
            )

            self.assertEqual(proxy_html_response.status_code, 200)
            self.assertIn(f"src='{proxy_base}@vite/client'", proxy_html_response.text)
            self.assertIn(f"src='{proxy_base}src/main.tsx'", proxy_html_response.text)
        finally:
            server.shutdown()
            server.server_close()

    def test_dev_surface_proxy_rewrites_vite_client_hmr_target(self) -> None:
        """Proxying should retarget Vite's websocket client through Pivot."""

        class _ViteClientHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/@vite/client":
                    body = (
                        b"const importMetaUrl = new URL(import.meta.url);\n"
                        b"const socketHost = `${__HMR_HOSTNAME__ || importMetaUrl.hostname}:${hmrPort || importMetaUrl.port}${__HMR_BASE__}`;\n"
                        b"const directSocketHost = __HMR_DIRECT_TARGET__;\n"
                    )
                    self.send_response(200)
                    self.send_header("Content-Type", "application/javascript")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(404)
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                del format, args

        server = ThreadingHTTPServer(("127.0.0.1", 0), _ViteClientHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            create_response = self.client.post(
                "/api/chat-surfaces/dev-sessions",
                json={
                    "session_id": "session-1",
                    "surface_key": "workspace-editor",
                    "dev_server_url": f"http://127.0.0.1:{server.server_port}",
                },
            )
            self.assertEqual(create_response.status_code, 201)
            create_payload = create_response.json()
            surface_session_id = create_payload["surface_session_id"]
            surface_token = create_payload["surface_token"]

            client_response = self.client.get(
                f"/api/chat-surfaces/dev-sessions/{surface_session_id}/proxy/@vite/client",
                params={"surface_token": surface_token},
            )

            self.assertEqual(client_response.status_code, 200)
            self.assertIn(
                (
                    "const socketHost = "
                    f"`${{importMetaUrl.host}}/api/chat-surfaces/dev-sessions/{surface_session_id}/hmr`;"
                ),
                client_response.text,
            )
            self.assertIn("const directSocketHost = socketHost;", client_response.text)
        finally:
            server.shutdown()
            server.server_close()

    def test_dev_surface_proxy_rewrites_root_relative_js_module_specifiers(
        self,
    ) -> None:
        """Proxying should keep JS module imports under the surface proxy prefix."""

        class _ViteModuleHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/src/main.js":
                    body = (
                        b'import "/src/styles.css?t=123";\n'
                        b'import "/@fs/Users/example/project/sdk.js?t=456";\n'
                    )
                    self.send_response(200)
                    self.send_header("Content-Type", "application/javascript")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(404)
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                del format, args

        server = ThreadingHTTPServer(("127.0.0.1", 0), _ViteModuleHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            create_response = self.client.post(
                "/api/chat-surfaces/dev-sessions",
                json={
                    "session_id": "session-1",
                    "surface_key": "workspace-editor",
                    "dev_server_url": f"http://127.0.0.1:{server.server_port}",
                },
            )
            self.assertEqual(create_response.status_code, 201)
            create_payload = create_response.json()
            surface_session_id = create_payload["surface_session_id"]
            surface_token = create_payload["surface_token"]

            module_response = self.client.get(
                f"/api/chat-surfaces/dev-sessions/{surface_session_id}/proxy/src/main.js",
                params={"surface_token": surface_token},
            )

            self.assertEqual(module_response.status_code, 200)
            self.assertIn(
                f"/api/chat-surfaces/dev-sessions/{surface_session_id}/proxy/src/styles.css?t=123",
                module_response.text,
            )
            self.assertIn(
                f"/api/chat-surfaces/dev-sessions/{surface_session_id}/proxy/@fs/Users/example/project/sdk.js?t=456",
                module_response.text,
            )
        finally:
            server.shutdown()
            server.server_close()

    def test_dev_surface_hmr_tunnel_forwards_websocket_frames(self) -> None:
        """The HMR websocket tunnel should relay browser frames to the dev server."""

        class _EchoHmrServer:
            def __init__(self) -> None:
                self.ready = threading.Event()
                self.server: Any | None = None
                self.port = 0
                self.thread = threading.Thread(target=self._run, daemon=True)

            def start(self) -> None:
                self.thread.start()
                self.ready.wait(timeout=5)

            def _run(self) -> None:
                def handler(websocket: Any) -> None:
                    for message in websocket:
                        if isinstance(message, bytes):
                            websocket.send(message)
                        else:
                            websocket.send(f"echo:{message}")

                with serve(
                    handler,
                    "127.0.0.1",
                    0,
                    ping_interval=None,
                ) as server:
                    self.server = server
                    self.port = server.socket.getsockname()[1]
                    self.ready.set()
                    server.serve_forever()

            def stop(self) -> None:
                if self.server is None:
                    return
                self.server.shutdown()
                self.thread.join(timeout=5)

        hmr_server = _EchoHmrServer()
        hmr_server.start()

        try:
            create_response = self.client.post(
                "/api/chat-surfaces/dev-sessions",
                json={
                    "session_id": "session-1",
                    "surface_key": "workspace-editor",
                    "dev_server_url": f"http://127.0.0.1:{hmr_server.port}",
                },
            )
            self.assertEqual(create_response.status_code, 201)
            create_payload = create_response.json()
            surface_session_id = create_payload["surface_session_id"]
            surface_token = create_payload["surface_token"]

            with self.client.websocket_connect(
                f"/api/chat-surfaces/dev-sessions/{surface_session_id}/hmr"
                f"?surface_token={surface_token}"
            ) as websocket:
                websocket.send_text("ping")
                self.assertEqual(websocket.receive_text(), "echo:ping")
        finally:
            hmr_server.stop()

    def test_surface_cookie_allows_follow_up_requests_without_repeating_token(
        self,
    ) -> None:
        """Initial proxy bootstrap should scope a cookie for later surface requests."""
        workspace_path = WorkspaceService(self.session).get_workspace_path(
            self.workspace
        )
        workspace_path.mkdir(parents=True, exist_ok=True)
        (workspace_path / "notes.txt").write_text("hello surface\n", encoding="utf-8")

        class _SurfaceDevHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                body = b"<!doctype html><html><body>ok</body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                del format, args

        server = ThreadingHTTPServer(("127.0.0.1", 0), _SurfaceDevHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            create_response = self.client.post(
                "/api/chat-surfaces/dev-sessions",
                json={
                    "session_id": "session-1",
                    "surface_key": "workspace-editor",
                    "dev_server_url": f"http://127.0.0.1:{server.server_port}",
                },
            )
            self.assertEqual(create_response.status_code, 201)
            create_payload = create_response.json()
            surface_session_id = create_payload["surface_session_id"]
            surface_token = create_payload["surface_token"]

            bootstrap_response = self.client.get(
                f"/api/chat-surfaces/dev-sessions/{surface_session_id}/proxy/",
                params={"surface_token": surface_token},
            )
            self.assertEqual(bootstrap_response.status_code, 200)

            tree_response = self.client.get(
                f"/api/chat-surfaces/dev-sessions/{surface_session_id}/files/tree"
            )
            self.assertEqual(tree_response.status_code, 200)
            self.assertEqual(
                [
                    (entry["path"], entry["kind"])
                    for entry in tree_response.json()["entries"]
                ],
                [("notes.txt", "file")],
            )
        finally:
            server.shutdown()
            server.server_close()
