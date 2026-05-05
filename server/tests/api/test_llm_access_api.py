"""API tests for LLM resource-level edit access."""

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
auth_module = import_module("app.api.auth")
dependencies_module = import_module("app.api.dependencies")
llms_api_module = import_module("app.api.llms")
permission_catalog_module = import_module("app.security.permission_catalog")
permission_service_module = import_module("app.services.permission_service")
user_models = import_module("app.models.user")
access_service_module = import_module("app.services.access_service")

AccessLevel = access_models.AccessLevel
AccessService = access_service_module.AccessService
Permission = permission_catalog_module.Permission
PermissionService = permission_service_module.PermissionService
PrincipalType = access_models.PrincipalType
ResourceAccess = access_models.ResourceAccess
ResourceType = access_models.ResourceType
User = user_models.User

if TYPE_CHECKING:
    from collections.abc import Generator


class LLMAccessApiTestCase(unittest.TestCase):
    """Verify LLM management stays inside resource edit grants."""

    def setUp(self) -> None:
        """Create one isolated test app and database."""
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        permission_service = PermissionService(self.session)
        permission_service.seed_defaults()
        llm_role = permission_service.create_role(
            key="llm-manager",
            name="LLM Manager",
            permission_keys={Permission.AGENTS_MANAGE, Permission.LLMS_MANAGE},
        )
        self.owner = User(
            username="owner",
            password_hash="hash",
            role_id=llm_role.id or 0,
        )
        self.collaborator = User(
            username="collaborator",
            password_hash="hash",
            role_id=llm_role.id or 0,
        )
        self.session.add(self.owner)
        self.session.add(self.collaborator)
        self.session.commit()
        self.session.refresh(self.owner)
        self.session.refresh(self.collaborator)
        self.current_user = self.owner

        self.app = FastAPI()
        self.app.include_router(llms_api_module.router)
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

    def _create_llm(self) -> dict[str, Any]:
        response = self.client.post(
            "/llms",
            json={
                "name": "primary",
                "endpoint": "https://api.example.test/v1",
                "model": "model-a",
                "api_key": "test-key",
                "protocol": "openai_completion_llm",
            },
        )
        self.assertEqual(response.status_code, 201)
        return response.json()

    def test_creator_can_manage_created_llm(self) -> None:
        """Creating an LLM should grant creator edit access."""
        llm_payload = self._create_llm()

        response = self.client.get("/llms")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.json()], [llm_payload["id"]])

        response = self.client.put(
            f"/llms/{llm_payload['id']}",
            json={"model": "model-b"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["model"], "model-b")

    def test_llm_manager_without_resource_edit_is_blocked(self) -> None:
        """System capability alone should not expose another user's LLM config."""
        llm_payload = self._create_llm()

        self.current_user = self.collaborator
        response = self.client.get("/llms")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

        response = self.client.get(f"/llms/{llm_payload['id']}")
        self.assertEqual(response.status_code, 403)

    def test_resource_edit_grant_allows_collaborator_management(self) -> None:
        """A direct LLM edit grant should allow read and update."""
        llm_payload = self._create_llm()
        AccessService(self.session).grant_access(
            resource_type=ResourceType.LLM,
            resource_id=llm_payload["id"],
            principal_type=PrincipalType.USER,
            principal_id=self.collaborator.id or 0,
            access_level=AccessLevel.EDIT,
        )

        self.current_user = self.collaborator
        response = self.client.get(f"/llms/{llm_payload['id']}")
        self.assertEqual(response.status_code, 200)

        response = self.client.put(
            f"/llms/{llm_payload['id']}",
            json={"name": "collaborator-model"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "collaborator-model")

    def test_resource_use_grant_exposes_safe_usable_option_only(self) -> None:
        """A direct LLM use grant should expose selection data without secrets."""
        llm_payload = self._create_llm()
        response = self.client.put(
            f"/llms/{llm_payload['id']}/access",
            json={
                "use_scope": "selected",
                "use_user_ids": [self.collaborator.id],
                "use_group_ids": [],
                "edit_user_ids": [],
                "edit_group_ids": [],
            },
        )
        self.assertEqual(response.status_code, 200)

        self.current_user = self.collaborator
        response = self.client.get("/llms/usable")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual([row["id"] for row in payload], [llm_payload["id"]])
        self.assertEqual(payload[0]["name"], "primary")
        self.assertEqual(payload[0]["model"], "model-a")
        self.assertNotIn("api_key", payload[0])
        self.assertNotIn("endpoint", payload[0])
        self.assertNotIn("extra_config", payload[0])

        response = self.client.get(f"/llms/{llm_payload['id']}")
        self.assertEqual(response.status_code, 403)

    def test_owner_can_update_access_and_creator_stays_editor(self) -> None:
        """The access API should update grants while keeping creator edit."""
        llm_payload = self._create_llm()

        response = self.client.get(f"/llms/{llm_payload['id']}/access-options")
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            self.collaborator.id,
            {user["id"] for user in response.json()["users"]},
        )

        response = self.client.put(
            f"/llms/{llm_payload['id']}/access",
            json={
                "use_scope": "selected",
                "use_user_ids": [self.collaborator.id],
                "use_group_ids": [],
                "edit_user_ids": [],
                "edit_group_ids": [],
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn(self.collaborator.id, payload["use_user_ids"])
        self.assertIn(self.owner.id, payload["edit_user_ids"])
        self.assertNotIn(self.collaborator.id, payload["edit_user_ids"])

    def test_delete_removes_llm_resource_grants(self) -> None:
        """Deleting an LLM should clean up direct resource grants."""
        llm_payload = self._create_llm()

        response = self.client.delete(f"/llms/{llm_payload['id']}")
        self.assertEqual(response.status_code, 204)

        grant = self.session.exec(
            select(ResourceAccess).where(
                ResourceAccess.resource_type == ResourceType.LLM,
                ResourceAccess.resource_id == str(llm_payload["id"]),
            )
        ).first()
        self.assertIsNone(grant)


if __name__ == "__main__":
    unittest.main()
