"""Unit tests for storage status reporting."""

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

storage_status_service = import_module("app.services.storage_status_service")


class StorageStatusServiceTestCase(unittest.TestCase):
    """Validate storage status snapshots for diagnostics."""

    def test_reports_resolved_storage_profile(self) -> None:
        """Status should expose active backends and the backend workspace root."""
        module = cast(Any, storage_status_service)
        service = module.StorageStatusService()
        fake_profile = type(
            "ResolvedProfile",
            (),
            {
                "requested_profile": "seaweedfs",
                "active_profile": "local_fs",
                "fallback_reason": "external_profile_unavailable",
                "object_storage": type(
                    "ObjectStorage", (), {"backend_name": "local_fs"}
                )(),
                "posix_workspace": type(
                    "PosixWorkspace",
                    (),
                    {"backend_name": "local_fs"},
                )(),
            },
        )()

        with (
            patch.object(
                module, "get_resolved_storage_profile", return_value=fake_profile
            ),
            patch.object(
                module,
                "backend_workspace_root",
                return_value="/srv/pivot-workspaces",
            ),
            patch.object(
                module,
                "get_settings",
                return_value=type(
                    "Settings",
                    (),
                    {
                        "STORAGE_SEAWEEDFS_POSIX_ROOT": "/srv/pivot-external-posix",
                        "STORAGE_SEAWEEDFS_HOST_POSIX_ROOT": "/host/pivot-external-posix",
                    },
                )(),
            ),
            patch.object(module.Path, "exists", return_value=True),
            patch.object(
                module,
                "inspect_seaweedfs_readiness",
                return_value=type(
                    "Readiness",
                    (),
                    {
                        "is_configured": True,
                        "filer_reachable": True,
                        "posix_root_exists": True,
                        "namespace_shared": False,
                        "reason_detail": "namespace mismatch",
                    },
                )(),
            ),
        ):
            snapshot = service.get_status()

        self.assertEqual(snapshot.requested_profile, "seaweedfs")
        self.assertEqual(snapshot.active_profile, "local_fs")
        self.assertEqual(snapshot.object_storage_backend, "local_fs")
        self.assertEqual(snapshot.posix_workspace_backend, "local_fs")
        self.assertEqual(snapshot.fallback_reason, "external_profile_unavailable")
        self.assertEqual(snapshot.backend_workspace_root, "/srv/pivot-workspaces")
        self.assertEqual(snapshot.external_posix_root, "/srv/pivot-external-posix")
        self.assertEqual(
            snapshot.external_host_posix_root, "/host/pivot-external-posix"
        )
        self.assertTrue(snapshot.external_posix_root_exists)
        self.assertTrue(snapshot.external_filer_reachable)
        self.assertFalse(snapshot.external_namespace_shared)
        self.assertEqual(snapshot.external_readiness_reason, "namespace mismatch")
