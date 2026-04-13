"""API tests for skill bundle import flows."""

from __future__ import annotations

import sys
import unittest
from importlib import import_module
from pathlib import Path
from typing import Any
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

User = import_module("app.models.user").User
auth_module = import_module("app.api.auth")
dependencies_module = import_module("app.api.dependencies")
skills_api_module = import_module("app.api.skills")


class SkillsApiTestCase(unittest.TestCase):
    """Verify skill API bundle-import behavior."""

    def setUp(self) -> None:
        """Create one isolated app with auth and database overrides."""
        self.user = User(username="alice", password_hash="hash")
        self.app = FastAPI()
        self.app.include_router(skills_api_module.router, prefix="/api")
        self.app.dependency_overrides[dependencies_module.get_db] = self._get_db
        self.app.dependency_overrides[auth_module.get_current_user] = (
            self._get_current_user
        )
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        """Release the test client and dependency overrides."""
        self.client.close()
        self.app.dependency_overrides.clear()

    def _get_db(self):
        """Yield one placeholder database dependency for patched service calls."""
        yield object()

    def _get_current_user(self) -> Any:
        """Return the authenticated test user for protected endpoints."""
        return self.user

    def test_bundle_import_accepts_more_than_default_multipart_limit(self) -> None:
        """Skill bundle import should tolerate multipart payloads above 1000 fields."""
        file_count = 1_001
        files = [
            (
                "files",
                (
                    f"part-{index}.txt",
                    f"content-{index}".encode(),
                    "text/plain",
                ),
            )
            for index in range(file_count)
        ]
        data = {
            "bundle_name": "bulk-import",
            "kind": "private",
            "skill_name": "bulk-import-skill",
            "relative_paths": [
                f"bulk-import/files/part-{index}.txt" for index in range(file_count)
            ],
        }

        with patch.object(
            skills_api_module,
            "install_bundle_skill",
            return_value={"name": "bulk-import-skill"},
        ) as install_mock:
            response = self.client.post(
                "/api/skills/import/bundle",
                files=files,
                data=data,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "imported")

        self.assertTrue(install_mock.called)
        self.assertEqual(len(install_mock.call_args.kwargs["files"]), file_count)
        self.assertEqual(
            install_mock.call_args.kwargs["files"][0].relative_path,
            "bulk-import/files/part-0.txt",
        )
        self.assertEqual(
            install_mock.call_args.kwargs["files"][-1].relative_path,
            "bulk-import/files/part-1000.txt",
        )
