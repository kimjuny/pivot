"""API tests for client and session entry permissions."""

from __future__ import annotations

import sys
import unittest
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

import_module("app.models")
access_models = import_module("app.models.access")
agent_models = import_module("app.models.agent")
user_models = import_module("app.models.user")
auth_module = import_module("app.api.auth")
consumer_api_module = import_module("app.api.consumer")
projects_api_module = import_module("app.api.projects")
session_api_module = import_module("app.api.session")
dependencies_module = import_module("app.api.dependencies")
permission_service_module = import_module("app.services.permission_service")

Agent = agent_models.Agent
Role = access_models.Role
User = user_models.User
PermissionService = permission_service_module.PermissionService

if TYPE_CHECKING:
    from collections.abc import Generator


class EntryPermissionApiTestCase(unittest.TestCase):
    """Verify entry permissions before resource-level checks run."""

    def setUp(self) -> None:
        """Create one isolated test app and database."""
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.permission_service = PermissionService(self.session)
        self.permission_service.seed_defaults()

        user_role = self.session.exec(select(Role).where(Role.key == "user")).one()
        self.client_user = User(
            username="client-user",
            password_hash="hash",
            role_id=user_role.id or 0,
        )

        no_entry_role = self.permission_service.create_role(
            key="no-entry",
            name="No Entry",
            permission_keys=set(),
        )
        self.no_entry_user = User(
            username="no-entry-user",
            password_hash="hash",
            role_id=no_entry_role.id or 0,
        )
        self.session.add(self.client_user)
        self.session.add(self.no_entry_user)
        self.locked_agent = Agent(name="Locked", llm_id=None, use_scope="selected")
        self.session.add(self.locked_agent)
        self.session.commit()
        self.session.refresh(self.client_user)
        self.session.refresh(self.no_entry_user)
        self.session.refresh(self.locked_agent)
        self.current_user = self.no_entry_user

        self.app = FastAPI()
        self.app.include_router(consumer_api_module.router)
        self.app.include_router(projects_api_module.router)
        self.app.include_router(session_api_module.router)
        self.app.dependency_overrides[dependencies_module.get_db] = self._get_db
        self.app.dependency_overrides[auth_module.get_current_user] = (
            self._get_current_user
        )
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        """Release app and database resources."""
        self.client.close()
        self.app.dependency_overrides.clear()
        self.session.close()

    def _get_db(self) -> Generator[Session, None, None]:
        """Yield the shared database session for the test API app."""
        yield self.session

    def _get_current_user(self) -> Any:
        """Return the active user configured by each test."""
        return self.current_user

    def test_consumer_agents_require_client_access(self) -> None:
        """Consumer agent listing should require the client entry permission."""
        response = self.client.get("/consumer/agents")

        self.assertEqual(response.status_code, 403)

    def test_consumer_session_create_requires_client_access(self) -> None:
        """Consumer session creation should require the client entry permission."""
        response = self.client.post(
            "/sessions",
            json={"agent_id": 1, "type": "consumer"},
        )

        self.assertEqual(response.status_code, 403)

    def test_studio_test_session_create_requires_agent_management(self) -> None:
        """Studio test session creation should require the Studio agent capability."""
        self.current_user = self.client_user

        response = self.client.post(
            "/sessions",
            json={"agent_id": 1, "type": "studio_test"},
        )

        self.assertEqual(response.status_code, 403)

    def test_projects_require_client_access(self) -> None:
        """Project listing should require the client entry permission."""
        response = self.client.get("/projects?agent_id=1")

        self.assertEqual(response.status_code, 403)

    def test_projects_require_agent_use_access(self) -> None:
        """Project listing should stay inside the agent use boundary."""
        self.current_user = self.client_user

        response = self.client.get(f"/projects?agent_id={self.locked_agent.id}")

        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
