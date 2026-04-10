"""Unit tests for sandbox-manager container recreation decisions."""

from __future__ import annotations

import sys
import unittest
from importlib import import_module
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

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
            patch.object(module, "_mounted_skill_sources", return_value={}),
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
                {},
                expected_skills_volume_name="pivot-sandbox-alice-1-skills",
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
            patch.object(module, "_mounted_skill_sources", return_value={}),
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
                {},
                expected_skills_volume_name="pivot-sandbox-alice-1-skills",
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
            patch.object(module, "_mounted_skill_sources", return_value={}),
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
                {},
                expected_skills_volume_name="pivot-sandbox-alice-1-skills",
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
            patch.object(module, "_mounted_skill_sources", return_value={}),
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
                {},
                expected_skills_volume_name="pivot-sandbox-alice-1-skills",
            )

        self.assertTrue(should_recreate)
        self.assertEqual(reason, "missing_skills_volume_mount")


class SandboxManagerWorkspaceRootTestCase(unittest.TestCase):
    """Validate configurable backend workspace root handling."""

    def test_ensure_workspace_dir_rejects_paths_outside_configured_root(self) -> None:
        """Sandbox creation should reject backend paths that escape the root."""
        module = cast(Any, sandbox_manager)

        with (
            patch.object(
                module,
                "get_settings",
                return_value=type(
                    "Settings",
                    (),
                    {
                        "SANDBOX_BACKEND_WORKSPACE_ROOT": "/srv/pivot-workspaces",
                        "SANDBOX_EXTERNAL_POSIX_ROOT": None,
                    },
                )(),
            ),
            self.assertRaisesRegex(Exception, "/srv/pivot-workspaces"),
        ):
            module._ensure_workspace_dir("/app/server/workspace/alice")

    def test_ensure_workspace_dir_accepts_external_posix_root(self) -> None:
        """External POSIX roots should be treated as valid workspace parents."""
        module = cast(Any, sandbox_manager)
        backend = type(
            "Backend",
            (),
            {
                "exec_run": lambda self, *args, **kwargs: (0, b""),
            },
        )()

        with (
            patch.object(
                module,
                "get_settings",
                return_value=type(
                    "Settings",
                    (),
                    {
                        "SANDBOX_BACKEND_WORKSPACE_ROOT": "/app/server/workspace",
                        "SANDBOX_EXTERNAL_POSIX_ROOT": "/app/server/external-posix",
                    },
                )(),
            ),
            patch.object(module, "_backend_container", return_value=backend),
        ):
            module._ensure_workspace_dir(
                "/app/server/external-posix/users/alice/agents/7/sessions/s1/workspace"
            )

    def test_resolve_host_path_prefers_external_posix_mount(self) -> None:
        """Workspace resolution should prefer the most specific external mount."""
        module = cast(Any, sandbox_manager)
        backend_mounts = [
            {
                "Destination": "/app/server",
                "Source": "/Users/dev/pivot/server",
            },
            {
                "Destination": "/app/server/external-posix",
                "Source": "/tmp/pivot-seaweedfs-posix",
            },
        ]

        with (
            patch.object(
                module,
                "_backend_container",
                return_value=object(),
            ),
            patch.object(module, "_get_container_mounts", return_value=backend_mounts),
            patch.object(module, "_self_container", return_value=None),
        ):
            resolved = module._resolve_host_path_from_backend_path(
                "/app/server/external-posix/users/alice/agents/7/sessions/s1/workspace"
            )

        self.assertEqual(
            resolved,
            "/tmp/pivot-seaweedfs-posix/users/alice/agents/7/sessions/s1/workspace",
        )
