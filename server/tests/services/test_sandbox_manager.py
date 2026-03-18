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
                    {"Destination": "/workspace", "Source": "/tmp/workspace"}
                ],
            ),
            patch.object(module, "_mounted_skill_sources", return_value={}),
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
                    {"SANDBOX_BASE_IMAGE": "localhost/pivot-sandbox-base:py311-rg"},
                )(),
            ),
        ):
            should_recreate, reason = module._should_recreate_container(container, {})

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
                    {"Destination": "/workspace", "Source": "/tmp/workspace"}
                ],
            ),
            patch.object(module, "_mounted_skill_sources", return_value={}),
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
                    {"SANDBOX_BASE_IMAGE": "localhost/pivot-sandbox-base:py311-rg"},
                )(),
            ),
        ):
            should_recreate, reason = module._should_recreate_container(container, {})

        self.assertFalse(should_recreate)
        self.assertEqual(reason, "ok")
