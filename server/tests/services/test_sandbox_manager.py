"""Unit tests for sandbox-manager container recreation decisions."""

from __future__ import annotations

import sys
import tempfile
import unittest
from importlib import import_module
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock, patch

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

sandbox_manager = import_module("sandbox_manager.main")


class SandboxManagerRecreateTestCase(unittest.TestCase):
    """Validate when reusable sandbox containers must be recreated."""

    def test_recreates_container_when_base_image_id_changes(self) -> None:
        """A rebuilt local sandbox image should invalidate reused containers."""
        module = cast(Any, sandbox_manager)
        container = object()

        with (
            patch.object(module, "_container_working_dir", return_value="/workspace"),
            patch.object(
                module,
                "_get_container_mounts",
                return_value=[
                    {"Destination": "/workspace", "Source": "/tmp/workspace"},
                    {"Destination": "/workspace/skills", "Source": "/tmp/skills"},
                ],
            ),
            patch.object(
                module,
                "_container_skills_volume_name",
                return_value="pivot-sandbox-alice-1-skills",
            ),
            patch.object(module, "_container_network_mode", return_value="bridge"),
            patch.object(
                module,
                "_container_image_ref",
                return_value="localhost/pivot-sandbox-base:py311-rg",
            ),
            patch.object(module, "_resolve_image_id", return_value="sha256:new"),
            patch.object(module, "_container_image_id", return_value="sha256:old"),
            patch.object(
                module,
                "get_settings",
                return_value=type(
                    "Settings",
                    (),
                    {
                        "SANDBOX_BASE_IMAGE": "localhost/pivot-sandbox-base:py311-rg",
                        "SANDBOX_NETWORK_MODE": "bridge",
                    },
                )(),
            ),
        ):
            should_recreate, reason = module._should_recreate_container(
                container,
                expected_skills_volume_name="pivot-sandbox-alice-1-skills",
                expected_workspace_mount_source="/tmp/workspace",
            )

        self.assertTrue(should_recreate)
        self.assertEqual(reason, "base_image_id_mismatch")

    def test_keeps_container_when_mounts_and_image_match(self) -> None:
        """Healthy sandboxes should stay warm instead of being recreated."""
        module = cast(Any, sandbox_manager)
        container = object()

        with (
            patch.object(module, "_container_working_dir", return_value="/workspace"),
            patch.object(
                module,
                "_get_container_mounts",
                return_value=[
                    {"Destination": "/workspace", "Source": "/tmp/workspace"},
                    {"Destination": "/workspace/skills", "Source": "/tmp/skills"},
                ],
            ),
            patch.object(
                module,
                "_container_skills_volume_name",
                return_value="pivot-sandbox-alice-1-skills",
            ),
            patch.object(module, "_container_network_mode", return_value="bridge"),
            patch.object(
                module,
                "_container_image_ref",
                return_value="localhost/pivot-sandbox-base:py311-rg",
            ),
            patch.object(module, "_resolve_image_id", return_value="sha256:current"),
            patch.object(module, "_container_image_id", return_value="sha256:current"),
            patch.object(
                module,
                "get_settings",
                return_value=type(
                    "Settings",
                    (),
                    {
                        "SANDBOX_BASE_IMAGE": "localhost/pivot-sandbox-base:py311-rg",
                        "SANDBOX_NETWORK_MODE": "bridge",
                    },
                )(),
            ),
        ):
            should_recreate, reason = module._should_recreate_container(
                container,
                expected_skills_volume_name="pivot-sandbox-alice-1-skills",
                expected_workspace_mount_source="/tmp/workspace",
            )

        self.assertFalse(should_recreate)
        self.assertEqual(reason, "ok")

    def test_recreates_container_when_network_mode_changes(self) -> None:
        """Changing sandbox network policy should refresh warm containers."""
        module = cast(Any, sandbox_manager)
        container = object()

        with (
            patch.object(module, "_container_working_dir", return_value="/workspace"),
            patch.object(
                module,
                "_get_container_mounts",
                return_value=[
                    {"Destination": "/workspace", "Source": "/tmp/workspace"},
                    {"Destination": "/workspace/skills", "Source": "/tmp/skills"},
                ],
            ),
            patch.object(
                module,
                "_container_skills_volume_name",
                return_value="pivot-sandbox-alice-1-skills",
            ),
            patch.object(module, "_container_network_mode", return_value="none"),
            patch.object(
                module,
                "_container_image_ref",
                return_value="localhost/pivot-sandbox-base:py311-rg",
            ),
            patch.object(module, "_resolve_image_id", return_value="sha256:current"),
            patch.object(module, "_container_image_id", return_value="sha256:current"),
            patch.object(
                module,
                "get_settings",
                return_value=type(
                    "Settings",
                    (),
                    {
                        "SANDBOX_BASE_IMAGE": "localhost/pivot-sandbox-base:py311-rg",
                        "SANDBOX_NETWORK_MODE": "bridge",
                    },
                )(),
            ),
        ):
            should_recreate, reason = module._should_recreate_container(
                container,
                expected_skills_volume_name="pivot-sandbox-alice-1-skills",
                expected_workspace_mount_source="/tmp/workspace",
            )

        self.assertTrue(should_recreate)
        self.assertEqual(reason, "network_mode_mismatch")

    def test_recreates_container_when_skills_volume_mount_is_missing(self) -> None:
        """Legacy sandboxes without the private skills volume must be replaced."""
        module = cast(Any, sandbox_manager)
        container = object()

        with (
            patch.object(module, "_container_working_dir", return_value="/workspace"),
            patch.object(
                module,
                "_get_container_mounts",
                return_value=[
                    {"Destination": "/workspace", "Source": "/tmp/workspace"}
                ],
            ),
            patch.object(module, "_container_skills_volume_name", return_value=None),
            patch.object(module, "_container_network_mode", return_value="bridge"),
            patch.object(
                module,
                "_container_image_ref",
                return_value="localhost/pivot-sandbox-base:py311-rg",
            ),
            patch.object(module, "_resolve_image_id", return_value="sha256:current"),
            patch.object(module, "_container_image_id", return_value="sha256:current"),
            patch.object(
                module,
                "get_settings",
                return_value=type(
                    "Settings",
                    (),
                    {
                        "SANDBOX_BASE_IMAGE": "localhost/pivot-sandbox-base:py311-rg",
                        "SANDBOX_NETWORK_MODE": "bridge",
                    },
                )(),
            ),
        ):
            should_recreate, reason = module._should_recreate_container(
                container,
                expected_skills_volume_name="pivot-sandbox-alice-1-skills",
                expected_workspace_mount_source="/tmp/workspace",
            )

        self.assertTrue(should_recreate)
        self.assertEqual(reason, "missing_skills_volume_mount")

    def test_recreates_container_when_legacy_skill_bind_mounts_exist(self) -> None:
        """Legacy per-skill bind mounts should be replaced by materialized drafts."""
        module = cast(Any, sandbox_manager)
        container = object()

        with (
            patch.object(module, "_container_working_dir", return_value="/workspace"),
            patch.object(
                module,
                "_get_container_mounts",
                return_value=[
                    {"Destination": "/workspace", "Source": "/tmp/workspace"},
                    {"Destination": "/workspace/skills", "Source": "/tmp/skills"},
                    {
                        "Destination": "/workspace/skills/research-notes",
                        "Source": "/tmp/canonical-skill",
                    },
                ],
            ),
            patch.object(
                module,
                "_container_skills_volume_name",
                return_value="pivot-sandbox-alice-1-skills",
            ),
            patch.object(module, "_container_network_mode", return_value="bridge"),
            patch.object(
                module,
                "_container_image_ref",
                return_value="localhost/pivot-sandbox-base:py311-rg",
            ),
            patch.object(module, "_resolve_image_id", return_value="sha256:current"),
            patch.object(module, "_container_image_id", return_value="sha256:current"),
            patch.object(
                module,
                "get_settings",
                return_value=type(
                    "Settings",
                    (),
                    {
                        "SANDBOX_BASE_IMAGE": "localhost/pivot-sandbox-base:py311-rg",
                        "SANDBOX_NETWORK_MODE": "bridge",
                    },
                )(),
            ),
        ):
            should_recreate, reason = module._should_recreate_container(
                container,
                expected_skills_volume_name="pivot-sandbox-alice-1-skills",
                expected_workspace_mount_source="/tmp/workspace",
            )

        self.assertTrue(should_recreate)
        self.assertEqual(reason, "legacy_skill_bind_mount")

    def test_recreates_container_when_workspace_mount_source_changes(self) -> None:
        """Warm sandboxes must be replaced when the workspace bind source drifts."""
        module = cast(Any, sandbox_manager)
        container = object()

        with (
            patch.object(module, "_container_working_dir", return_value="/workspace"),
            patch.object(
                module,
                "_get_container_mounts",
                return_value=[
                    {
                        "Destination": "/workspace",
                        "Source": "/tmp/legacy-workspace",
                    },
                    {"Destination": "/workspace/skills", "Source": "/tmp/skills"},
                ],
            ),
            patch.object(
                module,
                "_container_skills_volume_name",
                return_value="pivot-sandbox-alice-1-skills",
            ),
            patch.object(module, "_container_network_mode", return_value="bridge"),
            patch.object(
                module,
                "_container_image_ref",
                return_value="localhost/pivot-sandbox-base:py311-rg",
            ),
            patch.object(module, "_resolve_image_id", return_value="sha256:current"),
            patch.object(module, "_container_image_id", return_value="sha256:current"),
            patch.object(
                module,
                "get_settings",
                return_value=type(
                    "Settings",
                    (),
                    {
                        "SANDBOX_BASE_IMAGE": "localhost/pivot-sandbox-base:py311-rg",
                        "SANDBOX_NETWORK_MODE": "bridge",
                    },
                )(),
            ),
        ):
            should_recreate, reason = module._should_recreate_container(
                container,
                expected_skills_volume_name="pivot-sandbox-alice-1-skills",
                expected_workspace_mount_source="/var/lib/pivot/seaweedfs-mnt/users/alice/ws-1",
            )

        self.assertTrue(should_recreate)
        self.assertEqual(reason, "workspace_mount_source_mismatch")

    def test_materialize_runtime_skills_preserves_existing_allowed_drafts(self) -> None:
        """Materialization should only add missing skills and remove stale ones."""
        module = cast(Any, sandbox_manager)
        container = object()

        with (
            patch.object(
                module,
                "_list_runtime_skill_names",
                return_value={"existing-skill", "stale-skill"},
            ),
            patch.object(module, "_remove_runtime_skills") as remove_mock,
            patch.object(
                module,
                "_export_backend_skill_archive",
                return_value=b"archive-bytes",
            ) as export_mock,
            patch.object(module, "_copy_skill_archive_into_container") as copy_mock,
        ):
            module._materialize_runtime_skills(
                container=container,
                skills=[
                    {
                        "name": "existing-skill",
                        "canonical_location": "/app/server/workspace/skills/existing-skill",
                    },
                    {
                        "name": "new-skill",
                        "canonical_location": "/app/server/workspace/skills/new-skill",
                    },
                ],
            )

        remove_mock.assert_called_once_with(container, {"stale-skill"})
        export_mock.assert_called_once_with(
            skill_name="new-skill",
            backend_location="/app/server/workspace/skills/new-skill",
        )
        copy_mock.assert_called_once_with(
            container=container,
            skill_name="new-skill",
            archive_bytes=b"archive-bytes",
        )


class SandboxManagerPoolCleanupTestCase(unittest.TestCase):
    """Validate proactive cleanup of stale warm sandbox containers."""

    def test_cleanup_pool_removes_incompatible_warm_container(self) -> None:
        """Pool cleanup should evict stale warm sandboxes before they are reused."""
        module = cast(Any, sandbox_manager)
        container = object()
        driver = Mock()
        driver.build_workspace_bind.return_value = module.RuntimeBind(
            source="/expected/workspace",
            destination="/workspace",
        )

        with (
            patch.dict(
                module._last_used_by_name,
                {"pivot-sandbox-alice-1": 1.0},
                clear=True,
            ),
            patch.object(module, "_find_container", return_value=container),
            patch.object(
                module,
                "_container_workspace_contract",
                return_value=("seaweedfs", "users/alice/ws-1", "live_sync"),
            ),
            patch.object(
                module,
                "_container_skills_volume_name",
                return_value="pivot-sandbox-alice-1-skills",
            ),
            patch.object(module, "_workspace_runtime_driver", return_value=driver),
            patch.object(
                module,
                "_should_recreate_container",
                return_value=(True, "workspace_mount_source_mismatch"),
            ) as recreate_mock,
            patch.object(module, "_remove_container_fast") as remove_mock,
            patch.object(module.time, "time", return_value=2.0),
            patch.object(
                module,
                "get_settings",
                return_value=type(
                    "Settings",
                    (),
                    {
                        "SANDBOX_POOL_IDLE_TTL_SECONDS": 86400,
                        "SANDBOX_POOL_MAX_SIZE": 100,
                    },
                )(),
            ),
        ):
            module._cleanup_pool_once()

        recreate_mock.assert_called_once_with(
            container,
            expected_skills_volume_name="pivot-sandbox-alice-1-skills",
            expected_workspace_mount_source="/expected/workspace",
        )
        remove_mock.assert_called_once_with(
            container,
            reason="pool_compatibility:workspace_mount_source_mismatch",
            remove_skills_volume=True,
        )
        self.assertNotIn("pivot-sandbox-alice-1", module._last_used_by_name)


class SandboxManagerWorkspaceDriverTestCase(unittest.TestCase):
    """Validate workspace runtime driver selection and bind preparation."""

    def test_workspace_runtime_driver_selects_expected_backend(self) -> None:
        """Driver selection should stay deterministic for supported backends."""
        module = cast(Any, sandbox_manager)
        module._workspace_runtime_driver.cache_clear()

        local_driver = module._workspace_runtime_driver("local_fs")
        seaweedfs_driver = module._workspace_runtime_driver("seaweedfs")

        self.assertEqual(local_driver.__class__.__name__, "LocalFilesystemWorkspaceDriver")
        self.assertEqual(seaweedfs_driver.__class__.__name__, "SeaweedfsWorkspaceDriver")

    def test_workspace_runtime_driver_rejects_unknown_backend(self) -> None:
        """Unsupported backends should fail fast at the manager boundary."""
        module = cast(Any, sandbox_manager)
        module._workspace_runtime_driver.cache_clear()

        with self.assertRaises(module.HTTPException):
            module._workspace_runtime_driver("mysteryfs")

    def test_seaweedfs_driver_builds_runtime_bind_from_compatibility_path(self) -> None:
        """The phase-1 SeaweedFS driver should return a helper-visible workspace bind."""
        module = cast(Any, sandbox_manager)
        driver = module.SeaweedfsWorkspaceDriver()

        with patch.object(
            module,
            "_resolve_host_path_from_backend_compat_path",
            return_value="/tmp/users/alice/ws-1",
        ):
            bind = driver.build_workspace_bind(
                "users/alice/agents/7/sessions/workspace-1",
                "live_sync",
            )

        self.assertEqual(bind.source, "/tmp/users/alice/ws-1")
        self.assertEqual(bind.destination, "/workspace")
        self.assertEqual(bind.mode, "rw")

    def test_seaweedfs_driver_ensures_filer_reachable_and_mount_root(self) -> None:
        """Compose-compat readiness should validate filer access and mount root."""
        module = cast(Any, sandbox_manager)
        driver = module.SeaweedfsWorkspaceDriver()

        with (
            patch.object(module, "_assert_service_reachable") as reachable_mock,
            patch.object(module.Path, "mkdir") as mkdir_mock,
            patch.object(
                module,
                "get_settings",
                return_value=type(
                    "Settings",
                    (),
                    {
                        "SANDBOX_SEAWEEDFS_ATTACH_STRATEGY": "compose_compat",
                        "SANDBOX_SEAWEEDFS_FILER_URL": "http://seaweedfs:8888",
                        "SANDBOX_SEAWEEDFS_MOUNT_ROOT": "/var/lib/pivot/seaweedfs-mnt",
                    },
                )(),
            ),
        ):
            driver.ensure_runtime_ready()

        reachable_mock.assert_called_once_with(
            "http://seaweedfs:8888",
            label="SeaweedFS filer",
        )
        mkdir_mock.assert_called_once_with(
            exist_ok=True,
            parents=True,
        )

    def test_seaweedfs_driver_shared_mount_root_checks_filer_and_mount_root(self) -> None:
        """Shared-root mode should still verify filer reachability for hydration."""
        module = cast(Any, sandbox_manager)
        driver = module.SeaweedfsWorkspaceDriver()

        with (
            patch.object(module, "_assert_service_reachable") as reachable_mock,
            patch.object(module.Path, "mkdir") as mkdir_mock,
            patch.object(
                module,
                "get_settings",
                return_value=type(
                    "Settings",
                    (),
                    {
                        "SANDBOX_SEAWEEDFS_ATTACH_STRATEGY": "shared_mount_root",
                        "SANDBOX_SEAWEEDFS_REQUIRE_NATIVE_MOUNT": False,
                        "SANDBOX_SEAWEEDFS_FILER_URL": "http://seaweedfs:8888",
                        "SANDBOX_SEAWEEDFS_MOUNT_ROOT": "/var/lib/pivot/seaweedfs-mnt",
                    },
                )(),
            ),
        ):
            driver.ensure_runtime_ready()

        reachable_mock.assert_called_once_with(
            "http://seaweedfs:8888",
            label="SeaweedFS filer",
        )
        mkdir_mock.assert_called_once_with(
            exist_ok=True,
            parents=True,
        )

    def test_seaweedfs_driver_shared_mount_root_builds_bind_from_mount_root(self) -> None:
        """Shared-root mode should bind directly from the prepared helper root."""
        module = cast(Any, sandbox_manager)
        driver = module.SeaweedfsWorkspaceDriver()

        with (
            patch.object(
                module,
                "_resolve_host_path_from_self_container_path",
                return_value=(
                    "/var/home/core/.local/share/containers/storage/volumes/"
                    "pivot_seaweedfs_mount_root/_data/users/alice/agents/7/"
                    "sessions/workspace-1"
                ),
            ),
            patch.object(
                module,
                "get_settings",
                return_value=type(
                    "Settings",
                    (),
                    {
                        "SANDBOX_SEAWEEDFS_ATTACH_STRATEGY": "shared_mount_root",
                        "SANDBOX_SEAWEEDFS_REQUIRE_NATIVE_MOUNT": False,
                        "SANDBOX_SEAWEEDFS_MOUNT_ROOT": "/var/lib/pivot/seaweedfs-mnt",
                    },
                )(),
            ),
        ):
            bind = driver.build_workspace_bind(
                "users/alice/agents/7/sessions/workspace-1",
                "live_sync",
            )

        self.assertEqual(
            bind.source,
            "/var/home/core/.local/share/containers/storage/volumes/"
            "pivot_seaweedfs_mount_root/_data/users/alice/agents/7/"
            "sessions/workspace-1",
        )
        self.assertEqual(bind.destination, "/workspace")
        self.assertEqual(bind.mode, "rw")

    def test_seaweedfs_driver_shared_mount_root_native_mount_skips_bridge_sync(
        self,
    ) -> None:
        """Real shared mounts should not hydrate through the filer bridge."""
        module = cast(Any, sandbox_manager)
        driver = module.SeaweedfsWorkspaceDriver()

        with tempfile.TemporaryDirectory() as temp_dir:
            local_dir = Path(temp_dir)
            with (
                patch.object(
                    module.SeaweedfsWorkspaceDriver,
                    "_shared_mount_root_host_path",
                    return_value="/host/seaweedfs-root",
                ),
                patch.object(module.os.path, "ismount", return_value=True),
                patch.object(
                    module.SeaweedfsWorkspaceDriver,
                    "_shared_mount_root_dir",
                    return_value=local_dir,
                ),
                patch.object(module, "_seaweedfs_directory_has_entries") as remote_mock,
                patch.object(module, "_sync_local_workspace_from_seaweedfs") as hydrate_mock,
                patch.object(module, "_sync_local_workspace_to_seaweedfs") as seed_mock,
                patch.object(
                    module,
                    "get_settings",
                    return_value=type(
                        "Settings",
                        (),
                        {
                            "SANDBOX_SEAWEEDFS_ATTACH_STRATEGY": "shared_mount_root",
                            "SANDBOX_SEAWEEDFS_REQUIRE_NATIVE_MOUNT": False,
                            "SANDBOX_SEAWEEDFS_FILER_URL": "http://seaweedfs:8888",
                            "SANDBOX_SEAWEEDFS_MOUNT_ROOT": "/var/lib/pivot/seaweedfs-mnt",
                        },
                    )(),
                ),
            ):
                driver.ensure_workspace_ready("users/alice/ws-1", "live_sync")

        remote_mock.assert_not_called()
        hydrate_mock.assert_not_called()
        seed_mock.assert_not_called()

    def test_seaweedfs_driver_shared_mount_root_native_mount_skips_flush(self) -> None:
        """Real shared mounts should not mirror back through the filer bridge."""
        module = cast(Any, sandbox_manager)
        driver = module.SeaweedfsWorkspaceDriver()

        with (
            patch.object(
                module.SeaweedfsWorkspaceDriver,
                "_shared_mount_root_host_path",
                return_value="/host/seaweedfs-root",
            ),
            patch.object(module.os.path, "ismount", return_value=True),
            patch.object(module, "_sync_local_workspace_to_seaweedfs") as sync_mock,
            patch.object(
                module,
                "get_settings",
                return_value=type(
                    "Settings",
                    (),
                    {
                        "SANDBOX_SEAWEEDFS_ATTACH_STRATEGY": "shared_mount_root",
                        "SANDBOX_SEAWEEDFS_REQUIRE_NATIVE_MOUNT": False,
                        "SANDBOX_SEAWEEDFS_FILER_URL": "http://seaweedfs:8888",
                        "SANDBOX_SEAWEEDFS_MOUNT_ROOT": "/var/lib/pivot/seaweedfs-mnt",
                    },
                )(),
            ),
        ):
            driver.sync_workspace("users/alice/ws-1", "live_sync")

        sync_mock.assert_not_called()

    def test_seaweedfs_driver_shared_mount_root_requires_native_mount_when_enabled(
        self,
    ) -> None:
        """Strict shared-root mode should fail fast when no native mount exists."""
        module = cast(Any, sandbox_manager)
        driver = module.SeaweedfsWorkspaceDriver()

        with (
            patch.object(
                module.SeaweedfsWorkspaceDriver,
                "_shared_mount_root_host_path",
                return_value="/host/seaweedfs-root",
            ),
            patch.object(module.os.path, "ismount", return_value=False),
            patch.object(module, "_seaweedfs_directory_has_entries") as remote_mock,
            patch.object(module, "_sync_local_workspace_from_seaweedfs") as hydrate_mock,
            patch.object(module, "_sync_local_workspace_to_seaweedfs") as seed_mock,
            patch.object(
                module,
                "get_settings",
                return_value=type(
                    "Settings",
                    (),
                    {
                        "SANDBOX_SEAWEEDFS_ATTACH_STRATEGY": "shared_mount_root",
                        "SANDBOX_SEAWEEDFS_REQUIRE_NATIVE_MOUNT": True,
                        "SANDBOX_SEAWEEDFS_FILER_URL": "http://seaweedfs:8888",
                        "SANDBOX_SEAWEEDFS_MOUNT_ROOT": "/var/lib/pivot/seaweedfs-mnt",
                    },
                )(),
            ),
            self.assertRaises(module.HTTPException),
        ):
            driver.ensure_workspace_ready("users/alice/ws-1", "live_sync")

        remote_mock.assert_not_called()
        hydrate_mock.assert_not_called()
        seed_mock.assert_not_called()

    def test_seaweedfs_driver_hydrates_empty_compat_cache_from_filer(self) -> None:
        """Compose-compat workspaces should hydrate local cache from SeaweedFS."""
        module = cast(Any, sandbox_manager)
        driver = module.SeaweedfsWorkspaceDriver()

        with tempfile.TemporaryDirectory() as temp_dir:
            local_dir = Path(temp_dir)
            with (
                patch.object(module, "_ensure_workspace_compat_directory"),
                patch.object(
                    module,
                    "_workspace_backend_compat_path_from_contract",
                    return_value=str(local_dir),
                ),
                patch.object(module, "_seaweedfs_directory_has_entries", return_value=True),
                patch.object(module, "_sync_local_workspace_from_seaweedfs") as hydrate_mock,
                patch.object(module, "_sync_local_workspace_to_seaweedfs") as seed_mock,
                patch.object(
                    module,
                    "get_settings",
                    return_value=type(
                        "Settings",
                        (),
                        {
                            "SANDBOX_SEAWEEDFS_ATTACH_STRATEGY": "compose_compat",
                            "SANDBOX_SEAWEEDFS_REQUIRE_NATIVE_MOUNT": False,
                            "SANDBOX_SEAWEEDFS_FILER_URL": "http://seaweedfs:8888",
                            "SANDBOX_SEAWEEDFS_MOUNT_ROOT": "/var/lib/pivot/seaweedfs-mnt",
                        },
                    )(),
                ),
            ):
                driver.ensure_workspace_ready("users/alice/ws-1", "live_sync")

        hydrate_mock.assert_called_once_with(
            filer_url="http://seaweedfs:8888",
            logical_path="users/alice/ws-1",
            local_dir=local_dir,
        )
        seed_mock.assert_not_called()

    def test_seaweedfs_driver_seeds_empty_remote_from_non_empty_cache(self) -> None:
        """Compose-compat should treat an existing local cache as seed data."""
        module = cast(Any, sandbox_manager)
        driver = module.SeaweedfsWorkspaceDriver()

        with tempfile.TemporaryDirectory() as temp_dir:
            local_dir = Path(temp_dir)
            (local_dir / "README.md").write_text("hello", encoding="utf-8")
            with (
                patch.object(module, "_ensure_workspace_compat_directory"),
                patch.object(
                    module,
                    "_workspace_backend_compat_path_from_contract",
                    return_value=str(local_dir),
                ),
                patch.object(module, "_seaweedfs_directory_has_entries", return_value=False),
                patch.object(module, "_sync_local_workspace_from_seaweedfs") as hydrate_mock,
                patch.object(module, "_sync_local_workspace_to_seaweedfs") as seed_mock,
                patch.object(
                    module,
                    "get_settings",
                    return_value=type(
                        "Settings",
                        (),
                        {
                            "SANDBOX_SEAWEEDFS_ATTACH_STRATEGY": "compose_compat",
                            "SANDBOX_SEAWEEDFS_REQUIRE_NATIVE_MOUNT": False,
                            "SANDBOX_SEAWEEDFS_FILER_URL": "http://seaweedfs:8888",
                            "SANDBOX_SEAWEEDFS_MOUNT_ROOT": "/var/lib/pivot/seaweedfs-mnt",
                        },
                    )(),
                ),
            ):
                driver.ensure_workspace_ready("users/alice/ws-1", "live_sync")

        hydrate_mock.assert_not_called()
        seed_mock.assert_called_once_with(
            filer_url="http://seaweedfs:8888",
            logical_path="users/alice/ws-1",
            local_dir=local_dir,
        )

    def test_seaweedfs_driver_skips_sync_for_non_live_mount_mode(self) -> None:
        """Only live-sync mounts should flush local cache back into SeaweedFS."""
        module = cast(Any, sandbox_manager)
        driver = module.SeaweedfsWorkspaceDriver()

        with tempfile.TemporaryDirectory() as temp_dir:
            local_dir = Path(temp_dir)
            with (
                patch.object(
                    module,
                    "_workspace_backend_compat_path_from_contract",
                    return_value=str(local_dir),
                ),
                patch.object(module, "_sync_local_workspace_to_seaweedfs") as sync_mock,
                patch.object(
                    module,
                    "get_settings",
                    return_value=type(
                        "Settings",
                        (),
                        {
                            "SANDBOX_SEAWEEDFS_ATTACH_STRATEGY": "compose_compat",
                            "SANDBOX_SEAWEEDFS_REQUIRE_NATIVE_MOUNT": False,
                            "SANDBOX_SEAWEEDFS_FILER_URL": "http://seaweedfs:8888",
                            "SANDBOX_SEAWEEDFS_MOUNT_ROOT": "/var/lib/pivot/seaweedfs-mnt",
                        },
                    )(),
                ),
            ):
                driver.sync_workspace(
                    "users/alice/ws-1",
                    "detached_clone",
                )

        sync_mock.assert_not_called()

    def test_seaweedfs_runtime_status_reports_shared_mount_root_state(self) -> None:
        """Runtime status should show native mount and resolved host path."""
        module = cast(Any, sandbox_manager)

        with (
            patch.object(module, "_assert_service_reachable"),
            patch.object(
                module,
                "_resolve_host_path_from_self_container_path",
                return_value="/host/seaweedfs-root",
            ),
            patch.object(
                module.os.path,
                "ismount",
                side_effect=lambda path: path == "/host/seaweedfs-root",
            ),
            patch.object(
                module,
                "get_settings",
                return_value=type(
                    "Settings",
                    (),
                    {
                        "SANDBOX_SEAWEEDFS_ATTACH_STRATEGY": "shared_mount_root",
                        "SANDBOX_SEAWEEDFS_REQUIRE_NATIVE_MOUNT": False,
                        "SANDBOX_SEAWEEDFS_FILER_URL": "http://seaweedfs:8888",
                        "SANDBOX_SEAWEEDFS_MOUNT_ROOT": "/var/lib/pivot/seaweedfs-mnt",
                    },
                )(),
            ),
        ):
            status = module._seaweedfs_runtime_status()

        self.assertEqual(status.attach_strategy, "shared_mount_root")
        self.assertFalse(status.native_mount_required)
        self.assertTrue(status.filer_reachable)
        self.assertTrue(status.native_mount_active)
        self.assertFalse(status.fallback_bridge_active)
        self.assertEqual(status.mount_root_host_path, "/host/seaweedfs-root")

    def test_seaweedfs_runtime_status_reports_bridge_fallback_when_filer_unreachable(
        self,
    ) -> None:
        """Runtime status should expose when the manager is still on bridge mode."""
        module = cast(Any, sandbox_manager)

        with (
            patch.object(
                module,
                "_assert_service_reachable",
                side_effect=module.HTTPException(
                    status_code=500,
                    detail="SeaweedFS filer is unreachable.",
                ),
            ),
            patch.object(
                module,
                "get_settings",
                return_value=type(
                    "Settings",
                    (),
                    {
                        "SANDBOX_SEAWEEDFS_ATTACH_STRATEGY": "compose_compat",
                        "SANDBOX_SEAWEEDFS_REQUIRE_NATIVE_MOUNT": False,
                        "SANDBOX_SEAWEEDFS_FILER_URL": "http://seaweedfs:8888",
                        "SANDBOX_SEAWEEDFS_MOUNT_ROOT": "/var/lib/pivot/seaweedfs-mnt",
                    },
                )(),
            ),
        ):
            status = module._seaweedfs_runtime_status()

        self.assertEqual(status.attach_strategy, "compose_compat")
        self.assertFalse(status.native_mount_required)
        self.assertFalse(status.filer_reachable)
        self.assertFalse(status.native_mount_active)
        self.assertTrue(status.fallback_bridge_active)
        self.assertIsNone(status.mount_root_host_path)

    def test_sync_local_workspace_from_seaweedfs_removes_stale_local_files(self) -> None:
        """Hydration should mirror remote files and prune missing local files."""
        module = cast(Any, sandbox_manager)
        bridge = module.seaweedfs_bridge

        with tempfile.TemporaryDirectory() as temp_dir:
            local_dir = Path(temp_dir)
            stale_path = local_dir / "stale.txt"
            stale_path.write_text("stale", encoding="utf-8")
            keep_path = local_dir / "keep.txt"
            keep_path.write_text("remote-copy", encoding="utf-8")

            response = Mock()
            response.raise_for_status.return_value = None
            response.content = b"remote-copy"
            with (
                patch.object(
                    bridge,
                    "_seaweedfs_walk_files",
                    return_value={
                        "users/alice/ws-1/keep.txt": {
                            "Md5": "same-digest",
                        }
                    },
                ),
                patch.object(bridge, "_file_md5_hex", return_value="same-digest"),
                patch.object(bridge.requests, "get", return_value=response) as get_mock,
            ):
                bridge._sync_local_workspace_from_seaweedfs(
                    filer_url="http://seaweedfs:8888",
                    logical_path="users/alice/ws-1",
                    local_dir=local_dir,
                )

            self.assertFalse(stale_path.exists())
            self.assertTrue(keep_path.exists())
            get_mock.assert_not_called()

    def test_sync_local_workspace_to_seaweedfs_only_updates_changed_files(self) -> None:
        """Flush should avoid full recursive delete and only touch changed files."""
        module = cast(Any, sandbox_manager)
        bridge = module.seaweedfs_bridge

        with tempfile.TemporaryDirectory() as temp_dir:
            local_dir = Path(temp_dir)
            unchanged_path = local_dir / "keep.txt"
            unchanged_path.write_text("same", encoding="utf-8")
            changed_path = local_dir / "changed.txt"
            changed_path.write_text("new", encoding="utf-8")

            put_response = Mock()
            put_response.raise_for_status.return_value = None
            delete_response = Mock()
            delete_response.status_code = 204
            delete_response.raise_for_status.return_value = None
            with (
                patch.object(
                    bridge,
                    "_seaweedfs_walk_files",
                    return_value={
                        "users/alice/ws-1/keep.txt": {
                            "Md5": "same-digest",
                        },
                        "users/alice/ws-1/stale.txt": {
                            "Md5": "stale-digest",
                        },
                        "users/alice/ws-1/changed.txt": {
                            "Md5": "old-digest",
                        },
                    },
                ),
                patch.object(
                    bridge,
                    "_file_md5_hex",
                    side_effect=lambda path: (
                        "same-digest" if path == unchanged_path else "new-digest"
                    ),
                ),
                patch.object(bridge.requests, "put", return_value=put_response) as put_mock,
                patch.object(
                    bridge.requests,
                    "delete",
                    return_value=delete_response,
                ) as delete_mock,
            ):
                bridge._sync_local_workspace_to_seaweedfs(
                    filer_url="http://seaweedfs:8888",
                    logical_path="users/alice/ws-1",
                    local_dir=local_dir,
                )

            put_mock.assert_called_once()
            put_url = put_mock.call_args.args[0]
            self.assertTrue(put_url.endswith("/users/alice/ws-1/changed.txt"))
            delete_mock.assert_called_once()
            delete_url = delete_mock.call_args.args[0]
            self.assertTrue(delete_url.endswith("/users/alice/ws-1/stale.txt"))


class SandboxManagerWorkspaceSyncLifecycleTestCase(unittest.TestCase):
    """Validate workspace sync timing around sandbox exec and destroy calls."""

    def test_destroy_sandbox_syncs_workspace_before_removal(self) -> None:
        """Destroy should flush the workspace cache before removing the sandbox."""
        module = cast(Any, sandbox_manager)
        payload = module.SandboxRequest(
            username="alice",
            workspace_id="ws-1",
            storage_backend="seaweedfs",
            logical_path="users/alice/ws-1",
            mount_mode="live_sync",
        )
        container = object()
        driver = Mock()

        with (
            patch.object(module, "_find_container", return_value=container),
            patch.object(module, "_workspace_runtime_driver", return_value=driver),
            patch.object(module, "_remove_container_fast") as remove_mock,
        ):
            response = module.destroy_sandbox(payload)

        driver.sync_workspace.assert_called_once_with(
            "users/alice/ws-1",
            "live_sync",
        )
        remove_mock.assert_called_once_with(
            container,
            reason="destroy_api",
            remove_skills_volume=True,
        )
        self.assertEqual(response["status"], "destroyed")

    def test_exec_in_sandbox_syncs_workspace_after_command(self) -> None:
        """Successful execs should flush workspace mutations back to SeaweedFS."""
        module = cast(Any, sandbox_manager)
        payload = module.SandboxExecRequest(
            username="alice",
            workspace_id="ws-1",
            storage_backend="seaweedfs",
            logical_path="users/alice/ws-1",
            mount_mode="live_sync",
            cmd=["python3", "-c", "print('ok')"],
        )
        container = Mock()
        container.exec_run.return_value = (0, (b"ok\n", b""))
        driver = Mock()

        with (
            patch.object(module, "_ensure_sandbox", return_value=container),
            patch.object(module, "_workspace_runtime_driver", return_value=driver),
        ):
            response = module.exec_in_sandbox(payload)

        driver.sync_workspace.assert_called_once_with(
            "users/alice/ws-1",
            "live_sync",
        )
        self.assertEqual(response.exit_code, 0)
        self.assertEqual(response.stdout, "ok\n")
