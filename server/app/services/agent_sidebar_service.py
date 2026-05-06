"""Reusable aggregation helpers for Agent detail sidebar state."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from app.services.agent_service import AgentService
from app.services.channel_service import ChannelService
from app.services.extension_service import ExtensionService
from app.services.media_generation_service import MediaGenerationService
from app.services.skill_service import list_visible_skills
from app.services.tool_service import list_usable_tools
from app.services.web_search_service import WebSearchService

if TYPE_CHECKING:
    from app.models.user import User
    from sqlmodel import Session


def _parse_name_allowlist(raw_value: str | None) -> set[str]:
    """Parse one persisted JSON allowlist into trimmed names."""
    if raw_value is None:
        return set()
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return set()
    if not isinstance(parsed, list):
        return set()
    return {item.strip() for item in parsed if isinstance(item, str) and item.strip()}


class AgentSidebarService:
    """Build compact sidebar payloads for one editable agent."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def _count_enabled_extension_contributions(
        self,
        *,
        packages: list[dict[str, Any]],
        contribution_type: str,
    ) -> int:
        """Count enabled extension contribution items of one type."""
        extension_service = ExtensionService(self.db)
        total = 0

        for package in packages:
            binding = package.get("selected_binding")
            if binding is None or not getattr(binding, "enabled", False):
                continue

            installation_id = getattr(binding, "extension_installation_id", None)
            if not isinstance(installation_id, int):
                continue

            installation = next(
                (
                    item
                    for item in package.get("versions", [])
                    if getattr(item, "id", None) == installation_id
                ),
                None,
            )
            if installation is None:
                continue

            total += sum(
                1
                for item in extension_service.get_installation_contribution_items(
                    installation
                )
                if item.get("type") == contribution_type
            )

        return total

    def get_sidebar_stats(
        self,
        *,
        agent_id: int,
        user: User,
    ) -> dict[str, dict[str, int]]:
        """Return compact count summaries for Agent detail sidebar sections."""
        agent = AgentService(self.db).get_required_agent(agent_id)
        extension_service = ExtensionService(self.db)
        channel_service = ChannelService(self.db)
        media_generation_service = MediaGenerationService(self.db)
        web_search_service = WebSearchService(self.db)

        usable_tools = list_usable_tools(self.db, current_user=user)
        visible_skills = list_visible_skills(self.db, user.username)
        extension_packages = extension_service.list_agent_package_choices(
            agent_id, user
        )

        selected_extension_packages = [
            package
            for package in extension_packages
            if package.get("selected_binding") is not None
        ]
        enabled_extension_tool_count = self._count_enabled_extension_contributions(
            packages=extension_packages,
            contribution_type="tool",
        )
        enabled_extension_skill_count = self._count_enabled_extension_contributions(
            packages=extension_packages,
            contribution_type="skill",
        )

        allowed_tool_names = _parse_name_allowlist(agent.tool_ids)
        allowed_skill_names = _parse_name_allowlist(agent.skill_ids)

        tool_selected_count = (
            sum(1 for item in usable_tools if item.get("name") in allowed_tool_names)
            + enabled_extension_tool_count
        )
        skill_selected_count = (
            sum(1 for item in visible_skills if item.get("name") in allowed_skill_names)
            + enabled_extension_skill_count
        )

        channel_catalog = channel_service.list_catalog(agent_id, user=user)
        channel_bindings = channel_service.list_agent_bindings(agent_id)
        media_catalog = media_generation_service.list_catalog(agent_id, user=user)
        media_bindings = media_generation_service.list_agent_bindings(agent_id)
        web_search_catalog = web_search_service.list_catalog(agent_id, user=user)
        web_search_bindings = web_search_service.list_agent_bindings(agent_id)

        return {
            "tools": {
                "selected_count": tool_selected_count,
                "total_count": len(usable_tools) + enabled_extension_tool_count,
            },
            "skills": {
                "selected_count": skill_selected_count,
                "total_count": len(visible_skills) + enabled_extension_skill_count,
            },
            "extensions": {
                "selected_count": len(selected_extension_packages),
                "total_count": len(extension_packages),
            },
            "channels": {
                "selected_count": len(channel_bindings),
                "total_count": len(channel_catalog),
            },
            "media": {
                "selected_count": len(media_bindings),
                "total_count": len(media_catalog),
            },
            "web_search": {
                "selected_count": len(web_search_bindings),
                "total_count": len(web_search_catalog),
            },
        }
