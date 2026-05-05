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
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

import_module("app.models")
Role = import_module("app.models.access").Role
User = import_module("app.models.user").User
auth_module = import_module("app.api.auth")
dependencies_module = import_module("app.api.dependencies")
skills_api_module = import_module("app.api.skills")
permission_service_module = import_module("app.services.permission_service")

PermissionService = permission_service_module.PermissionService


class SkillsApiTestCase(unittest.TestCase):
    """Verify skill API bundle-import behavior."""

    def setUp(self) -> None:
        """Create one isolated app with auth and database overrides."""
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        PermissionService(self.session).seed_defaults()
        admin_role = self.session.exec(select(Role).where(Role.key == "admin")).one()
        self.user = User(
            username="alice",
            password_hash="hash",
            role_id=admin_role.id or 0,
        )
        self.session.add(self.user)
        self.session.commit()
        self.session.refresh(self.user)
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
        self.session.close()

    def _get_db(self):
        """Yield the shared test database session."""
        yield self.session

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
