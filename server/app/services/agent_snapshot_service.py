"""Services for persisted agent draft and release snapshots."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from app.models.agent import Agent, Connection, Scene, Subscene
from app.models.agent_release import AgentRelease, AgentSavedDraft
from app.models.channel import AgentChannelBinding
from app.models.web_search import AgentWebSearchBinding
from sqlmodel import Session, col, desc, select


def _load_json_array(raw_value: str | None) -> list[str] | None:
    """Parse one stored JSON string list into a normalized Python list.

    Args:
        raw_value: JSON text stored on the agent row.

    Returns:
        Sorted unique strings, or ``None`` when the value means unrestricted.
    """
    if raw_value is None:
        return None
    try:
        parsed = json.loads(raw_value)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    values = sorted(
        {
            item.strip()
            for item in parsed
            if isinstance(item, str) and item.strip()
        }
    )
    return values


def _load_json_object(raw_value: str | None) -> dict[str, Any]:
    """Parse a JSON object stored in a text column."""
    if not raw_value:
        return {}
    try:
        parsed = json.loads(raw_value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _dump_json(payload: Any) -> str:
    """Serialize one payload into canonical compact JSON text."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _hash_payload(payload: Any) -> str:
    """Return a stable hash for one canonical JSON payload."""
    return hashlib.sha256(_dump_json(payload).encode("utf-8")).hexdigest()


def _format_name_list(names: list[str], *, noun: str, verb: str) -> str:
    """Render one concise audit sentence for a list of changed names."""
    if not names:
        return ""
    preview = ", ".join(names[:3])
    suffix = "" if len(names) <= 3 else f", +{len(names) - 3} more"
    return f"{noun} {verb}: {preview}{suffix}"


class AgentSnapshotService:
    """Service for normalized agent snapshots, draft baselines, and releases."""

    def __init__(self, db: Session) -> None:
        """Store the active session for snapshot operations."""
        self.db = db

    def _get_agent_or_raise(self, agent_id: int) -> Agent:
        """Load one agent or raise a descriptive error."""
        agent = self.db.get(Agent, agent_id)
        if agent is None:
            raise ValueError("Agent not found.")
        return agent

    def _normalize_scene_snapshot(self, scene: Scene) -> dict[str, Any]:
        """Build one canonical scene snapshot with nested graph data."""
        subscenes = self.db.exec(
            select(Subscene)
            .where(Subscene.scene_id == scene.id)
            .order_by(col(Subscene.id))
        ).all()
        connections = self.db.exec(
            select(Connection)
            .where(Connection.scene_id == scene.id)
            .order_by(col(Connection.id))
        ).all()
        connections_by_source: dict[str, list[Connection]] = {}
        for connection in connections:
            connections_by_source.setdefault(connection.from_subscene, []).append(
                connection
            )

        return {
            "id": scene.id,
            "name": scene.name,
            "description": scene.description,
            "subscenes": [
                {
                    "id": subscene.id,
                    "name": subscene.name,
                    "type": subscene.type,
                    "state": subscene.state,
                    "description": subscene.description,
                    "mandatory": subscene.mandatory,
                    "objective": subscene.objective,
                    "connections": [
                        {
                            "id": connection.id,
                            "name": connection.name,
                            "condition": connection.condition,
                            "from_subscene": connection.from_subscene,
                            "to_subscene": connection.to_subscene,
                        }
                        for connection in connections_by_source.get(subscene.name, [])
                    ],
                }
                for subscene in subscenes
            ],
        }

    def _normalize_channel_binding(
        self, binding: AgentChannelBinding
    ) -> dict[str, Any]:
        """Build one canonical channel-binding snapshot.

        Why: auth secrets should still participate in change detection without
        leaking raw secret values into release history UIs.
        """
        auth_config = _load_json_object(binding.auth_config)
        runtime_config = _load_json_object(binding.runtime_config)
        return {
            "id": binding.id,
            "channel_key": binding.channel_key,
            "name": binding.name,
            "enabled": binding.enabled,
            "auth_config_keys": sorted(auth_config.keys()),
            "auth_config_hash": _hash_payload(auth_config),
            "runtime_config": runtime_config,
        }

    def _normalize_web_search_binding(
        self, binding: AgentWebSearchBinding
    ) -> dict[str, Any]:
        """Build one canonical web-search binding snapshot."""
        auth_config = _load_json_object(binding.auth_config)
        runtime_config = _load_json_object(binding.runtime_config)
        return {
            "id": binding.id,
            "provider_key": binding.provider_key,
            "enabled": binding.enabled,
            "auth_config_keys": sorted(auth_config.keys()),
            "auth_config_hash": _hash_payload(auth_config),
            "runtime_config": runtime_config,
        }

    def build_current_snapshot(self, agent_id: int) -> dict[str, Any]:
        """Build the normalized current persisted snapshot for one agent.

        Args:
            agent_id: Agent whose multi-table state should be normalized.

        Returns:
            Canonical snapshot payload ready for hashing and persistence.

        Raises:
            ValueError: If the agent does not exist.
        """
        agent = self._get_agent_or_raise(agent_id)
        scenes = self.db.exec(
            select(Scene).where(Scene.agent_id == agent_id).order_by(col(Scene.id))
        ).all()
        channel_bindings = self.db.exec(
            select(AgentChannelBinding)
            .where(AgentChannelBinding.agent_id == agent_id)
            .order_by(col(AgentChannelBinding.id))
        ).all()
        web_search_bindings = self.db.exec(
            select(AgentWebSearchBinding)
            .where(AgentWebSearchBinding.agent_id == agent_id)
            .order_by(col(AgentWebSearchBinding.id))
        ).all()

        return {
            "schema_version": 1,
            "agent": {
                "id": agent.id,
                "name": agent.name,
                "description": agent.description,
                "llm_id": agent.llm_id,
                "skill_resolution_llm_id": agent.skill_resolution_llm_id,
                "session_idle_timeout_minutes": agent.session_idle_timeout_minutes,
                "sandbox_timeout_seconds": agent.sandbox_timeout_seconds,
                "compact_threshold_percent": agent.compact_threshold_percent,
                "is_active": agent.is_active,
                "max_iteration": agent.max_iteration,
                "tool_ids": _load_json_array(agent.tool_ids),
                "skill_ids": _load_json_array(agent.skill_ids),
            },
            "scenes": [self._normalize_scene_snapshot(scene) for scene in scenes],
            "channel_bindings": [
                self._normalize_channel_binding(binding) for binding in channel_bindings
            ],
            "web_search_bindings": [
                self._normalize_web_search_binding(binding)
                for binding in web_search_bindings
            ],
        }

    def _load_snapshot_json(self, raw_value: str) -> dict[str, Any]:
        """Parse one stored snapshot JSON payload."""
        parsed = json.loads(raw_value)
        return parsed if isinstance(parsed, dict) else {}

    def _list_release_models(self, agent_id: int) -> list[AgentRelease]:
        """Return all releases for one agent in newest-first order."""
        statement = (
            select(AgentRelease)
            .where(AgentRelease.agent_id == agent_id)
            .order_by(desc(AgentRelease.version))
        )
        return list(self.db.exec(statement).all())

    def _get_latest_release_model(self, agent_id: int) -> AgentRelease | None:
        """Return the latest published release for one agent, if any."""
        return self.db.exec(
            select(AgentRelease)
            .where(AgentRelease.agent_id == agent_id)
            .order_by(desc(AgentRelease.version))
        ).first()

    def _serialize_release(self, release: AgentRelease) -> dict[str, Any]:
        """Render one release row into a frontend-friendly response shape."""
        return {
            "id": release.id or 0,
            "version": release.version,
            "release_note": release.release_note,
            "change_summary": json.loads(release.change_summary_json),
            "published_by": release.published_by,
            "created_at": release.created_at.replace(tzinfo=UTC).isoformat(),
        }

    def _summarize_initial_snapshot(self, snapshot: dict[str, Any]) -> list[str]:
        """Build a first-release summary from an empty baseline."""
        changes = ["Initial release from saved draft"]
        agent_payload = snapshot["agent"]
        if agent_payload["name"] or agent_payload["description"]:
            changes.append("Agent basics configured")
        if (
            agent_payload["llm_id"] is not None
            or agent_payload["skill_resolution_llm_id"] is not None
        ):
            changes.append("Runtime settings configured")
        tool_ids = agent_payload["tool_ids"]
        if tool_ids is not None:
            if tool_ids:
                changes.append(_format_name_list(tool_ids, noun="Tools", verb="enabled"))
            else:
                changes.append("Tool access restricted to no tools")
        skill_ids = agent_payload["skill_ids"]
        if skill_ids is not None:
            if skill_ids:
                changes.append(
                    _format_name_list(skill_ids, noun="Skills", verb="enabled")
                )
            else:
                changes.append("Skill access restricted to no skills")
        scenes = snapshot["scenes"]
        if scenes:
            scene_names = [scene["name"] for scene in scenes if scene["name"]]
            if scene_names:
                changes.append(
                    _format_name_list(scene_names, noun="Scenes", verb="configured")
                )
        channel_bindings = snapshot["channel_bindings"]
        if channel_bindings:
            channel_names = [
                binding["name"] or binding["channel_key"]
                for binding in channel_bindings
            ]
            changes.append(
                _format_name_list(
                    channel_names, noun="Channel bindings", verb="configured"
                )
            )
        web_search_bindings = snapshot["web_search_bindings"]
        if web_search_bindings:
            provider_keys = [
                binding["provider_key"] for binding in web_search_bindings
            ]
            changes.append(
                _format_name_list(
                    provider_keys, noun="Web search providers", verb="configured"
                )
            )
        return changes

    def _compare_named_collection(
        self,
        before_items: list[dict[str, Any]],
        after_items: list[dict[str, Any]],
        *,
        key_field: str,
        label_field: str,
        noun: str,
    ) -> list[str]:
        """Summarize added, removed, and updated rows inside one collection."""
        before_map = {str(item[key_field]): item for item in before_items}
        after_map = {str(item[key_field]): item for item in after_items}
        added = [
            str(item[label_field])
            for key, item in after_map.items()
            if key not in before_map
        ]
        removed = [
            str(item[label_field])
            for key, item in before_map.items()
            if key not in after_map
        ]
        updated = [
            str(item[label_field])
            for key, item in after_map.items()
            if key in before_map and before_map[key] != item
        ]

        changes: list[str] = []
        added_summary = _format_name_list(added, noun=noun, verb="added")
        removed_summary = _format_name_list(removed, noun=noun, verb="removed")
        updated_summary = _format_name_list(updated, noun=noun, verb="updated")
        if added_summary:
            changes.append(added_summary)
        if removed_summary:
            changes.append(removed_summary)
        if updated_summary:
            changes.append(updated_summary)
        return changes

    def summarize_snapshot_diff(
        self,
        before_snapshot: dict[str, Any] | None,
        after_snapshot: dict[str, Any],
    ) -> list[str]:
        """Build concise audit strings for one snapshot diff.

        Args:
            before_snapshot: Previous snapshot baseline, if one exists.
            after_snapshot: Current candidate snapshot.

        Returns:
            Human-readable summary strings grouped by major module changes.
        """
        if before_snapshot is None:
            return self._summarize_initial_snapshot(after_snapshot)

        changes: list[str] = []
        before_agent = before_snapshot["agent"]
        after_agent = after_snapshot["agent"]

        basics_keys = {"name", "description", "is_active"}
        runtime_keys = {
            "llm_id",
            "skill_resolution_llm_id",
            "session_idle_timeout_minutes",
            "sandbox_timeout_seconds",
            "compact_threshold_percent",
            "max_iteration",
        }
        if any(before_agent[key] != after_agent[key] for key in basics_keys):
            changes.append("Agent basics updated")
        if any(before_agent[key] != after_agent[key] for key in runtime_keys):
            changes.append("Runtime settings updated")

        before_tools = before_agent["tool_ids"]
        after_tools = after_agent["tool_ids"]
        if before_tools != after_tools:
            if before_tools is None and after_tools is None:
                pass
            elif after_tools is None:
                changes.append("Tool access is now unrestricted")
            elif after_tools:
                changes.append(
                    _format_name_list(after_tools, noun="Tools", verb="enabled")
                )
            else:
                changes.append("Tool access restricted to no tools")

        before_skills = before_agent["skill_ids"]
        after_skills = after_agent["skill_ids"]
        if before_skills != after_skills:
            if before_skills is None and after_skills is None:
                pass
            elif after_skills is None:
                changes.append("Skill access is now unrestricted")
            elif after_skills:
                changes.append(
                    _format_name_list(after_skills, noun="Skills", verb="enabled")
                )
            else:
                changes.append("Skill access restricted to no skills")

        changes.extend(
            self._compare_named_collection(
                before_snapshot["scenes"],
                after_snapshot["scenes"],
                key_field="id",
                label_field="name",
                noun="Scenes",
            )
        )
        changes.extend(
            self._compare_named_collection(
                before_snapshot["channel_bindings"],
                after_snapshot["channel_bindings"],
                key_field="id",
                label_field="name",
                noun="Channel bindings",
            )
        )
        changes.extend(
            self._compare_named_collection(
                before_snapshot["web_search_bindings"],
                after_snapshot["web_search_bindings"],
                key_field="id",
                label_field="provider_key",
                noun="Web search providers",
            )
        )

        if not changes:
            changes.append("No unpublished changes")
        return changes

    def get_or_create_saved_draft(
        self, agent_id: int, *, saved_by: str | None = None
    ) -> AgentSavedDraft:
        """Return the saved draft row for one agent, creating it if needed."""
        self._get_agent_or_raise(agent_id)
        existing = self.db.exec(
            select(AgentSavedDraft).where(AgentSavedDraft.agent_id == agent_id)
        ).first()
        if existing is not None:
            return existing
        snapshot = self.build_current_snapshot(agent_id)
        now = datetime.now(UTC)
        draft = AgentSavedDraft(
            agent_id=agent_id,
            snapshot_json=_dump_json(snapshot),
            snapshot_hash=_hash_payload(snapshot),
            saved_by=saved_by,
            saved_at=now,
        )
        self.db.add(draft)
        self.db.commit()
        self.db.refresh(draft)
        return draft

    def save_draft(
        self, agent_id: int, *, saved_by: str | None = None
    ) -> AgentSavedDraft:
        """Persist the current normalized agent snapshot as the saved draft."""
        snapshot = self.build_current_snapshot(agent_id)
        now = datetime.now(UTC)
        draft = self.db.exec(
            select(AgentSavedDraft).where(AgentSavedDraft.agent_id == agent_id)
        ).first()
        if draft is None:
            draft = AgentSavedDraft(
                agent_id=agent_id,
                snapshot_json=_dump_json(snapshot),
                snapshot_hash=_hash_payload(snapshot),
                saved_by=saved_by,
                saved_at=now,
            )
        else:
            draft.snapshot_json = _dump_json(snapshot)
            draft.snapshot_hash = _hash_payload(snapshot)
            draft.saved_by = saved_by
            draft.saved_at = now
        self.db.add(draft)
        self.db.commit()
        self.db.refresh(draft)
        return draft

    def list_releases(self, agent_id: int) -> list[dict[str, Any]]:
        """List all immutable releases for one agent."""
        self._get_agent_or_raise(agent_id)
        return [
            self._serialize_release(release)
            for release in self._list_release_models(agent_id)
        ]

    def get_draft_state(self, agent_id: int) -> dict[str, Any]:
        """Return saved-draft and release metadata for the editor toolbar."""
        draft = self.get_or_create_saved_draft(agent_id)
        latest_release = self._get_latest_release_model(agent_id)
        draft_snapshot = self._load_snapshot_json(draft.snapshot_json)
        latest_release_snapshot = (
            self._load_snapshot_json(latest_release.snapshot_json)
            if latest_release is not None
            else None
        )
        publish_summary = self.summarize_snapshot_diff(
            latest_release_snapshot,
            draft_snapshot,
        )
        has_publishable_changes = (
            latest_release is None
            or latest_release.snapshot_hash != draft.snapshot_hash
        )
        if not has_publishable_changes:
            publish_summary = []

        return {
            "saved_draft": {
                "saved_at": draft.saved_at.replace(tzinfo=UTC).isoformat(),
                "saved_by": draft.saved_by,
                "snapshot_hash": draft.snapshot_hash,
            },
            "latest_release": (
                self._serialize_release(latest_release)
                if latest_release is not None
                else None
            ),
            "has_publishable_changes": has_publishable_changes,
            "publish_summary": publish_summary,
            "release_history": [
                self._serialize_release(release)
                for release in self._list_release_models(agent_id)[:10]
            ],
        }

    def publish_saved_draft(
        self,
        agent_id: int,
        *,
        release_note: str | None,
        published_by: str | None,
    ) -> dict[str, Any]:
        """Create one immutable release from the current saved draft."""
        draft = self.get_or_create_saved_draft(agent_id)
        latest_release = self._get_latest_release_model(agent_id)
        if latest_release is not None and latest_release.snapshot_hash == draft.snapshot_hash:
            raise ValueError("The current saved draft is already published.")

        latest_release_snapshot = (
            self._load_snapshot_json(latest_release.snapshot_json)
            if latest_release is not None
            else None
        )
        draft_snapshot = self._load_snapshot_json(draft.snapshot_json)
        change_summary = self.summarize_snapshot_diff(
            latest_release_snapshot,
            draft_snapshot,
        )
        next_version = 1 if latest_release is None else latest_release.version + 1
        release = AgentRelease(
            agent_id=agent_id,
            version=next_version,
            snapshot_json=draft.snapshot_json,
            snapshot_hash=draft.snapshot_hash,
            release_note=(release_note.strip() or None) if release_note else None,
            change_summary_json=_dump_json(change_summary),
            published_by=published_by,
            created_at=datetime.now(UTC),
        )
        self.db.add(release)
        self.db.commit()
        self.db.refresh(release)
        return self.get_draft_state(agent_id)

    def delete_agent_state(self, agent_id: int) -> None:
        """Delete saved draft and release rows owned by one agent."""
        draft = self.db.exec(
            select(AgentSavedDraft).where(AgentSavedDraft.agent_id == agent_id)
        ).first()
        if draft is not None:
            self.db.delete(draft)
        releases = self.db.exec(
            select(AgentRelease).where(AgentRelease.agent_id == agent_id)
        ).all()
        for release in releases:
            self.db.delete(release)
        self.db.commit()
