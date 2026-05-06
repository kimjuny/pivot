"""Tests for extension package installation and runtime resolution."""

import asyncio
import json
import shutil
import sys
import tempfile
import unittest
from importlib import import_module
from pathlib import Path, PurePosixPath
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine, select

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

import_module("app.models")
Agent = import_module("app.models.agent").Agent
AgentRelease = import_module("app.models.agent_release").AgentRelease
AgentSavedDraft = import_module("app.models.agent_release").AgentSavedDraft
AgentTestSnapshot = import_module("app.models.agent_release").AgentTestSnapshot
AgentWebSearchBinding = import_module("app.models.web_search").AgentWebSearchBinding
AgentExtensionBinding = import_module("app.models.extension").AgentExtensionBinding
ExtensionHookExecution = import_module("app.models.extension").ExtensionHookExecution
User = import_module("app.models.user").User
agent_release_runtime_service = import_module(
    "app.services.agent_release_runtime_service"
)
AgentReleaseRuntimeService = agent_release_runtime_service.AgentReleaseRuntimeService
agent_snapshot_service = import_module("app.services.agent_snapshot_service")
AgentSnapshotService = agent_snapshot_service.AgentSnapshotService
extension_api_module = import_module("app.api.extensions")
ExtensionHookService = import_module(
    "app.services.extension_hook_service"
).ExtensionHookService
ExtensionHookExecutionService = import_module(
    "app.services.extension_hook_execution_service"
).ExtensionHookExecutionService
ExtensionHookEffectService = import_module(
    "app.services.extension_hook_effect_service"
).ExtensionHookEffectService
ExtensionHookReplayService = import_module(
    "app.services.extension_hook_replay_service"
).ExtensionHookReplayService
artifact_storage_service_module = import_module("app.services.artifact_storage_service")
extension_service_module = import_module("app.services.extension_service")
ExtensionBundleImportFile = extension_service_module.ExtensionBundleImportFile
ExtensionService = extension_service_module.ExtensionService
LocalFilesystemObjectStorageProvider = import_module(
    "app.storage.providers.local_fs"
).LocalFilesystemObjectStorageProvider
ChannelService = import_module("app.services.channel_service").ChannelService
skill_service = import_module("app.services.skill_service")
tool_service = import_module("app.services.tool_service")
WebSearchService = import_module("app.services.web_search_service").WebSearchService
WebSearchQueryRequest = import_module(
    "app.orchestration.web_search.types"
).WebSearchQueryRequest
workspace_service = import_module("app.services.workspace_service")


class ExtensionServiceTestCase(unittest.TestCase):
    """Validate phase 1 extension installation and bundle resolution."""

    def setUp(self) -> None:
        """Create an isolated database and temporary workspace roots."""
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)

        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.workspace_root = self.root / "workspace"
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.runtime_cache_root = self.root / "runtime-cache"
        self.runtime_cache_root.mkdir(parents=True, exist_ok=True)
        self.object_storage_root = self.root / "object-storage"
        self.object_storage_root.mkdir(parents=True, exist_ok=True)

        self.workspace_patch = patch.object(
            workspace_service,
            "workspace_root",
            return_value=self.workspace_root,
        )
        self.extension_runtime_cache_patch = patch.object(
            extension_service_module,
            "_extensions_root",
            return_value=self.runtime_cache_root / "extensions",
        )
        self.artifact_storage_profile_patch = patch.object(
            artifact_storage_service_module,
            "get_resolved_storage_profile",
            return_value=type(
                "ResolvedProfile",
                (),
                {
                    "object_storage": LocalFilesystemObjectStorageProvider(
                        self.object_storage_root
                    ),
                },
            )(),
        )
        self.workspace_patch.start()
        self.extension_runtime_cache_patch.start()
        self.artifact_storage_profile_patch.start()

        self.agent = Agent(
            name="ext-agent",
            llm_id=1,
            active_release_id=None,
        )
        self.user = User(username="alice", password_hash="hash", role_id=1)
        self.bob = User(username="bob", password_hash="hash", role_id=1)
        self.session.add(self.agent)
        self.session.add(self.user)
        self.session.add(self.bob)
        self.session.commit()
        self.session.refresh(self.agent)
        self.session.refresh(self.user)
        self.session.refresh(self.bob)

    def tearDown(self) -> None:
        """Release temporary resources after each test."""
        self.workspace_patch.stop()
        self.extension_runtime_cache_patch.stop()
        self.artifact_storage_profile_patch.stop()
        self.session.close()
        self.tmpdir.cleanup()

    def _write_extension(
        self,
        *,
        package_name: str = "acme.crm",
        version: str = "0.1.0",
        tool_name: str = "search_accounts",
        skill_name: str = "crm_research",
        channel_provider_key: str | None = None,
        web_search_provider_key: str | None = None,
        hook_event: str | None = None,
        hook_name: str = "Recall CRM Context",
        hook_description: str = "Restores CRM context before the task starts.",
        hook_behavior: str = "emit_event",
        installation_config_fields: list[dict[str, object]] | None = None,
        binding_config_fields: list[dict[str, object]] | None = None,
        logo_path: str | None = None,
        include_default_logo: bool = False,
        chat_surface_key: str | None = None,
    ) -> Path:
        """Create one local extension folder with a tool and a skill."""
        package_scope, package_basename = self._split_package_name(package_name)
        extension_root = self.root / f"{package_scope}_{package_basename}_{version}"
        (extension_root / "tools").mkdir(parents=True, exist_ok=True)
        skill_dir = extension_root / "skills" / skill_name
        skill_dir.mkdir(parents=True, exist_ok=True)

        manifest = {
            "schema_version": 1,
            "scope": package_scope,
            "name": package_basename,
            "display_name": "ACME CRM",
            "version": version,
            "description": "CRM extension",
            "contributions": {
                "tools": [
                    {
                        "name": tool_name,
                        "entrypoint": f"tools/{tool_name}.py",
                    }
                ],
                "skills": [
                    {
                        "name": skill_name,
                        "path": f"skills/{skill_name}",
                    }
                ],
            },
        }
        if installation_config_fields or binding_config_fields:
            manifest["configuration"] = {
                "installation": {
                    "fields": installation_config_fields or [],
                },
                "binding": {
                    "fields": binding_config_fields or [],
                },
            }
        if logo_path is not None:
            manifest["logo_path"] = logo_path
            relative_logo_path = PurePosixPath(logo_path)
            target_logo_path = extension_root.joinpath(*relative_logo_path.parts)
            target_logo_path.parent.mkdir(parents=True, exist_ok=True)
            target_logo_path.write_bytes(b"\x89PNG\r\n\x1a\n")
        elif include_default_logo:
            (extension_root / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        if channel_provider_key is not None:
            (extension_root / "channel_providers").mkdir(parents=True, exist_ok=True)
            channel_provider_filename = channel_provider_key.replace("@", "_")
            manifest["contributions"].setdefault("channel_providers", []).append(
                {
                    "entrypoint": (f"channel_providers/{channel_provider_filename}.py"),
                }
            )
            (
                extension_root / "channel_providers" / f"{channel_provider_filename}.py"
            ).write_text(
                (
                    "from app.channels.providers import BaseBuiltinProvider\n"
                    "from app.channels.types import (\n"
                    "    ChannelManifest,\n"
                    "    ChannelTestResult,\n"
                    ")\n\n"
                    "class DemoChannelProvider(BaseBuiltinProvider):\n"
                    "    manifest = ChannelManifest(\n"
                    f'        key="{channel_provider_key}",\n'
                    '        name="Demo Channel",\n'
                    '        description="Extension-backed channel provider.",\n'
                    '        icon="message-square",\n'
                    '        docs_url="https://example.com/channel",\n'
                    '        transport_mode="webhook",\n'
                    '        capabilities=["receive_text", "send_text"],\n'
                    "        auth_schema=[],\n"
                    "        config_schema=[],\n"
                    '        setup_steps=["Save the binding to enable the provider."],\n'
                    "    )\n\n"
                    "    def test_connection(\n"
                    "        self,\n"
                    "        auth_config: dict[str, object],\n"
                    "        runtime_config: dict[str, object],\n"
                    "        binding_id: int,\n"
                    "    ) -> ChannelTestResult:\n"
                    "        del auth_config, runtime_config, binding_id\n"
                    "        return ChannelTestResult(\n"
                    "            ok=True,\n"
                    '            status="ok",\n'
                    '            message="Channel extension provider is healthy.",\n'
                    "        )\n\n"
                    "PROVIDER = DemoChannelProvider()\n"
                ),
                encoding="utf-8",
            )

        if web_search_provider_key is not None:
            provider_dir = (
                extension_root
                / "web_search_providers"
                / web_search_provider_key.replace("@", "_")
            )
            provider_dir.mkdir(parents=True, exist_ok=True)
            manifest["contributions"].setdefault("web_search_providers", []).append(
                {
                    "entrypoint": (
                        "web_search_providers/"
                        f"{web_search_provider_key.replace('@', '_')}/provider.py"
                    ),
                }
            )
            (provider_dir / "provider.py").write_text(
                (
                    "from app.orchestration.web_search.base import BaseWebSearchProvider\n"
                    "from app.orchestration.web_search.types import (\n"
                    "    WebSearchExecutionResult,\n"
                    "    WebSearchProviderManifest,\n"
                    "    WebSearchQueryRequest,\n"
                    "    WebSearchTestResult,\n"
                    ")\n\n"
                    "class DemoWebSearchProvider(BaseWebSearchProvider):\n"
                    "    manifest = WebSearchProviderManifest(\n"
                    f'        key="{web_search_provider_key}",\n'
                    '        name="Demo Search",\n'
                    '        description="Extension-backed web search provider.",\n'
                    '        docs_url="https://example.com/search",\n'
                    "        auth_schema=[],\n"
                    "        config_schema=[],\n"
                    '        setup_steps=["Save the binding to enable the provider."],\n'
                    '        supported_parameters=["query", "max_results"],\n'
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
                    "            query=request.query,\n"
                    '            provider={"key": self.manifest.key, "name": self.manifest.name},\n'
                    '            applied_parameters={"max_results": request.max_results},\n'
                    "            results=[],\n"
                    "        )\n\n"
                    "    def get_api_key(self, binding):\n"
                    "        del binding\n"
                    '        return "demo-key"\n\n'
                    "    def test_connection(\n"
                    "        self,\n"
                    "        *,\n"
                    "        auth_config: dict[str, object],\n"
                    "        runtime_config: dict[str, object],\n"
                    "    ) -> WebSearchTestResult:\n"
                    "        del auth_config, runtime_config\n"
                    "        return WebSearchTestResult(\n"
                    "            ok=True,\n"
                    '            status="ok",\n'
                    '            message="Web-search extension provider is healthy.",\n'
                    "        )\n\n"
                    "PROVIDER = DemoWebSearchProvider()\n"
                ),
                encoding="utf-8",
            )
            (provider_dir / "logo.svg").write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"></svg>\n',
                encoding="utf-8",
            )

        if chat_surface_key is not None:
            surface_dir = extension_root / "ui" / chat_surface_key
            surface_dir.mkdir(parents=True, exist_ok=True)
            manifest["contributions"].setdefault("chat_surfaces", []).append(
                {
                    "key": chat_surface_key,
                    "display_name": "Workspace Editor",
                    "description": "A coding workbench surface.",
                    "entrypoint": f"ui/{chat_surface_key}/index.html",
                    "placement": "right_dock",
                    "min_width": 560,
                }
            )
            (surface_dir / "index.html").write_text(
                (
                    "<!doctype html>\n"
                    "<html>\n"
                    "  <body>\n"
                    '    <div id="app">Workspace Editor</div>\n'
                    "  </body>\n"
                    "</html>\n"
                ),
                encoding="utf-8",
            )

        if hook_event is not None:
            (extension_root / "hooks").mkdir(parents=True, exist_ok=True)
            manifest["contributions"].setdefault("hooks", []).append(
                {
                    "name": hook_name,
                    "description": hook_description,
                    "event": hook_event,
                    "callable": "handle_task_event",
                    "mode": "sync",
                    "entrypoint": "hooks/lifecycle.py",
                }
            )
            hook_body = (
                "def handle_task_event(context: dict[str, object]) -> list[dict[str, object]]:\n"
                "    return [\n"
                "        {\n"
                '            "type": "emit_event",\n'
                '            "payload": {\n'
                '                "type": "observe",\n'
                '                "data": {\n'
                '                    "kind": "hook_observe",\n'
                '                    "event": context.get("event_payload", {}),\n'
                "                },\n"
                "            },\n"
                "        }\n"
                "    ]\n"
            )
            if hook_behavior == "raise":
                hook_body = (
                    "def handle_task_event(context: dict[str, object]) -> list[dict[str, object]]:\n"
                    "    del context\n"
                    '    raise RuntimeError("hook boom")\n'
                )
            elif hook_behavior == "append_prompt_block":
                hook_body = (
                    "def handle_task_event(context: dict[str, object]) -> list[dict[str, object]]:\n"
                    "    return [\n"
                    "        {\n"
                    '            "type": "append_prompt_block",\n'
                    '            "payload": {\n'
                    '                "target": "task_bootstrap",\n'
                    '                "position": "head",\n'
                    '                "content": "Remember the latest billing preferences.",\n'
                    "            },\n"
                    "        }\n"
                    "    ]\n"
                )
            elif hook_behavior == "emit_execution_mode":
                hook_body = (
                    "def handle_task_event(context: dict[str, object]) -> list[dict[str, object]]:\n"
                    "    return [\n"
                    "        {\n"
                    '            "type": "emit_event",\n'
                    '            "payload": {\n'
                    '                "type": "observe",\n'
                    '                "data": {\n'
                    '                    "execution_mode": context.get("execution_mode"),\n'
                    "                },\n"
                    "            },\n"
                    "        }\n"
                    "    ]\n"
                )
            elif hook_behavior == "emit_configs":
                hook_body = (
                    "def handle_task_event(context: dict[str, object]) -> list[dict[str, object]]:\n"
                    "    return [\n"
                    "        {\n"
                    '            "type": "emit_event",\n'
                    '            "payload": {\n'
                    '                "type": "observe",\n'
                    '                "data": {\n'
                    '                    "installation_config": context.get("installation_config"),\n'
                    '                    "binding_config": context.get("binding_config"),\n'
                    '                    "user": context.get("user"),\n'
                    "                },\n"
                    "            },\n"
                    "        }\n"
                    "    ]\n"
                )
            (extension_root / "hooks" / "lifecycle.py").write_text(
                hook_body,
                encoding="utf-8",
            )

        (extension_root / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (extension_root / "tools" / f"{tool_name}.py").write_text(
            (
                "from app.orchestration.tool import tool\n\n"
                f"@tool\n"
                f"def {tool_name}(query: str) -> str:\n"
                '    """Search accounts.\n\n'
                "    Args:\n"
                "        query: Search query.\n\n"
                "    Returns:\n"
                "        Echoed query text.\n"
                '    """\n'
                "    return query\n"
            ),
            encoding="utf-8",
        )
        (skill_dir / "SKILL.md").write_text(
            (
                f"---\nname: {skill_name}\ndescription: CRM research skill\n---\n\n"
                f"# {skill_name}\n\nUse CRM playbooks.\n"
            ),
            encoding="utf-8",
        )
        return extension_root

    def _split_package_name(self, package_name: str) -> tuple[str, str]:
        """Convert one test package shorthand into scope and package name parts."""
        if package_name.startswith("@") and "/" in package_name:
            normalized = package_name[1:]
            scope, name = normalized.split("/", 1)
            return scope, name
        if "." in package_name:
            scope, name = package_name.split(".", 1)
            return scope, name
        raise ValueError("Tests must use either scope.name or @scope/name package ids.")

    def _sample_extension_root(self) -> Path:
        """Return the repository sample package used for local import docs."""
        return SERVER_ROOT / "examples" / "extensions" / "acme-providers"

    def _sample_memory_extension_root(self) -> Path:
        """Return the repository sample package used for memory-hook docs."""
        return SERVER_ROOT / "examples" / "extensions" / "acme-memory"

    def test_install_and_bind_extension_flows_into_snapshot_and_runtime(self) -> None:
        """Agent snapshots and live runtime config should include enabled bundles."""
        extension_root = self._write_extension()
        service = ExtensionService(self.session)

        installation = service.install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        binding = service.upsert_agent_binding(
            agent_id=self.agent.id or 0,
            extension_installation_id=installation.id or 0,
            enabled=True,
            priority=10,
            config={"region": "us"},
        )

        self.assertEqual(binding.priority, 10)

        snapshot = AgentSnapshotService(self.session).build_current_snapshot(
            self.agent.id or 0
        )
        self.assertEqual(len(snapshot["extensions"]), 1)
        self.assertEqual(snapshot["extensions"][0]["scope"], "acme")
        self.assertEqual(snapshot["extensions"][0]["name"], "crm")
        self.assertEqual(snapshot["extensions"][0]["package_id"], "@acme/crm")
        self.assertEqual(snapshot["extensions"][0]["trust_status"], "trusted_local")
        self.assertEqual(snapshot["extensions"][0]["trust_source"], "local_import")
        self.assertIsNone(snapshot["extensions"][0]["hub_package_id"])
        self.assertEqual(
            snapshot["extensions"][0]["tools"][0]["name"], "search_accounts"
        )
        self.assertEqual(snapshot["extensions"][0]["skills"][0]["name"], "crm_research")

        runtime_config = AgentReleaseRuntimeService(self.session).resolve_for_agent(
            self.agent.id or 0
        )
        self.assertEqual(len(runtime_config.extension_bundle), 1)
        self.assertEqual(runtime_config.extension_bundle[0]["scope"], "acme")
        self.assertEqual(runtime_config.extension_bundle[0]["name"], "crm")
        self.assertEqual(runtime_config.extension_bundle[0]["package_id"], "@acme/crm")
        self.assertEqual(
            runtime_config.extension_bundle[0]["trust_status"],
            "trusted_local",
        )
        self.assertIsNone(runtime_config.extension_bundle[0]["hub_package_id"])

        tool_manager = service.build_request_tool_manager(
            username="alice",
            agent_id=self.agent.id or 0,
            raw_tool_ids=None,
            extension_bundle=runtime_config.extension_bundle,
        )
        self.assertIsNotNone(tool_manager.get_tool("search_accounts"))

        extra_skills = service.build_bundle_skill_payloads(
            runtime_config.extension_bundle
        )
        prompt_block = skill_service.build_skills_metadata_prompt_json(
            self.session,
            "alice",
            json.dumps(["crm_research"]),
            extra_skills=extra_skills,
        )
        self.assertEqual(
            json.loads(prompt_block),
            [
                {
                    "name": "crm_research",
                    "description": "Research CRM accounts",
                    "path": "/workspace/skills/crm_research/SKILL.md",
                }
            ],
        )

        mounts = skill_service.build_skill_mounts(
            self.session,
            "alice",
            ["crm_research"],
            extra_skills=extra_skills,
        )
        self.assertEqual(len(mounts), 1)
        self.assertTrue(mounts[0]["location"].endswith("/skills/crm_research"))

    def test_snapshot_bundle_includes_packaged_hooks(self) -> None:
        """Resolved extension bundles should pin declared task hooks."""
        extension_root = self._write_extension(hook_event="task.before_start")
        service = ExtensionService(self.session)
        installation = service.install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        service.upsert_agent_binding(
            agent_id=self.agent.id or 0,
            extension_installation_id=installation.id or 0,
            enabled=True,
        )

        bundle = (
            AgentReleaseRuntimeService(self.session)
            .resolve_for_agent(self.agent.id or 0)
            .extension_bundle
        )

        self.assertEqual(len(bundle), 1)
        self.assertEqual(bundle[0]["hooks"][0]["event"], "task.before_start")
        self.assertEqual(bundle[0]["hooks"][0]["callable"], "handle_task_event")
        self.assertTrue(Path(bundle[0]["hooks"][0]["source_path"]).is_file())

    def test_extension_tools_remain_available_under_legacy_tool_allowlist(
        self,
    ) -> None:
        """Bound extension tools and skills should ignore legacy allowlists."""
        extension_root = self._write_extension(
            tool_name="seedream_generate_image",
            skill_name="seedream_skill",
        )
        service = ExtensionService(self.session)
        installation = service.install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        service.upsert_agent_binding(
            agent_id=self.agent.id or 0,
            extension_installation_id=installation.id or 0,
            enabled=True,
        )

        runtime_config = AgentReleaseRuntimeService(self.session).resolve_for_agent(
            self.agent.id or 0
        )
        tool_manager = service.build_request_tool_manager(
            username="alice",
            agent_id=self.agent.id or 0,
            raw_tool_ids=json.dumps(["read_file"]),
            extension_bundle=runtime_config.extension_bundle,
        )
        extension_skills = service.build_bundle_skill_payloads(
            runtime_config.extension_bundle
        )
        visible_skills = skill_service.list_allowed_visible_skills(
            self.session,
            "alice",
            raw_skill_ids=json.dumps(["research"]),
            extra_skills=extension_skills,
        )

        self.assertIsNotNone(tool_manager.get_tool("seedream_generate_image"))
        self.assertTrue(
            any(skill["name"] == "seedream_skill" for skill in visible_skills)
        )

    def test_runtime_manual_tools_ignore_studio_tool_visibility(self) -> None:
        """End-user runtime should still load configured manual tools after Studio access is revoked."""
        tool_name = "customer_lookup"
        workspace_service.write_user_tool(
            self.user.username,
            tool_name,
            (
                "from app.orchestration.tool.metadata import ToolMetadata\n\n"
                "def customer_lookup(account_id: str) -> str:\n"
                '    """Look up one customer."""\n'
                '    return f"customer:{account_id}"\n\n'
                "customer_lookup.__tool_metadata__ = ToolMetadata(\n"
                '    name="customer_lookup",\n'
                '    description="Look up customer records",\n'
                '    parameters={"type": "object", "properties": {}},\n'
                '    tool_type="normal",\n'
                "    func=customer_lookup,\n"
                ")\n"
            ),
        )
        tool = tool_service.ensure_manual_tool_resource(
            self.session,
            owner=self.user,
            tool_name=tool_name,
        )
        tool_service.set_tool_access(
            self.session,
            tool=tool,
            use_scope="selected",
            use_user_ids={self.user.id or 0},
            use_group_ids=set(),
            edit_user_ids={self.user.id or 0},
            edit_group_ids=set(),
        )

        manager = ExtensionService(self.session).build_request_tool_manager(
            username=self.bob.username,
            agent_id=self.agent.id or 0,
            raw_tool_ids=json.dumps([tool_name]),
            extension_bundle=[],
        )

        self.assertIsNotNone(manager.get_tool(tool_name))

    def test_installation_configuration_defaults_are_persisted(self) -> None:
        """Installations should resolve manifest defaults for setup fields."""
        extension_root = self._write_extension(
            package_name="acme.memory",
            tool_name="search_accounts_memory",
            skill_name="crm_research_memory",
            installation_config_fields=[
                {
                    "key": "base_url",
                    "type": "string",
                    "label": "Base URL",
                    "required": True,
                    "default": "http://localhost:8765",
                }
            ],
        )
        installation = ExtensionService(self.session).install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )

        state = ExtensionService(self.session).get_installation_configuration_state(
            installation_id=installation.id or 0
        )
        self.assertEqual(
            state["config"],
            {"base_url": "http://localhost:8765"},
        )

    def test_update_installation_configuration_validates_declared_fields(self) -> None:
        """Installation config writes should reject undeclared or invalid values."""
        extension_root = self._write_extension(
            package_name="acme.memory",
            tool_name="search_accounts_memory",
            skill_name="crm_research_memory",
            installation_config_fields=[
                {
                    "key": "base_url",
                    "type": "string",
                    "required": True,
                },
                {
                    "key": "timeout_seconds",
                    "type": "number",
                    "default": 5,
                },
            ],
        )
        service = ExtensionService(self.session)
        installation = service.install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )

        updated = service.update_installation_config(
            installation_id=installation.id or 0,
            config={
                "base_url": "http://mem0.local",
                "timeout_seconds": 10,
            },
        )
        self.assertEqual(
            json.loads(updated.config_json or "{}"),
            {
                "base_url": "http://mem0.local",
                "timeout_seconds": 10,
            },
        )

        with self.assertRaisesRegex(ValueError, "not declared by the extension"):
            service.update_installation_config(
                installation_id=installation.id or 0,
                config={"unknown": "value"},
            )

    def test_extension_hook_service_runs_task_hook_and_normalizes_emit_event(
        self,
    ) -> None:
        """Task hooks should emit normalized runtime effects without direct mutation."""
        extension_root = self._write_extension(hook_event="task.before_start")
        service = ExtensionService(self.session)
        installation = service.install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        service.upsert_agent_binding(
            agent_id=self.agent.id or 0,
            extension_installation_id=installation.id or 0,
            enabled=True,
        )
        bundle = (
            AgentReleaseRuntimeService(self.session)
            .resolve_for_agent(self.agent.id or 0)
            .extension_bundle
        )

        effects = asyncio.run(
            ExtensionHookService(bundle).run_task_hooks(
                event_name="task.before_start",
                hook_context={
                    "session_id": "session-1",
                    "task_id": "task-1",
                    "trace_id": None,
                    "iteration": 0,
                    "agent_id": self.agent.id or 0,
                    "user": {"id": self.user.id, "username": "alice"},
                    "release_id": None,
                    "execution_mode": "live",
                    "timestamp": "2026-04-02T00:00:00Z",
                    "runtime": {"source": "live", "task_status": "pending"},
                    "event_payload": {"message": "hello"},
                },
            )
        )

        self.assertEqual(len(effects), 1)
        self.assertEqual(effects[0]["type"], "emit_event")
        self.assertEqual(effects[0]["payload"]["type"], "observe")
        self.assertEqual(effects[0]["payload"]["task_id"], "task-1")
        self.assertEqual(
            effects[0]["payload"]["data"]["extension_hook"]["package_id"],
            "@acme/crm",
        )

    def test_extension_hook_service_injects_installation_and_binding_config(
        self,
    ) -> None:
        """Hooks should receive validated installation and binding config snapshots."""
        extension_root = self._write_extension(
            package_name="acme.memory",
            tool_name="search_accounts_memory",
            skill_name="crm_research_memory",
            hook_event="task.before_start",
            hook_behavior="emit_configs",
            installation_config_fields=[
                {
                    "key": "base_url",
                    "type": "string",
                    "required": True,
                    "default": "http://localhost:8765",
                }
            ],
            binding_config_fields=[
                {
                    "key": "namespace",
                    "type": "string",
                    "default": "default",
                }
            ],
        )
        service = ExtensionService(self.session)
        installation = service.install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        service.update_installation_config(
            installation_id=installation.id or 0,
            config={"base_url": "http://mem0.internal"},
        )
        service.upsert_agent_binding(
            agent_id=self.agent.id or 0,
            extension_installation_id=installation.id or 0,
            enabled=True,
            config={"namespace": "agent-2"},
        )
        bundle = (
            AgentReleaseRuntimeService(self.session)
            .resolve_for_agent(self.agent.id or 0)
            .extension_bundle
        )

        effects = asyncio.run(
            ExtensionHookService(bundle).run_task_hooks(
                event_name="task.before_start",
                hook_context={
                    "session_id": "session-1",
                    "task_id": "task-1",
                    "trace_id": None,
                    "iteration": 0,
                    "agent_id": self.agent.id or 0,
                    "user": {"id": self.user.id, "username": "alice"},
                    "release_id": None,
                    "execution_mode": "live",
                    "timestamp": "2026-04-02T00:00:00Z",
                    "runtime": {"source": "live", "task_status": "pending"},
                    "event_payload": {"message": "hello"},
                },
            )
        )

        self.assertEqual(
            effects[0]["payload"]["data"]["installation_config"],
            {"base_url": "http://mem0.internal"},
        )
        self.assertEqual(
            effects[0]["payload"]["data"]["binding_config"],
            {"namespace": "agent-2"},
        )
        self.assertEqual(
            effects[0]["payload"]["data"]["user"],
            {"id": self.user.id, "username": "alice"},
        )

    def test_extension_hook_service_runs_iteration_hook(self) -> None:
        """Iteration-level observe-only hooks should load from the pinned bundle."""
        extension_root = self._write_extension(hook_event="iteration.plan_updated")
        service = ExtensionService(self.session)
        installation = service.install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        service.upsert_agent_binding(
            agent_id=self.agent.id or 0,
            extension_installation_id=installation.id or 0,
            enabled=True,
        )
        bundle = (
            AgentReleaseRuntimeService(self.session)
            .resolve_for_agent(self.agent.id or 0)
            .extension_bundle
        )

        effects = asyncio.run(
            ExtensionHookService(bundle).run_hooks(
                event_name="iteration.plan_updated",
                hook_context={
                    "session_id": "session-1",
                    "task_id": "task-1",
                    "trace_id": "trace-1",
                    "iteration": 2,
                    "agent_id": self.agent.id or 0,
                    "release_id": None,
                    "execution_mode": "live",
                    "timestamp": "2026-04-02T00:00:00Z",
                    "runtime": {"source": "live", "task_status": "running"},
                    "event_payload": {"current_plan": ["collect facts"]},
                },
            )
        )

        self.assertEqual(len(effects), 1)
        self.assertEqual(effects[0]["type"], "emit_event")
        self.assertEqual(effects[0]["payload"]["trace_id"], "trace-1")
        self.assertEqual(
            effects[0]["payload"]["data"]["extension_hook"]["event"],
            "iteration.plan_updated",
        )

    def test_extension_hook_service_runs_tool_iteration_hooks(self) -> None:
        """Tool lifecycle hooks should support both call and result observation."""
        before_root = self._write_extension(
            package_name="acme.before",
            tool_name="search_accounts_before",
            skill_name="crm_research_before",
            hook_event="iteration.before_tool_call",
        )
        after_root = self._write_extension(
            package_name="acme.after",
            tool_name="search_accounts_after",
            skill_name="crm_research_after",
            hook_event="iteration.after_tool_result",
        )
        service = ExtensionService(self.session)
        before_install = service.install_from_path(
            source_dir=before_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        after_install = service.install_from_path(
            source_dir=after_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        service.upsert_agent_binding(
            agent_id=self.agent.id or 0,
            extension_installation_id=before_install.id or 0,
            enabled=True,
            priority=10,
        )
        service.upsert_agent_binding(
            agent_id=self.agent.id or 0,
            extension_installation_id=after_install.id or 0,
            enabled=True,
            priority=20,
        )
        bundle = (
            AgentReleaseRuntimeService(self.session)
            .resolve_for_agent(self.agent.id or 0)
            .extension_bundle
        )
        hook_service = ExtensionHookService(bundle)

        before_effects = asyncio.run(
            hook_service.run_hooks(
                event_name="iteration.before_tool_call",
                hook_context={
                    "session_id": "session-1",
                    "task_id": "task-1",
                    "trace_id": "trace-1",
                    "iteration": 2,
                    "agent_id": self.agent.id or 0,
                    "release_id": None,
                    "execution_mode": "live",
                    "timestamp": "2026-04-02T00:00:00Z",
                    "runtime": {"source": "live", "task_status": "running"},
                    "event_payload": {
                        "tool_calls": [{"name": "search_accounts", "arguments": {}}]
                    },
                },
            )
        )
        after_effects = asyncio.run(
            hook_service.run_hooks(
                event_name="iteration.after_tool_result",
                hook_context={
                    "session_id": "session-1",
                    "task_id": "task-1",
                    "trace_id": "trace-1",
                    "iteration": 2,
                    "agent_id": self.agent.id or 0,
                    "release_id": None,
                    "execution_mode": "live",
                    "timestamp": "2026-04-02T00:00:01Z",
                    "runtime": {"source": "live", "task_status": "running"},
                    "event_payload": {
                        "tool_results": [{"name": "search_accounts", "success": True}]
                    },
                },
            )
        )

        self.assertEqual(len(before_effects), 1)
        self.assertEqual(len(after_effects), 1)
        self.assertEqual(
            before_effects[0]["payload"]["data"]["extension_hook"]["event"],
            "iteration.before_tool_call",
        )
        self.assertEqual(
            after_effects[0]["payload"]["data"]["extension_hook"]["event"],
            "iteration.after_tool_result",
        )

    def test_extension_hook_effect_service_applies_task_bootstrap_prompt_blocks(
        self,
    ) -> None:
        """Mutable task-start effects should produce ordered bootstrap prompt blocks."""
        extension_root = self._write_extension(
            package_name="acme.memory",
            tool_name="search_accounts_memory",
            skill_name="crm_research_memory",
            hook_event="task.before_start",
            hook_behavior="append_prompt_block",
        )
        service = ExtensionService(self.session)
        installation = service.install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        service.upsert_agent_binding(
            agent_id=self.agent.id or 0,
            extension_installation_id=installation.id or 0,
            enabled=True,
        )
        bundle = (
            AgentReleaseRuntimeService(self.session)
            .resolve_for_agent(self.agent.id or 0)
            .extension_bundle
        )

        effects = asyncio.run(
            ExtensionHookService(bundle).run_hooks(
                event_name="task.before_start",
                hook_context={
                    "session_id": "session-1",
                    "task_id": "task-memory",
                    "trace_id": None,
                    "iteration": 0,
                    "agent_id": self.agent.id or 0,
                    "release_id": None,
                    "execution_mode": "live",
                    "timestamp": "2026-04-02T00:00:00Z",
                    "runtime": {"source": "live", "task_status": "pending"},
                    "event_payload": {"message": "hello"},
                },
            )
        )

        applied = ExtensionHookEffectService().apply_effects(
            event_name="task.before_start",
            effects=effects,
        )
        self.assertEqual(applied.emitted_events, [])
        self.assertEqual(
            applied.task_bootstrap_head_blocks,
            ["Remember the latest billing preferences."],
        )
        self.assertEqual(applied.task_bootstrap_tail_blocks, [])

    def test_install_rejects_unsupported_hook_event(self) -> None:
        """Unsupported lifecycle hook events should fail during manifest validation."""
        extension_root = self._write_extension(hook_event="iteration.before_llm")

        with self.assertRaisesRegex(ValueError, "Unsupported hook event"):
            ExtensionService(self.session).install_from_path(
                source_dir=extension_root,
                installed_by="alice",
                trust_confirmed=True,
            )

    def test_hook_execution_service_records_successful_hook_runs(self) -> None:
        """Hook execution logs should persist successful packaged hook runs."""
        extension_root = self._write_extension(hook_event="task.before_start")
        service = ExtensionService(self.session)
        installation = service.install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        service.upsert_agent_binding(
            agent_id=self.agent.id or 0,
            extension_installation_id=installation.id or 0,
            enabled=True,
        )
        bundle = (
            AgentReleaseRuntimeService(self.session)
            .resolve_for_agent(self.agent.id or 0)
            .extension_bundle
        )
        execution_service = ExtensionHookExecutionService(self.session)

        effects = asyncio.run(
            ExtensionHookService(
                bundle,
                execution_service=execution_service,
            ).run_hooks(
                event_name="task.before_start",
                hook_context={
                    "session_id": "session-1",
                    "task_id": "task-1",
                    "trace_id": None,
                    "iteration": 0,
                    "agent_id": self.agent.id or 0,
                    "release_id": None,
                    "execution_mode": "live",
                    "timestamp": "2026-04-02T00:00:00Z",
                    "runtime": {"source": "live", "task_status": "pending"},
                    "event_payload": {"message": "hello"},
                },
            )
        )

        self.assertEqual(len(effects), 1)
        rows = execution_service.list_executions(task_id="task-1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].status, "succeeded")
        self.assertEqual(rows[0].hook_event, "task.before_start")
        self.assertEqual(rows[0].extension_package_id, "@acme/crm")
        self.assertIsNotNone(rows[0].hook_context_json)
        self.assertIsNotNone(rows[0].effects_json)
        self.assertGreaterEqual(rows[0].duration_ms, 0)

    def test_hook_replay_service_replays_one_historical_execution(self) -> None:
        """Safe replay should rerun one recorded hook without appending a new log."""
        extension_root = self._write_extension(hook_event="task.before_start")
        service = ExtensionService(self.session)
        installation = service.install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        service.upsert_agent_binding(
            agent_id=self.agent.id or 0,
            extension_installation_id=installation.id or 0,
            enabled=True,
        )
        bundle = (
            AgentReleaseRuntimeService(self.session)
            .resolve_for_agent(self.agent.id or 0)
            .extension_bundle
        )
        execution_service = ExtensionHookExecutionService(self.session)
        hook_context = {
            "session_id": "session-1",
            "task_id": "task-replay",
            "trace_id": None,
            "iteration": 0,
            "agent_id": self.agent.id or 0,
            "release_id": None,
            "execution_mode": "live",
            "timestamp": "2026-04-02T00:00:00Z",
            "runtime": {"source": "live", "task_status": "pending"},
            "event_payload": {"message": "hello"},
        }

        asyncio.run(
            ExtensionHookService(
                bundle,
                execution_service=execution_service,
            ).run_hooks(
                event_name="task.before_start",
                hook_context=hook_context,
            )
        )

        rows = execution_service.list_executions(task_id="task-replay")
        self.assertEqual(len(rows), 1)

        replay_result = asyncio.run(
            ExtensionHookReplayService(self.session).replay_execution(
                execution_id=rows[0].id or 0
            )
        )

        self.assertEqual(replay_result["status"], "succeeded")
        replay_effects = replay_result["effects"]
        self.assertIsInstance(replay_effects, list)
        if not isinstance(replay_effects, list):
            self.fail("Expected replay effects to be returned.")
        self.assertEqual(replay_effects[0]["type"], "emit_event")
        self.assertEqual(
            replay_effects[0]["payload"]["data"]["extension_hook"]["package_id"],
            "@acme/crm",
        )
        self.assertEqual(
            len(execution_service.list_executions(task_id="task-replay")), 1
        )

    def test_hook_replay_switches_execution_mode_to_replay(self) -> None:
        """Replay should expose replay mode so external hooks can skip live writes."""
        extension_root = self._write_extension(
            package_name="acme.replay",
            tool_name="search_accounts_replay",
            skill_name="crm_research_replay",
            hook_event="task.before_start",
            hook_behavior="emit_execution_mode",
        )
        service = ExtensionService(self.session)
        installation = service.install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        service.upsert_agent_binding(
            agent_id=self.agent.id or 0,
            extension_installation_id=installation.id or 0,
            enabled=True,
        )
        execution = ExtensionHookExecutionService(self.session).create_execution(
            session_id="session-1",
            task_id="task-replay-mode",
            trace_id=None,
            iteration=0,
            agent_id=self.agent.id or 0,
            release_id=None,
            extension_package_id="@acme/replay",
            extension_version="0.1.0",
            hook_event="task.before_start",
            hook_callable="handle_task_event",
            status="succeeded",
            hook_context_payload={
                "session_id": "session-1",
                "task_id": "task-replay-mode",
                "trace_id": None,
                "iteration": 0,
                "agent_id": self.agent.id or 0,
                "release_id": None,
                "execution_mode": "live",
                "timestamp": "2026-04-02T00:00:00Z",
                "runtime": {"source": "live", "task_status": "pending"},
                "event_payload": {"message": "hello"},
            },
            effects_payload=[],
            error_payload=None,
            duration_ms=1,
        )

        replay_result = asyncio.run(
            ExtensionHookReplayService(self.session).replay_execution(
                execution_id=execution.id or 0
            )
        )

        replay_effects = replay_result["effects"]
        self.assertIsInstance(replay_effects, list)
        if not isinstance(replay_effects, list):
            self.fail("Expected replay effects to be returned.")
        self.assertEqual(
            replay_effects[0]["payload"]["data"]["execution_mode"],
            "replay",
        )

    def test_hook_execution_service_records_failed_hook_runs(self) -> None:
        """Hook execution logs should persist failure payloads for crashed hooks."""
        extension_root = self._write_extension(
            package_name="acme.failure",
            tool_name="search_accounts_failure",
            skill_name="crm_research_failure",
            hook_event="task.before_start",
            hook_behavior="raise",
        )
        service = ExtensionService(self.session)
        installation = service.install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        service.upsert_agent_binding(
            agent_id=self.agent.id or 0,
            extension_installation_id=installation.id or 0,
            enabled=True,
        )
        bundle = (
            AgentReleaseRuntimeService(self.session)
            .resolve_for_agent(self.agent.id or 0)
            .extension_bundle
        )
        execution_service = ExtensionHookExecutionService(self.session)

        with self.assertRaisesRegex(RuntimeError, "hook boom"):
            asyncio.run(
                ExtensionHookService(
                    bundle,
                    execution_service=execution_service,
                ).run_hooks(
                    event_name="task.before_start",
                    hook_context={
                        "session_id": "session-1",
                        "task_id": "task-2",
                        "trace_id": None,
                        "iteration": 0,
                        "agent_id": self.agent.id or 0,
                        "release_id": None,
                        "execution_mode": "live",
                        "timestamp": "2026-04-02T00:00:00Z",
                        "runtime": {"source": "live", "task_status": "pending"},
                        "event_payload": {"message": "hello"},
                    },
                )
            )

        rows = execution_service.list_executions(task_id="task-2")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].status, "failed")
        self.assertIsNone(rows[0].effects_json)
        self.assertIsNotNone(rows[0].error_json)

        latest_row = self.session.get(ExtensionHookExecution, rows[0].id)
        self.assertIsNotNone(latest_row)

    def test_install_requires_skill_markdown_entry(self) -> None:
        """Skill contributions must point to a directory containing SKILL.md."""
        extension_root = self._write_extension()
        (extension_root / "skills" / "crm_research" / "SKILL.md").unlink()

        with self.assertRaisesRegex(ValueError, "must contain SKILL.md"):
            ExtensionService(self.session).install_from_path(
                source_dir=extension_root,
                installed_by="alice",
                trust_confirmed=True,
            )

    def test_hook_contributions_require_name_and_description(self) -> None:
        """Hook declarations should stay operator-readable in package detail views."""
        extension_root = self._write_extension(hook_event="task.before_start")
        manifest_path = extension_root / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        hook = manifest["contributions"]["hooks"][0]
        del hook["name"]
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "must declare a name"):
            ExtensionService(self.session).install_from_path(
                source_dir=extension_root,
                installed_by="alice",
                trust_confirmed=True,
            )

        hook["name"] = "Recall CRM Context"
        del hook["description"]
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "must declare a description"):
            ExtensionService(self.session).install_from_path(
                source_dir=extension_root,
                installed_by="alice",
                trust_confirmed=True,
            )

    def test_api_installation_serialization_includes_contribution_summary(self) -> None:
        """Expose normalized provider and lightweight contribution names in API payloads."""
        extension_root = self._write_extension(
            package_name="acme.providers",
            version="1.0.0",
            channel_provider_key="acme@chat",
            web_search_provider_key="acme@search",
            hook_event="task.before_start",
            chat_surface_key="workspace-editor",
        )
        installation = ExtensionService(self.session).install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )

        response = extension_api_module._serialize_installation(
            installation,
            service=ExtensionService(self.session),
        )

        self.assertEqual(response.contribution_summary.tools, ["search_accounts"])
        self.assertEqual(response.contribution_summary.skills, ["crm_research"])
        self.assertEqual(
            response.contribution_summary.hooks,
            ["Recall CRM Context"],
        )
        self.assertEqual(
            response.contribution_items[0].model_dump(),
            {
                "type": "hook",
                "name": "Recall CRM Context",
                "description": "Restores CRM context before the task starts.",
                "key": None,
                "min_width": None,
            },
        )
        self.assertEqual(response.scope, "acme")
        self.assertEqual(response.name, "providers")
        self.assertEqual(response.package_id, "@acme/providers")
        self.assertEqual(response.trust_status, "trusted_local")
        self.assertEqual(response.trust_source, "local_import")
        self.assertEqual(response.artifact_storage_backend, "local_fs")
        self.assertTrue(response.artifact_key.endswith(".tar.gz"))
        self.assertTrue(bool(response.artifact_digest))
        self.assertGreater(response.artifact_size_bytes, 0)
        self.assertIsNone(response.hub_package_id)
        self.assertIsNone(response.hub_package_version_id)
        self.assertIsNone(response.hub_artifact_digest)
        self.assertEqual(
            response.contribution_summary.channel_providers,
            ["acme@chat"],
        )
        self.assertEqual(
            response.contribution_summary.web_search_providers,
            ["acme@search"],
        )
        self.assertEqual(
            response.contribution_summary.chat_surfaces,
            ["workspace-editor"],
        )
        chat_surface_item = next(
            item for item in response.contribution_items if item.type == "chat_surface"
        )
        self.assertEqual(chat_surface_item.key, "workspace-editor")
        self.assertEqual(chat_surface_item.min_width, 560)
        self.assertIsNotNone(response.reference_summary)
        if response.reference_summary is None:
            self.fail("Expected reference summary to be serialized.")
        self.assertEqual(response.reference_summary.binding_count, 0)

    def test_runtime_bundle_includes_chat_surfaces(self) -> None:
        """Resolved extension bundles should include declared chat surfaces."""
        extension_root = self._write_extension(chat_surface_key="workspace-editor")
        service = ExtensionService(self.session)
        installation = service.install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        service.upsert_agent_binding(
            agent_id=self.agent.id or 0,
            extension_installation_id=installation.id or 0,
            enabled=True,
        )

        bundle = service.build_agent_extension_snapshot(self.agent.id or 0)

        self.assertEqual(len(bundle), 1)
        self.assertEqual(bundle[0]["chat_surfaces"][0]["key"], "workspace-editor")
        self.assertEqual(
            bundle[0]["chat_surfaces"][0]["display_name"],
            "Workspace Editor",
        )
        self.assertEqual(
            bundle[0]["chat_surfaces"][0]["placement"],
            "right_dock",
        )
        self.assertEqual(bundle[0]["chat_surfaces"][0]["min_width"], 560)
        self.assertTrue(Path(bundle[0]["chat_surfaces"][0]["source_path"]).is_file())

    def test_sample_memory_extension_recalls_and_persists_external_memory(self) -> None:
        """The sample memory extension should store externally and recall on start."""
        extension_root = self._sample_memory_extension_root()
        installation = ExtensionService(self.session).install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        ExtensionService(self.session).upsert_agent_binding(
            agent_id=self.agent.id or 0,
            extension_installation_id=installation.id or 0,
            enabled=True,
        )
        bundle = (
            AgentReleaseRuntimeService(self.session)
            .resolve_for_agent(self.agent.id or 0)
            .extension_bundle
        )
        memory_path = self.root / "external-memory.json"

        with patch.dict(
            "os.environ",
            {"PIVOT_SAMPLE_MEMORY_PATH": str(memory_path)},
            clear=False,
        ):
            completed_effects = asyncio.run(
                ExtensionHookService(bundle).run_hooks(
                    event_name="task.completed",
                    hook_context={
                        "session_id": "session-1",
                        "task_id": "task-memory-ext",
                        "trace_id": None,
                        "iteration": 2,
                        "agent_id": self.agent.id or 0,
                        "release_id": None,
                        "execution_mode": "live",
                        "timestamp": "2026-04-02T00:00:00Z",
                        "task": {
                            "user_message": "Remember that the user prefers quarterly billing.",
                            "status": "completed",
                            "total_tokens": 42,
                            "agent_answer": "The user prefers quarterly billing going forward.",
                        },
                        "runtime": {"source": "live", "task_status": "completed"},
                        "event_payload": {},
                    },
                )
            )

            self.assertTrue(memory_path.is_file())
            self.assertEqual(completed_effects[0]["type"], "emit_event")

            recalled_effects = asyncio.run(
                ExtensionHookService(bundle).run_hooks(
                    event_name="task.before_start",
                    hook_context={
                        "session_id": "session-1",
                        "task_id": "task-memory-ext-2",
                        "trace_id": None,
                        "iteration": 0,
                        "agent_id": self.agent.id or 0,
                        "release_id": None,
                        "execution_mode": "live",
                        "timestamp": "2026-04-02T00:10:00Z",
                        "task": {
                            "user_message": "Please draft the next invoice email.",
                            "status": "pending",
                            "total_tokens": 0,
                            "agent_answer": None,
                        },
                        "runtime": {"source": "live", "task_status": "pending"},
                        "event_payload": {
                            "message": "Please draft the next invoice email."
                        },
                    },
                )
            )

        applied = ExtensionHookEffectService().apply_effects(
            event_name="task.before_start",
            effects=recalled_effects,
        )
        self.assertEqual(len(applied.task_bootstrap_head_blocks), 1)
        self.assertIn(
            "Retrieved External Memory", applied.task_bootstrap_head_blocks[0]
        )
        self.assertIn("quarterly billing", applied.task_bootstrap_head_blocks[0])

    def test_binding_rejects_duplicate_extension_tool_names(self) -> None:
        """Enabled bindings should reject duplicate extension tool names."""
        first_root = self._write_extension(package_name="acme.crm", version="0.1.0")
        second_root = self._write_extension(package_name="acme.sales", version="0.2.0")
        service = ExtensionService(self.session)

        first_install = service.install_from_path(
            source_dir=first_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        second_install = service.install_from_path(
            source_dir=second_root,
            installed_by="alice",
            trust_confirmed=True,
        )

        service.upsert_agent_binding(
            agent_id=self.agent.id or 0,
            extension_installation_id=first_install.id or 0,
            enabled=True,
        )
        with self.assertRaisesRegex(ValueError, "tool name conflict"):
            service.upsert_agent_binding(
                agent_id=self.agent.id or 0,
                extension_installation_id=second_install.id or 0,
                enabled=True,
            )

    def test_list_packages_groups_versions_and_sorts_them(self) -> None:
        """Package view should group versions and prefer higher numeric versions."""
        service = ExtensionService(self.session)
        first_root = self._write_extension(package_name="acme.crm", version="0.2.0")
        second_root = self._write_extension(package_name="acme.crm", version="0.10.0")
        third_root = self._write_extension(package_name="beta.sales", version="1.0.0")

        first_install = service.install_from_path(
            source_dir=first_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        second_install = service.install_from_path(
            source_dir=second_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        service.install_from_path(
            source_dir=third_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        service.set_installation_status(
            installation_id=first_install.id or 0,
            status="disabled",
        )
        service.set_installation_status(
            installation_id=second_install.id or 0,
            status="active",
        )

        packages = service.list_packages()

        self.assertEqual(len(packages), 2)
        self.assertEqual(packages[0]["scope"], "acme")
        self.assertEqual(packages[0]["name"], "crm")
        self.assertEqual(packages[0]["package_id"], "@acme/crm")
        self.assertEqual(packages[0]["latest_version"], "0.10.0")
        self.assertEqual(packages[0]["active_version_count"], 1)
        self.assertEqual(packages[0]["disabled_version_count"], 1)
        versions = packages[0]["versions"]
        self.assertEqual([item.version for item in versions], ["0.10.0", "0.2.0"])
        self.assertEqual(packages[1]["scope"], "beta")
        self.assertEqual(packages[1]["name"], "sales")
        self.assertEqual(packages[1]["package_id"], "@beta/sales")

    def test_root_logo_png_is_used_when_manifest_omits_logo_path(self) -> None:
        """Root-level logo.png should become the package logo by convention."""
        extension_root = self._write_extension(include_default_logo=True)
        service = ExtensionService(self.session)

        installation = service.install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )

        logo_path = service.get_installation_logo_path(installation)

        self.assertIsNotNone(logo_path)
        if logo_path is None:
            return
        self.assertEqual(logo_path.name, "logo.png")
        self.assertEqual(
            service.get_installation_logo_url(installation),
            (
                f"/api/extensions/installations/{installation.id}/logo"
                f"?v={installation.artifact_digest}"
            ),
        )

    def test_root_logo_webp_is_used_when_manifest_omits_logo_path(self) -> None:
        """Root-level logo.webp should also be accepted by convention."""
        extension_root = self._write_extension()
        (extension_root / "logo.webp").write_bytes(b"RIFFtestWEBP")
        service = ExtensionService(self.session)

        installation = service.install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )

        logo_path = service.get_installation_logo_path(installation)

        self.assertIsNotNone(logo_path)
        if logo_path is None:
            return
        self.assertEqual(logo_path.name, "logo.webp")

    def test_manifest_logo_path_supports_nested_assets(self) -> None:
        """Manifest logo_path should allow package-relative image assets."""
        extension_root = self._write_extension(logo_path="assets/branding/mem0.png")
        service = ExtensionService(self.session)

        installation = service.install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )

        logo_path = service.get_installation_logo_path(installation)

        self.assertIsNotNone(logo_path)
        if logo_path is None:
            return
        self.assertEqual(logo_path.name, "mem0.png")
        parsed_manifest = json.loads(installation.manifest_json)
        self.assertEqual(parsed_manifest["logo_path"], "assets/branding/mem0.png")

    def test_list_agent_package_choices_marks_selected_version_and_updates(
        self,
    ) -> None:
        """Agent package view should include current selection and upgrade state."""
        service = ExtensionService(self.session)
        old_root = self._write_extension(package_name="acme.crm", version="0.1.0")
        new_root = self._write_extension(
            package_name="acme.crm",
            version="0.2.0",
            tool_name="search_accounts_v2",
        )
        old_install = service.install_from_path(
            source_dir=old_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        service.install_from_path(
            source_dir=new_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        service.upsert_agent_binding(
            agent_id=self.agent.id or 0,
            extension_installation_id=old_install.id or 0,
            enabled=True,
            priority=15,
        )

        packages = service.list_agent_package_choices(self.agent.id or 0)

        self.assertEqual(len(packages), 1)
        self.assertEqual(packages[0]["scope"], "acme")
        self.assertEqual(packages[0]["name"], "crm")
        self.assertEqual(packages[0]["package_id"], "@acme/crm")
        self.assertTrue(bool(packages[0]["has_update_available"]))
        selected_binding = packages[0]["selected_binding"]
        self.assertIsNotNone(selected_binding)
        if selected_binding is None:
            self.fail("Expected one selected binding for the package.")
        self.assertEqual(selected_binding.priority, 15)
        self.assertEqual(selected_binding.extension_installation_id, old_install.id)
        versions = packages[0]["versions"]
        self.assertEqual([item.version for item in versions], ["0.2.0", "0.1.0"])

    def test_binding_rejects_enabling_disabled_installation(self) -> None:
        """Bindings cannot enable installations that are already disabled."""
        extension_root = self._write_extension()
        service = ExtensionService(self.session)
        installation = service.install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        service.set_installation_status(
            installation_id=installation.id or 0,
            status="disabled",
        )

        with self.assertRaisesRegex(ValueError, "Disabled extension versions"):
            service.upsert_agent_binding(
                agent_id=self.agent.id or 0,
                extension_installation_id=installation.id or 0,
                enabled=True,
            )

    def test_delete_agent_binding_removes_selected_package_binding(self) -> None:
        """Deleting one binding should clear it from binding and package views."""
        service = ExtensionService(self.session)
        extension_root = self._write_extension()
        installation = service.install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        service.upsert_agent_binding(
            agent_id=self.agent.id or 0,
            extension_installation_id=installation.id or 0,
            enabled=True,
            priority=30,
        )

        service.delete_agent_binding(
            agent_id=self.agent.id or 0,
            extension_installation_id=installation.id or 0,
        )

        self.assertEqual(service.list_agent_bindings(self.agent.id or 0), [])
        packages = service.list_agent_package_choices(self.agent.id or 0)
        self.assertEqual(len(packages), 1)
        self.assertIsNone(packages[0]["selected_binding"])
        self.assertFalse(bool(packages[0]["has_update_available"]))

    def test_delete_agent_binding_requires_existing_row(self) -> None:
        """Deleting a missing binding should raise a descriptive error."""
        service = ExtensionService(self.session)
        extension_root = self._write_extension()
        installation = service.install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )

        with self.assertRaisesRegex(ValueError, "binding not found"):
            service.delete_agent_binding(
                agent_id=self.agent.id or 0,
                extension_installation_id=installation.id or 0,
            )

    def test_replace_agent_bindings_replaces_versions_and_removes_omitted_rows(
        self,
    ) -> None:
        """Batch replace should support version switches and omitted-row removal."""
        first_root = self._write_extension(package_name="acme.crm", version="0.1.0")
        second_root = self._write_extension(
            package_name="acme.crm",
            version="0.2.0",
            tool_name="search_accounts_v2",
        )
        service = ExtensionService(self.session)
        first_install = service.install_from_path(
            source_dir=first_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        second_install = service.install_from_path(
            source_dir=second_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        service.upsert_agent_binding(
            agent_id=self.agent.id or 0,
            extension_installation_id=first_install.id or 0,
            enabled=True,
            priority=10,
        )

        bindings = service.replace_agent_bindings(
            agent_id=self.agent.id or 0,
            bindings=[
                {
                    "extension_installation_id": second_install.id or 0,
                    "enabled": True,
                    "priority": 5,
                    "config": {"region": "eu"},
                }
            ],
        )

        self.assertEqual(len(bindings), 1)
        self.assertEqual(bindings[0].extension_installation_id, second_install.id)
        self.assertEqual(bindings[0].priority, 5)
        self.assertEqual(
            ExtensionService(self.session)
            .list_agent_bindings(self.agent.id or 0)[0]
            .extension_installation_id,
            second_install.id,
        )
        snapshot = AgentSnapshotService(self.session).build_current_snapshot(
            self.agent.id or 0
        )
        self.assertEqual(len(snapshot["extensions"]), 1)
        self.assertEqual(snapshot["extensions"][0]["version"], "0.2.0")

    def test_replace_agent_bindings_rejects_duplicate_installation_ids(self) -> None:
        """Batch replace should reject duplicate installation references."""
        extension_root = self._write_extension()
        service = ExtensionService(self.session)
        installation = service.install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )

        with self.assertRaisesRegex(ValueError, "may appear only once"):
            service.replace_agent_bindings(
                agent_id=self.agent.id or 0,
                bindings=[
                    {
                        "extension_installation_id": installation.id or 0,
                        "enabled": True,
                        "priority": 10,
                        "config": {},
                    },
                    {
                        "extension_installation_id": installation.id or 0,
                        "enabled": False,
                        "priority": 20,
                        "config": {},
                    },
                ],
            )

    def test_binding_rejects_multiple_versions_of_same_package(self) -> None:
        """One agent cannot bind multiple versions of the same extension package."""
        service = ExtensionService(self.session)
        first_root = self._write_extension(package_name="acme.crm", version="0.1.0")
        second_root = self._write_extension(
            package_name="acme.crm",
            version="0.2.0",
            tool_name="search_accounts_v2",
        )
        first_install = service.install_from_path(
            source_dir=first_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        second_install = service.install_from_path(
            source_dir=second_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        service.upsert_agent_binding(
            agent_id=self.agent.id or 0,
            extension_installation_id=first_install.id or 0,
            enabled=True,
        )

        with self.assertRaisesRegex(
            ValueError, "only one version per extension package"
        ):
            service.upsert_agent_binding(
                agent_id=self.agent.id or 0,
                extension_installation_id=second_install.id or 0,
                enabled=True,
            )

    def test_replace_agent_bindings_rejects_duplicate_package_names(self) -> None:
        """Batch replace should reject multiple versions of one package."""
        service = ExtensionService(self.session)
        first_root = self._write_extension(package_name="acme.crm", version="0.1.0")
        second_root = self._write_extension(
            package_name="acme.crm",
            version="0.2.0",
            tool_name="search_accounts_v2",
        )
        first_install = service.install_from_path(
            source_dir=first_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        second_install = service.install_from_path(
            source_dir=second_root,
            installed_by="alice",
            trust_confirmed=True,
        )

        with self.assertRaisesRegex(ValueError, "package may appear only once"):
            service.replace_agent_bindings(
                agent_id=self.agent.id or 0,
                bindings=[
                    {
                        "extension_installation_id": first_install.id or 0,
                        "enabled": True,
                        "priority": 10,
                        "config": {},
                    },
                    {
                        "extension_installation_id": second_install.id or 0,
                        "enabled": True,
                        "priority": 20,
                        "config": {},
                    },
                ],
            )

    def test_install_bundle_imports_uploaded_extension_files(self) -> None:
        """Bundle imports should accept browser-style relative file payloads."""
        extension_root = self._write_extension()
        files = [
            ExtensionBundleImportFile(
                relative_path="acme_bundle/manifest.json",
                content=(extension_root / "manifest.json").read_bytes(),
            ),
            ExtensionBundleImportFile(
                relative_path="acme_bundle/tools/search_accounts.py",
                content=(extension_root / "tools" / "search_accounts.py").read_bytes(),
            ),
            ExtensionBundleImportFile(
                relative_path="acme_bundle/skills/crm_research/SKILL.md",
                content=(
                    extension_root / "skills" / "crm_research" / "SKILL.md"
                ).read_bytes(),
            ),
        ]

        installation = ExtensionService(self.session).install_bundle(
            bundle_name="acme_bundle",
            files=files,
            installed_by="alice",
            trust_confirmed=True,
        )

        self.assertEqual(installation.source, "bundle")
        self.assertEqual(installation.scope, "acme")
        self.assertEqual(installation.name, "crm")
        self.assertEqual(installation.package_id, "@acme/crm")
        self.assertEqual(installation.trust_status, "trusted_local")
        self.assertEqual(installation.trust_source, "local_import")
        self.assertEqual(installation.artifact_storage_backend, "local_fs")
        self.assertTrue(installation.artifact_key.endswith(".tar.gz"))
        self.assertTrue(bool(installation.artifact_digest))
        self.assertGreater(installation.artifact_size_bytes, 0)
        self.assertIsNone(installation.hub_scope)
        self.assertIsNone(installation.hub_package_id)
        self.assertIsNone(installation.hub_package_version_id)
        self.assertIsNone(installation.hub_artifact_digest)
        self.assertTrue(
            Path(installation.install_root).is_relative_to(self.runtime_cache_root)
        )
        self.assertTrue(
            Path(installation.install_root).joinpath("manifest.json").is_file()
        )

    def test_preview_bundle_returns_unverified_trust_metadata(self) -> None:
        """Bundle preview should stay unverified until the operator approves it."""
        extension_root = self._write_extension(
            package_name="acme.providers",
            version="1.0.0",
            hook_event="task.before_start",
        )
        files = [
            ExtensionBundleImportFile(
                relative_path="acme_bundle/manifest.json",
                content=(extension_root / "manifest.json").read_bytes(),
            ),
            ExtensionBundleImportFile(
                relative_path="acme_bundle/tools/search_accounts.py",
                content=(extension_root / "tools" / "search_accounts.py").read_bytes(),
            ),
            ExtensionBundleImportFile(
                relative_path="acme_bundle/skills/crm_research/SKILL.md",
                content=(
                    extension_root / "skills" / "crm_research" / "SKILL.md"
                ).read_bytes(),
            ),
            ExtensionBundleImportFile(
                relative_path="acme_bundle/hooks/lifecycle.py",
                content=(extension_root / "hooks" / "lifecycle.py").read_bytes(),
            ),
        ]

        preview = ExtensionService(self.session).preview_bundle(
            bundle_name="acme_bundle",
            files=files,
        )

        self.assertEqual(preview.package_id, "@acme/providers")
        self.assertEqual(preview.trust_status, "unverified")
        self.assertEqual(preview.trust_source, "local_import")
        self.assertEqual(preview.contribution_summary["tools"], ["search_accounts"])
        self.assertEqual(
            preview.contribution_summary["hooks"],
            ["Recall CRM Context"],
        )
        self.assertEqual(
            preview.contribution_items[0],
            {
                "type": "hook",
                "name": "Recall CRM Context",
                "description": "Restores CRM context before the task starts.",
                "key": None,
                "min_width": None,
            },
        )

    def test_install_from_path_requires_explicit_trust_confirmation(self) -> None:
        """Local installs should fail until the operator confirms trust."""
        extension_root = self._write_extension()

        with self.assertRaisesRegex(
            ValueError,
            "explicitly trusted before installation",
        ):
            ExtensionService(self.session).install_from_path(
                source_dir=extension_root,
                installed_by="alice",
                trust_confirmed=False,
            )

    def test_install_from_path_is_idempotent_for_same_version_and_manifest(
        self,
    ) -> None:
        """Re-importing the same package version should reuse the existing row."""
        extension_root = self._write_extension()
        service = ExtensionService(self.session)

        first = service.install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        second = service.install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )

        self.assertEqual(first.id, second.id)
        self.assertEqual(first.artifact_key, second.artifact_key)
        self.assertTrue(Path(second.install_root).joinpath("manifest.json").is_file())

    def test_preview_from_path_flags_safe_overwrite_for_changed_same_version(
        self,
    ) -> None:
        """Preview should surface when one same-version import can overwrite safely."""
        extension_root = self._write_extension()
        service = ExtensionService(self.session)
        service.install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        manifest_path = extension_root / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["description"] = "Updated package payload"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        preview = service.preview_from_path(source_dir=extension_root)

        self.assertEqual(preview.package_id, "@acme/crm")
        self.assertFalse(preview.identical_to_installed)
        self.assertTrue(preview.requires_overwrite_confirmation)
        self.assertEqual(preview.overwrite_blocked_reason, "")
        self.assertIsNotNone(preview.existing_reference_summary)

    def test_install_from_path_overwrites_same_version_after_confirmation(self) -> None:
        """Operators may replace an unreferenced same-version install after confirming."""
        extension_root = self._write_extension()
        service = ExtensionService(self.session)
        installation = service.install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        original_artifact_key = installation.artifact_key
        original_manifest_hash = installation.manifest_hash
        manifest_path = extension_root / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["description"] = "Overwritten package payload"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        overwritten = service.install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
            overwrite_confirmed=True,
        )

        self.assertEqual(overwritten.id, installation.id)
        self.assertNotEqual(overwritten.manifest_hash, original_manifest_hash)
        self.assertNotEqual(overwritten.artifact_key, original_artifact_key)
        self.assertEqual(overwritten.description, "Overwritten package payload")
        self.assertFalse((self.workspace_root / original_artifact_key).exists())

    def test_install_from_path_blocks_overwrite_when_references_exist(self) -> None:
        """Same-version replacement should be rejected while references still exist."""
        extension_root = self._write_extension()
        service = ExtensionService(self.session)
        installation = service.install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        service.upsert_agent_binding(
            agent_id=self.agent.id or 0,
            extension_installation_id=installation.id or 0,
            enabled=True,
        )
        manifest_path = extension_root / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["description"] = "Updated package payload"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            ValueError,
            "still referenced by agent bindings, releases, test snapshots, or saved drafts",
        ):
            service.install_from_path(
                source_dir=extension_root,
                installed_by="alice",
                trust_confirmed=True,
                overwrite_confirmed=True,
            )

    def test_install_from_path_recreates_orphaned_version_directory(self) -> None:
        """A stale local version directory should not block a reinstall after DB reset."""
        extension_root = self._write_extension()
        service = ExtensionService(self.session)

        installation = service.install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        version_root = Path(installation.install_root).parent
        self.session.delete(installation)
        self.session.commit()

        reinstall = service.install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )

        self.assertEqual(reinstall.package_id, "@acme/crm")
        self.assertEqual(reinstall.status, "active")
        self.assertTrue(version_root.joinpath("runtime", "manifest.json").is_file())

    def test_install_bundle_requires_top_level_manifest(self) -> None:
        """Bundle imports should reject archives missing top-level manifest.json."""
        files = [
            ExtensionBundleImportFile(
                relative_path="broken_bundle/tools/search_accounts.py",
                content=b"print('missing manifest')\n",
            )
        ]

        with self.assertRaisesRegex(ValueError, "must contain manifest.json"):
            ExtensionService(self.session).install_bundle(
                bundle_name="broken_bundle",
                files=files,
                installed_by="alice",
                trust_confirmed=True,
            )

    def test_agent_scoped_provider_catalogs_require_the_extension_binding(
        self,
    ) -> None:
        """Agent-scoped catalogs should only expose providers from bound extensions."""
        extension_root = self._write_extension(
            package_name="acme.providers",
            version="1.0.0",
            channel_provider_key="acme@chat",
            web_search_provider_key="acme@search",
        )
        installation = ExtensionService(self.session).install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )

        self.assertEqual(installation.status, "active")

        channel_catalog = ChannelService(self.session).list_catalog()
        self.assertTrue(
            any(
                item["manifest"]["key"] == "acme@chat"
                and item["manifest"]["visibility"] == "extension"
                and item["manifest"]["extension_name"] == "@acme/providers"
                and item["manifest"]["extension_version"] == "1.0.0"
                for item in channel_catalog
            )
        )

        web_search_catalog = WebSearchService(self.session).list_catalog()
        self.assertTrue(
            any(
                item["manifest"]["key"] == "acme@search"
                and item["manifest"]["visibility"] == "extension"
                and item["manifest"]["extension_name"] == "@acme/providers"
                and item["manifest"]["extension_version"] == "1.0.0"
                for item in web_search_catalog
            )
        )

        self.assertFalse(
            any(
                item["manifest"]["key"] == "acme@chat"
                for item in ChannelService(self.session).list_catalog(
                    self.agent.id or 0
                )
            )
        )
        self.assertFalse(
            any(
                item["manifest"]["key"] == "acme@search"
                for item in WebSearchService(self.session).list_catalog(
                    self.agent.id or 0
                )
            )
        )

        ExtensionService(self.session).upsert_agent_binding(
            agent_id=self.agent.id or 0,
            extension_installation_id=installation.id or 0,
            enabled=True,
        )

        self.assertTrue(
            any(
                item["manifest"]["key"] == "acme@chat"
                for item in ChannelService(self.session).list_catalog(
                    self.agent.id or 0
                )
            )
        )
        self.assertTrue(
            any(
                item["manifest"]["key"] == "acme@search"
                for item in WebSearchService(self.session).list_catalog(
                    self.agent.id or 0
                )
            )
        )

        web_search_bindings = WebSearchService(self.session).list_agent_bindings(
            self.agent.id or 0
        )
        self.assertEqual(len(web_search_bindings), 1)
        self.assertEqual(web_search_bindings[0].provider_key, "acme@search")
        self.assertFalse(web_search_bindings[0].enabled)
        self.assertFalse(web_search_bindings[0].effective_enabled)
        seeded_binding = self.session.exec(
            select(AgentWebSearchBinding).where(
                AgentWebSearchBinding.agent_id == (self.agent.id or 0),
                AgentWebSearchBinding.provider_key == "acme@search",
            )
        ).first()
        self.assertIsNotNone(seeded_binding)
        if seeded_binding is None:
            self.fail("Expected seeded web-search binding to exist.")
        seeded_binding.enabled = True
        self.session.add(seeded_binding)
        self.session.commit()

        channel_binding = ChannelService(self.session).create_binding(
            agent_id=self.agent.id or 0,
            channel_key="acme@chat",
            name="Demo Chat",
            enabled=True,
            auth_config={},
            runtime_config={},
        )
        self.assertEqual(channel_binding.channel_key, "acme@chat")
        self.assertEqual(channel_binding.manifest["visibility"], "extension")
        self.assertEqual(channel_binding.manifest["extension_name"], "@acme/providers")
        self.assertEqual(channel_binding.manifest["extension_version"], "1.0.0")

        result = WebSearchService(self.session).execute_search(
            agent_id=self.agent.id or 0,
            request=WebSearchQueryRequest(query="pivot", provider="acme@search"),
        )
        self.assertEqual(result.provider["key"], "acme@search")
        self.assertEqual(result.query, "pivot")

    def test_deleting_agent_extension_binding_cascades_agent_contributions(
        self,
    ) -> None:
        """Removing an extension binding should remove its child agent bindings."""
        extension_root = self._write_extension(
            package_name="acme.providers",
            version="1.0.0",
            channel_provider_key="acme@chat",
            web_search_provider_key="acme@search",
        )
        service = ExtensionService(self.session)
        installation = service.install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        service.upsert_agent_binding(
            agent_id=self.agent.id or 0,
            extension_installation_id=installation.id or 0,
            enabled=True,
        )

        seeded_binding = self.session.exec(
            select(AgentWebSearchBinding).where(
                AgentWebSearchBinding.agent_id == (self.agent.id or 0),
                AgentWebSearchBinding.provider_key == "acme@search",
            )
        ).first()
        self.assertIsNotNone(seeded_binding)
        if seeded_binding is None:
            self.fail("Expected seeded web-search binding to exist.")
        seeded_binding.enabled = True
        self.session.add(seeded_binding)
        self.session.commit()

        channel_binding = ChannelService(self.session).create_binding(
            agent_id=self.agent.id or 0,
            channel_key="acme@chat",
            name="Demo Chat",
            enabled=True,
            auth_config={},
            runtime_config={},
        )
        self.assertEqual(channel_binding.channel_key, "acme@chat")

        service.delete_agent_binding(
            agent_id=self.agent.id or 0,
            extension_installation_id=installation.id or 0,
        )

        self.assertEqual(
            WebSearchService(self.session).list_agent_bindings(self.agent.id or 0),
            [],
        )
        self.assertEqual(
            ChannelService(self.session).list_agent_bindings(self.agent.id or 0),
            [],
        )

    def test_provider_keys_must_use_the_extension_scope_prefix(self) -> None:
        """Extension providers should follow the documented scope@name identity."""
        extension_root = self._write_extension(
            package_name="acme.providers",
            version="1.0.0",
            channel_provider_key="other@chat",
        )

        with self.assertRaisesRegex(
            ValueError,
            "must use the extension scope 'acme' as its prefix",
        ):
            ExtensionService(self.session).install_from_path(
                source_dir=extension_root,
                installed_by="alice",
                trust_confirmed=True,
            )

    def test_repository_sample_extension_installs_and_executes_provider_flow(
        self,
    ) -> None:
        """The documented sample package should stay importable and runnable."""
        sample_root = self._sample_extension_root()
        self.assertTrue(sample_root.joinpath("manifest.json").is_file())

        installation = ExtensionService(self.session).install_from_path(
            source_dir=sample_root,
            installed_by="alice",
            trust_confirmed=True,
        )

        self.assertEqual(installation.package_id, "@acme/providers")
        self.assertEqual(installation.status, "active")

        channel_binding = ChannelService(self.session).create_binding(
            agent_id=self.agent.id or 0,
            channel_key="acme@chat",
            name="Sample Chat",
            enabled=True,
            auth_config={},
            runtime_config={},
        )
        self.assertEqual(channel_binding.channel_key, "acme@chat")

        web_search_binding = WebSearchService(self.session).create_binding(
            agent_id=self.agent.id or 0,
            provider_key="acme@search",
            enabled=True,
            auth_config={},
            runtime_config={},
        )
        self.assertEqual(web_search_binding.provider_key, "acme@search")

        result = WebSearchService(self.session).execute_search(
            agent_id=self.agent.id or 0,
            request=WebSearchQueryRequest(query="pivot", provider="acme@search"),
        )
        self.assertEqual(result.provider["key"], "acme@search")

    def test_provider_resolution_rematerializes_missing_runtime_cache(self) -> None:
        """Provider loading should restore the extracted runtime directory on demand."""
        extension_root = self._write_extension(
            package_name="acme.providers",
            version="1.0.0",
            web_search_provider_key="acme@search",
        )
        service = ExtensionService(self.session)
        installation = service.install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )

        install_root = Path(installation.install_root)
        self.assertTrue(install_root.joinpath("manifest.json").is_file())
        shutil.rmtree(install_root)
        self.assertFalse(install_root.exists())

        catalog = WebSearchService(self.session).list_catalog()

        self.assertTrue(install_root.joinpath("manifest.json").is_file())
        self.assertTrue(
            any(item["manifest"]["key"] == "acme@search" for item in catalog)
        )

    def test_provider_installation_cannot_disable_or_uninstall_while_bound(
        self,
    ) -> None:
        """Provider-backed extensions should protect active agent provider bindings."""
        extension_root = self._write_extension(
            package_name="acme.providers",
            version="1.0.0",
            web_search_provider_key="acme@search",
        )
        service = ExtensionService(self.session)
        installation = service.install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        WebSearchService(self.session).create_binding(
            agent_id=self.agent.id or 0,
            provider_key="acme@search",
            enabled=True,
            auth_config={},
            runtime_config={},
        )

        summary = service.get_reference_summary(installation_id=installation.id or 0)
        self.assertEqual(summary.binding_count, 1)
        self.assertEqual(summary.extension_binding_count, 0)
        self.assertEqual(summary.channel_binding_count, 0)
        self.assertEqual(summary.web_search_binding_count, 1)

        with self.assertRaisesRegex(ValueError, "before disabling this extension"):
            service.set_installation_status(
                installation_id=installation.id or 0,
                status="disabled",
            )

        with self.assertRaisesRegex(ValueError, "before uninstalling this extension"):
            service.uninstall_installation(installation_id=installation.id or 0)

    def test_conflicting_provider_versions_install_disabled_and_require_manual_switch(
        self,
    ) -> None:
        """Conflicting provider keys should keep later installs disabled by default."""
        service = ExtensionService(self.session)
        first_root = self._write_extension(
            package_name="acme.providers",
            version="1.0.0",
            web_search_provider_key="acme@search",
        )
        second_root = self._write_extension(
            package_name="acme.providers",
            version="2.0.0",
            tool_name="search_accounts_v2",
            web_search_provider_key="acme@search",
        )

        first_install = service.install_from_path(
            source_dir=first_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        second_install = service.install_from_path(
            source_dir=second_root,
            installed_by="alice",
            trust_confirmed=True,
        )

        self.assertEqual(first_install.status, "active")
        self.assertEqual(second_install.status, "disabled")

        with self.assertRaisesRegex(ValueError, "conflicts with @acme/providers@1.0.0"):
            service.set_installation_status(
                installation_id=second_install.id or 0,
                status="active",
            )

    def test_disabled_installation_is_excluded_from_runtime_bundle(self) -> None:
        """Disabled installations should not appear in runtime bundle resolution."""
        extension_root = self._write_extension()
        service = ExtensionService(self.session)
        installation = service.install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        service.upsert_agent_binding(
            agent_id=self.agent.id or 0,
            extension_installation_id=installation.id or 0,
            enabled=True,
        )

        service.set_installation_status(
            installation_id=installation.id or 0,
            status="disabled",
        )

        snapshot = AgentSnapshotService(self.session).build_current_snapshot(
            self.agent.id or 0
        )
        self.assertEqual(snapshot["extensions"], [])

    def test_runtime_bundle_rematerializes_missing_extension_cache(self) -> None:
        """Snapshot building should restore tool and skill files from the artifact."""
        extension_root = self._write_extension()
        service = ExtensionService(self.session)
        installation = service.install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        service.upsert_agent_binding(
            agent_id=self.agent.id or 0,
            extension_installation_id=installation.id or 0,
            enabled=True,
        )

        install_root = Path(installation.install_root)
        shutil.rmtree(install_root)
        self.assertFalse(install_root.exists())

        bundle = service.build_agent_extension_snapshot(self.agent.id or 0)

        self.assertTrue(install_root.joinpath("manifest.json").is_file())
        self.assertEqual(len(bundle), 1)
        self.assertTrue(Path(bundle[0]["tools"][0]["source_path"]).is_file())
        self.assertTrue(Path(bundle[0]["skills"][0]["location"]).is_dir())

    def test_reference_summary_counts_pinned_snapshots(self) -> None:
        """Reference summary should count release and snapshot records that pin bundles."""
        extension_root = self._write_extension()
        service = ExtensionService(self.session)
        installation = service.install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        service.upsert_agent_binding(
            agent_id=self.agent.id or 0,
            extension_installation_id=installation.id or 0,
            enabled=True,
        )

        snapshot_payload = AgentSnapshotService(self.session).build_current_snapshot(
            self.agent.id or 0
        )
        snapshot_hash = agent_snapshot_service._hash_payload(snapshot_payload)
        release = AgentRelease(
            agent_id=self.agent.id or 0,
            version=1,
            snapshot_json=json.dumps(snapshot_payload, ensure_ascii=False),
            snapshot_hash=snapshot_hash,
            published_by="alice",
        )
        test_snapshot = AgentTestSnapshot(
            agent_id=self.agent.id or 0,
            snapshot_json=json.dumps(snapshot_payload, ensure_ascii=False),
            snapshot_hash=snapshot_hash,
            workspace_hash="workspace-hash",
            created_by="alice",
        )
        saved_draft = AgentSavedDraft(
            agent_id=self.agent.id or 0,
            snapshot_json=json.dumps(snapshot_payload, ensure_ascii=False),
            snapshot_hash=snapshot_hash,
            saved_by="alice",
        )
        self.session.add(release)
        self.session.add(test_snapshot)
        self.session.add(saved_draft)
        self.session.commit()

        summary = service.get_reference_summary(
            installation_id=installation.id or 0,
        )

        self.assertEqual(summary.binding_count, 1)
        self.assertEqual(summary.extension_binding_count, 1)
        self.assertEqual(summary.channel_binding_count, 0)
        self.assertEqual(summary.web_search_binding_count, 0)
        self.assertEqual(summary.release_count, 1)
        self.assertEqual(summary.test_snapshot_count, 1)
        self.assertEqual(summary.saved_draft_count, 1)

    def test_uninstall_without_references_deletes_installation(self) -> None:
        """Unreferenced installations should be removed physically."""
        extension_root = self._write_extension()
        service = ExtensionService(self.session)
        installation = service.install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )

        install_root = Path(installation.install_root)
        artifact_path = self.workspace_root / Path(installation.artifact_key)
        result = service.uninstall_installation(
            installation_id=installation.id or 0,
        )

        self.assertEqual(result["mode"], "physical")
        self.assertFalse(install_root.exists())
        self.assertFalse(artifact_path.exists())
        self.assertIsNone(service.get_installation(installation.id or 0))

    def test_uninstall_with_binding_falls_back_to_logical_disable(self) -> None:
        """Referenced installations should be disabled instead of deleted."""
        extension_root = self._write_extension()
        service = ExtensionService(self.session)
        installation = service.install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        binding = service.upsert_agent_binding(
            agent_id=self.agent.id or 0,
            extension_installation_id=installation.id or 0,
            enabled=True,
        )

        result = service.uninstall_installation(
            installation_id=installation.id or 0,
        )

        self.assertEqual(result["mode"], "logical")
        refreshed_installation = service.get_installation(installation.id or 0)
        self.assertIsNotNone(refreshed_installation)
        self.assertEqual(refreshed_installation.status, "disabled")
        refreshed_binding = self.session.get(AgentExtensionBinding, binding.id)
        if refreshed_binding is None:
            self.fail("Expected agent-extension binding to remain persisted.")
        self.assertFalse(bool(refreshed_binding.enabled))

    def test_uninstall_with_saved_draft_reference_falls_back_to_logical_disable(
        self,
    ) -> None:
        """Saved drafts should also prevent physical deletion."""
        extension_root = self._write_extension()
        service = ExtensionService(self.session)
        installation = service.install_from_path(
            source_dir=extension_root,
            installed_by="alice",
            trust_confirmed=True,
        )
        binding = service.upsert_agent_binding(
            agent_id=self.agent.id or 0,
            extension_installation_id=installation.id or 0,
            enabled=True,
        )

        AgentSnapshotService(self.session).save_draft(
            self.agent.id or 0,
            saved_by="alice",
        )
        self.session.delete(binding)
        self.session.commit()

        result = service.uninstall_installation(
            installation_id=installation.id or 0,
        )

        self.assertEqual(result["mode"], "logical")
        self.assertEqual(result["references"]["saved_draft_count"], 1)
        refreshed_installation = service.get_installation(installation.id or 0)
        self.assertIsNotNone(refreshed_installation)
        self.assertEqual(refreshed_installation.status, "disabled")


if __name__ == "__main__":
    unittest.main()
