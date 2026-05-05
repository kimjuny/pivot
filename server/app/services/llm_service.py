"""Service layer for LLM provider configurations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.llm.cache_policy import validate_cache_policy
from app.llm.thinking_policy import validate_thinking_policy
from app.models.access import AccessLevel, ResourceType
from app.models.llm import LLM
from app.services.access_service import AccessService
from sqlmodel import Session as DBSession, col, select

if TYPE_CHECKING:
    from app.models.user import User


class LLMService:
    """CRUD and resource-access operations for LLM configs."""

    def __init__(self, db: DBSession) -> None:
        self.db = db

    def get_llm(self, llm_id: int) -> LLM | None:
        """Return one LLM config by id."""
        return self.db.get(LLM, llm_id)

    def get_by_name(self, name: str) -> LLM | None:
        """Return one LLM config by unique name."""
        return self.db.exec(select(LLM).where(LLM.name == name)).first()

    def has_llm_access(
        self,
        *,
        user: User,
        llm: LLM,
        access_level: AccessLevel,
    ) -> bool:
        """Return whether a user can use or edit one LLM config."""
        return AccessService(self.db).has_resource_access(
            user=user,
            resource_type=ResourceType.LLM,
            resource_id=llm.id,
            access_level=access_level,
            creator_user_id=llm.created_by_user_id,
            use_scope=llm.use_scope,
        )

    def require_llm_access(
        self,
        *,
        user: User,
        llm: LLM,
        access_level: AccessLevel,
    ) -> None:
        """Raise unless a user can use or edit one LLM config."""
        AccessService(self.db).require_resource_access(
            user=user,
            resource_type=ResourceType.LLM,
            resource_id=llm.id,
            access_level=access_level,
            creator_user_id=llm.created_by_user_id,
            use_scope=llm.use_scope,
        )

    def list_llms(
        self,
        *,
        user: User,
        skip: int = 0,
        limit: int = 100,
    ) -> list[LLM]:
        """List LLM configs the user can edit."""
        statement = select(LLM).order_by(col(LLM.updated_at).desc())
        llms = [
            llm
            for llm in self.db.exec(statement).all()
            if self.has_llm_access(
                user=user,
                llm=llm,
                access_level=AccessLevel.EDIT,
            )
        ]
        return llms[skip : skip + limit]

    def list_usable_llms(
        self,
        *,
        user: User,
        skip: int = 0,
        limit: int = 100,
    ) -> list[LLM]:
        """List LLM configs the user can select or reference in Studio."""
        statement = select(LLM).order_by(col(LLM.updated_at).desc())
        llms = [
            llm
            for llm in self.db.exec(statement).all()
            if self.has_llm_access(
                user=user,
                llm=llm,
                access_level=AccessLevel.USE,
            )
        ]
        return llms[skip : skip + limit]

    def create_llm(
        self,
        *,
        user: User,
        name: str,
        endpoint: str,
        model: str,
        api_key: str,
        protocol: str,
        cache_policy: str,
        thinking_policy: str,
        thinking_effort: str | None,
        thinking_budget_tokens: int | None,
        streaming: bool,
        image_input: bool,
        image_output: bool,
        max_context: int,
        extra_config: str | None,
        use_scope: str = "all",
        use_user_ids: set[int] | None = None,
        use_group_ids: set[int] | None = None,
        edit_user_ids: set[int] | None = None,
        edit_group_ids: set[int] | None = None,
    ) -> LLM:
        """Create one LLM config and grant creator edit access."""
        if use_scope not in {"all", "selected"}:
            raise ValueError("use_scope must be 'all' or 'selected'.")
        if self.get_by_name(name) is not None:
            raise ValueError("LLM with this name already exists")
        (
            normalized_cache_policy,
            normalized_thinking_policy,
            normalized_thinking_effort,
            normalized_thinking_budget_tokens,
        ) = self._validate_policy_fields(
            protocol=protocol,
            cache_policy=cache_policy,
            thinking_policy=thinking_policy,
            thinking_effort=thinking_effort,
            thinking_budget_tokens=thinking_budget_tokens,
        )
        llm = LLM(
            name=name,
            created_by_user_id=user.id,
            use_scope=use_scope,
            endpoint=endpoint,
            model=model,
            api_key=api_key,
            protocol=protocol,
            cache_policy=normalized_cache_policy,
            thinking_policy=normalized_thinking_policy,
            thinking_effort=normalized_thinking_effort,
            thinking_budget_tokens=normalized_thinking_budget_tokens,
            streaming=streaming,
            image_input=image_input,
            image_output=image_output,
            max_context=max_context,
            extra_config=extra_config,
        )
        self.db.add(llm)
        self.db.commit()
        self.db.refresh(llm)
        if llm.id is not None:
            self.set_llm_access(
                llm=llm,
                use_scope=use_scope,
                use_user_ids=use_user_ids or set(),
                use_group_ids=use_group_ids or set(),
                edit_user_ids=edit_user_ids or set(),
                edit_group_ids=edit_group_ids or set(),
            )
        return llm

    def set_llm_access(
        self,
        *,
        llm: LLM,
        use_scope: str,
        use_user_ids: set[int],
        use_group_ids: set[int],
        edit_user_ids: set[int],
        edit_group_ids: set[int],
    ) -> None:
        """Replace selected use/edit grants for one LLM config."""
        if llm.id is None:
            raise ValueError("LLM must be persisted before access can be updated.")
        if use_scope not in {"all", "selected"}:
            raise ValueError("use_scope must be 'all' or 'selected'.")
        if llm.created_by_user_id is not None:
            edit_user_ids = set(edit_user_ids)
            edit_user_ids.add(llm.created_by_user_id)

        llm.use_scope = use_scope
        access_service = AccessService(self.db)
        access_service._replace_resource_grants_in_session(
            resource_type=ResourceType.LLM,
            resource_id=llm.id,
            access_level=AccessLevel.USE,
            user_ids=use_user_ids if use_scope == "selected" else set(),
            group_ids=use_group_ids if use_scope == "selected" else set(),
        )
        access_service._replace_resource_grants_in_session(
            resource_type=ResourceType.LLM,
            resource_id=llm.id,
            access_level=AccessLevel.EDIT,
            user_ids=edit_user_ids,
            group_ids=edit_group_ids,
        )
        llm.updated_at = datetime.now(UTC)
        self.db.add(llm)
        self.db.commit()
        self.db.refresh(llm)

    def update_llm(
        self,
        llm_id: int,
        *,
        user: User,
        update_data: dict[str, Any],
    ) -> LLM | None:
        """Update one editable LLM config."""
        llm = self.get_llm(llm_id)
        if llm is None:
            return None
        self.require_llm_access(user=user, llm=llm, access_level=AccessLevel.EDIT)

        next_name = update_data.get("name")
        if next_name is not None and next_name != llm.name:
            existing_llm = self.get_by_name(next_name)
            if existing_llm is not None:
                raise ValueError("LLM with this name already exists")

        target_protocol = update_data.get("protocol", llm.protocol)
        target_cache_policy = update_data.get("cache_policy", llm.cache_policy)
        target_thinking_policy = update_data.get(
            "thinking_policy",
            llm.thinking_policy,
        )
        target_thinking_effort = update_data.get(
            "thinking_effort",
            llm.thinking_effort,
        )
        target_thinking_budget_tokens = update_data.get(
            "thinking_budget_tokens",
            llm.thinking_budget_tokens,
        )
        (
            update_data["cache_policy"],
            update_data["thinking_policy"],
            update_data["thinking_effort"],
            update_data["thinking_budget_tokens"],
        ) = self._validate_policy_fields(
            protocol=target_protocol,
            cache_policy=target_cache_policy,
            thinking_policy=target_thinking_policy,
            thinking_effort=target_thinking_effort,
            thinking_budget_tokens=target_thinking_budget_tokens,
        )

        for key, value in update_data.items():
            setattr(llm, key, value)
        llm.updated_at = datetime.now(UTC)
        self.db.add(llm)
        self.db.commit()
        self.db.refresh(llm)
        return llm

    def delete_llm(self, llm_id: int, *, user: User) -> bool:
        """Delete one editable LLM config and its direct grants."""
        llm = self.get_llm(llm_id)
        if llm is None:
            return False
        self.require_llm_access(user=user, llm=llm, access_level=AccessLevel.EDIT)
        access_service = AccessService(self.db)
        access_service._delete_resource_grants_in_session(
            resource_type=ResourceType.LLM,
            resource_id=llm_id,
        )
        self.db.delete(llm)
        self.db.commit()
        return True

    def _validate_policy_fields(
        self,
        *,
        protocol: str,
        cache_policy: str,
        thinking_policy: str,
        thinking_effort: str | None,
        thinking_budget_tokens: int | None,
    ) -> tuple[str, str, str | None, int | None]:
        """Validate protocol-dependent cache and thinking settings."""
        normalized_cache_policy = validate_cache_policy(protocol, cache_policy)
        (
            normalized_thinking_policy,
            normalized_thinking_effort,
            normalized_thinking_budget_tokens,
        ) = validate_thinking_policy(
            protocol,
            thinking_policy,
            thinking_effort,
            thinking_budget_tokens,
        )
        return (
            normalized_cache_policy,
            normalized_thinking_policy,
            normalized_thinking_effort,
            normalized_thinking_budget_tokens,
        )
