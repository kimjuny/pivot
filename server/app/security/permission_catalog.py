"""System permission catalog for Pivot roles."""

from __future__ import annotations

from enum import StrEnum


class Permission(StrEnum):
    """Permission keys recognized by the backend."""

    CLIENT_ACCESS = "client.access"
    STUDIO_ACCESS = "studio.access"

    USERS_MANAGE = "users.manage"
    GROUPS_MANAGE = "groups.manage"
    ROLES_MANAGE = "roles.manage"

    OPERATIONS_VIEW = "operations.view"

    AGENTS_MANAGE = "agents.manage"
    LLMS_MANAGE = "llms.manage"
    TOOLS_MANAGE = "tools.manage"
    SKILLS_MANAGE = "skills.manage"
    EXTENSIONS_MANAGE = "extensions.manage"
    CHANNELS_MANAGE = "channels.manage"
    MEDIA_GENERATION_MANAGE = "media_generation.manage"
    WEB_SEARCH_MANAGE = "web_search.manage"
    STORAGE_VIEW = "storage.view"


PERMISSION_METADATA: dict[Permission, dict[str, str]] = {
    Permission.CLIENT_ACCESS: {
        "name": "Client access",
        "category": "Access",
        "description": "Access client-facing Pivot surfaces.",
    },
    Permission.STUDIO_ACCESS: {
        "name": "Studio access",
        "category": "Access",
        "description": "Access the Studio workspace.",
    },
    Permission.USERS_MANAGE: {
        "name": "Manage users",
        "category": "Operations",
        "description": "Create, disable, and update users.",
    },
    Permission.GROUPS_MANAGE: {
        "name": "Manage groups",
        "category": "Operations",
        "description": "Create groups and manage group membership.",
    },
    Permission.ROLES_MANAGE: {
        "name": "Manage roles",
        "category": "Operations",
        "description": "Create roles and edit role permissions.",
    },
    Permission.OPERATIONS_VIEW: {
        "name": "View operations",
        "category": "Operations",
        "description": "Inspect runtime sessions and operational diagnostics.",
    },
    Permission.AGENTS_MANAGE: {
        "name": "Manage agents",
        "category": "Studio",
        "description": "Create and manage authorized agents.",
    },
    Permission.LLMS_MANAGE: {
        "name": "Manage LLMs",
        "category": "Studio",
        "description": "Manage model provider configurations.",
    },
    Permission.TOOLS_MANAGE: {
        "name": "Manage tools",
        "category": "Studio",
        "description": "Manage user-authored tools.",
    },
    Permission.SKILLS_MANAGE: {
        "name": "Manage skills",
        "category": "Studio",
        "description": "Manage skill assets.",
    },
    Permission.EXTENSIONS_MANAGE: {
        "name": "Manage extensions",
        "category": "Studio",
        "description": "Install, trust, and configure extensions.",
    },
    Permission.CHANNELS_MANAGE: {
        "name": "Manage channels",
        "category": "Studio",
        "description": "Configure external channel bindings.",
    },
    Permission.MEDIA_GENERATION_MANAGE: {
        "name": "Manage media generation",
        "category": "Studio",
        "description": "Configure media generation providers.",
    },
    Permission.WEB_SEARCH_MANAGE: {
        "name": "Manage web search",
        "category": "Studio",
        "description": "Configure web search providers.",
    },
    Permission.STORAGE_VIEW: {
        "name": "View storage",
        "category": "System",
        "description": "View storage backend status.",
    },
}


DEFAULT_ROLE_PERMISSIONS: dict[str, set[Permission]] = {
    "user": {Permission.CLIENT_ACCESS},
    "builder": {
        Permission.CLIENT_ACCESS,
        Permission.STUDIO_ACCESS,
        Permission.AGENTS_MANAGE,
        Permission.TOOLS_MANAGE,
        Permission.SKILLS_MANAGE,
        Permission.STORAGE_VIEW,
    },
    "admin": set(Permission),
}
