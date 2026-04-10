"""Unit tests for storage profile resolution."""

from __future__ import annotations

import sys
import tempfile
import unittest
from importlib import import_module
from pathlib import Path
from unittest.mock import Mock, patch

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

resolver_module = import_module("app.storage.resolver")


class StorageResolverTestCase(unittest.TestCase):
    """Validate profile selection and fallback behavior."""

    def tearDown(self) -> None:
        """Clear cached profile resolution after each test."""
        resolver_module.get_resolved_storage_profile.cache_clear()

    def test_resolves_seaweedfs_profile_when_healthchecks_pass(self) -> None:
        """SeaweedFS should activate when filer and POSIX root are configured."""
        with tempfile.TemporaryDirectory() as tmp_root:
            settings = type(
                "Settings",
                (),
                {
                    "STORAGE_PROFILE": "seaweedfs",
                    "STORAGE_LOCAL_ROOT": None,
                    "STORAGE_SEAWEEDFS_FILER_ENDPOINT": "http://seaweedfs-filer:8888",
                    "STORAGE_SEAWEEDFS_POSIX_ROOT": tmp_root,
                },
            )()
            response = Mock()
            response.raise_for_status.return_value = None

            with (
                patch.object(resolver_module, "get_settings", return_value=settings),
                patch(
                    "app.storage.providers.seaweedfs.requests.get",
                    return_value=response,
                ),
                patch.object(
                    resolver_module,
                    "_verify_seaweedfs_shared_namespace",
                    return_value=None,
                ),
                patch.object(
                    resolver_module,
                    "_verify_posix_root_writable",
                    return_value=None,
                ),
            ):
                profile = resolver_module.get_resolved_storage_profile()

        self.assertEqual(profile.active_profile, "seaweedfs")
        self.assertEqual(profile.object_storage.backend_name, "seaweedfs")
        self.assertEqual(profile.posix_workspace.backend_name, "mounted_posix")

    def test_falls_back_to_local_fs_when_seaweedfs_healthcheck_fails(self) -> None:
        """SeaweedFS should degrade cleanly to local_fs when unreachable."""
        with tempfile.TemporaryDirectory() as tmp_root:
            settings = type(
                "Settings",
                (),
                {
                    "STORAGE_PROFILE": "seaweedfs",
                    "STORAGE_LOCAL_ROOT": None,
                    "STORAGE_SEAWEEDFS_FILER_ENDPOINT": "http://seaweedfs-filer:8888",
                    "STORAGE_SEAWEEDFS_POSIX_ROOT": tmp_root,
                },
            )()

            with (
                patch.object(resolver_module, "get_settings", return_value=settings),
                patch(
                    "app.storage.providers.seaweedfs.requests.get",
                    side_effect=RuntimeError("connection refused"),
                ),
            ):
                profile = resolver_module.get_resolved_storage_profile()

        self.assertEqual(profile.active_profile, "local_fs")
        self.assertEqual(profile.requested_profile, "seaweedfs")
        self.assertEqual(profile.object_storage.backend_name, "local_fs")
        self.assertEqual(profile.posix_workspace.backend_name, "local_fs")
        self.assertEqual(profile.fallback_reason, "seaweedfs_filer_unreachable")

    def test_auto_profile_stays_local_when_filer_is_unreachable(self) -> None:
        """Auto mode should remain silent local_fs when SeaweedFS is absent."""
        with tempfile.TemporaryDirectory() as tmp_root:
            settings = type(
                "Settings",
                (),
                {
                    "STORAGE_PROFILE": "auto",
                    "STORAGE_LOCAL_ROOT": None,
                    "STORAGE_SEAWEEDFS_FILER_ENDPOINT": "http://seaweedfs-filer:8888",
                    "STORAGE_SEAWEEDFS_POSIX_ROOT": tmp_root,
                },
            )()

            with (
                patch.object(resolver_module, "get_settings", return_value=settings),
                patch(
                    "app.storage.providers.seaweedfs.requests.get",
                    side_effect=RuntimeError("connection refused"),
                ),
            ):
                profile = resolver_module.get_resolved_storage_profile()

        self.assertEqual(profile.requested_profile, "auto")
        self.assertEqual(profile.active_profile, "local_fs")
        self.assertEqual(profile.fallback_reason, "seaweedfs_filer_unreachable")

    def test_auto_profile_warns_when_namespace_bridge_is_invalid(self) -> None:
        """Auto mode should fall back with a warning when the POSIX view is split."""
        with tempfile.TemporaryDirectory() as tmp_root:
            settings = type(
                "Settings",
                (),
                {
                    "STORAGE_PROFILE": "auto",
                    "STORAGE_LOCAL_ROOT": None,
                    "STORAGE_SEAWEEDFS_FILER_ENDPOINT": "http://seaweedfs-filer:8888",
                    "STORAGE_SEAWEEDFS_POSIX_ROOT": tmp_root,
                },
            )()
            response = Mock()
            response.raise_for_status.return_value = None

            with (
                patch.object(resolver_module, "get_settings", return_value=settings),
                patch(
                    "app.storage.providers.seaweedfs.requests.get",
                    return_value=response,
                ),
                patch.object(
                    resolver_module,
                    "_verify_seaweedfs_shared_namespace",
                    side_effect=RuntimeError("namespace mismatch"),
                ),
            ):
                profile = resolver_module.get_resolved_storage_profile()

        self.assertEqual(profile.requested_profile, "auto")
        self.assertEqual(profile.active_profile, "local_fs")
        self.assertEqual(profile.fallback_reason, "seaweedfs_namespace_mismatch")

    def test_auto_profile_falls_back_when_posix_root_is_not_writable(self) -> None:
        """Auto mode should reject SeaweedFS mounts that fail direct POSIX writes."""
        with tempfile.TemporaryDirectory() as tmp_root:
            settings = type(
                "Settings",
                (),
                {
                    "STORAGE_PROFILE": "auto",
                    "STORAGE_LOCAL_ROOT": None,
                    "STORAGE_SEAWEEDFS_FILER_ENDPOINT": "http://seaweedfs-filer:8888",
                    "STORAGE_SEAWEEDFS_POSIX_ROOT": tmp_root,
                },
            )()
            response = Mock()
            response.raise_for_status.return_value = None

            with (
                patch.object(resolver_module, "get_settings", return_value=settings),
                patch(
                    "app.storage.providers.seaweedfs.requests.get",
                    return_value=response,
                ),
                patch.object(
                    resolver_module,
                    "_verify_seaweedfs_shared_namespace",
                    return_value=None,
                ),
                patch.object(
                    resolver_module,
                    "_verify_posix_root_writable",
                    side_effect=RuntimeError("posix io failed"),
                ),
            ):
                profile = resolver_module.get_resolved_storage_profile()

        self.assertEqual(profile.requested_profile, "auto")
        self.assertEqual(profile.active_profile, "local_fs")
        self.assertEqual(profile.fallback_reason, "seaweedfs_posix_io_failed")
