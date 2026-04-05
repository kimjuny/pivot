"""Resolve effective runtime configuration for live and released agents."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.models.agent import Agent
from app.models.agent_release import AgentRelease, AgentTestSnapshot
from app.models.session import Session as ConversationSession
from app.services.agent_snapshot_service import AgentSnapshotService
from app.services.extension_service import ExtensionService
from sqlmodel import Session as DBSession, select

if TYPE_CHECKING:
    from app.models.react import ReactTask


def _dump_allowlist_json(names: list[str] | None) -> str | None:
    """Serialize one normalized name allowlist into the agent JSON format.

    Args:
        names: Optional normalized list of names from a release snapshot.

    Returns:
        Canonical JSON array text, or ``None`` when the runtime is unrestricted.
    """
    if names is None:
        return None
    return json.dumps(names, ensure_ascii=False, separators=(",", ":"))


def _parse_snapshot_json(raw_value: str) -> dict[str, Any]:
    """Parse one persisted release snapshot into a dictionary.

    Args:
        raw_value: Canonical JSON payload stored on the release row.

    Returns:
        Parsed dictionary payload.

    Raises:
        ValueError: If the stored snapshot cannot be parsed.
    """
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise ValueError("Stored release snapshot is invalid JSON.") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Stored release snapshot is not an object.")
    return parsed


@dataclass(frozen=True, slots=True)
class AgentRuntimeConfig:
    """Effective runtime configuration resolved for one task or session.

    Attributes:
        agent_id: Stable agent identifier used for workspace and task ownership.
        agent_name: Human-readable agent name for error reporting.
        release_id: Published release pinned to the session, if any.
        llm_id: Primary LLM backing the runtime.
        session_idle_timeout_minutes: Idle timeout used by the client shell.
        sandbox_timeout_seconds: Sandbox timeout applied to tool execution.
        compact_threshold_percent: Context-usage threshold for compaction.
        max_iteration: Maximum recursion depth for newly created tasks.
        raw_tool_ids: JSON-encoded tool allowlist matching the agent row format.
        raw_skill_ids: JSON-encoded skill allowlist matching the agent row format.
        source: ``"release"`` when loaded from a published snapshot, otherwise
            ``"live"`` for mutable agent state fallback.
    """

    agent_id: int
    agent_name: str
    release_id: int | None
    llm_id: int | None
    session_idle_timeout_minutes: int
    sandbox_timeout_seconds: int
    compact_threshold_percent: int
    max_iteration: int
    raw_tool_ids: str | None
    raw_skill_ids: str | None
    extension_bundle: list[dict[str, Any]]
    source: str


class AgentReleaseRuntimeService:
    """Resolve the effective runtime config for one live agent or release.

    Why: user sessions are pinned to a published release, but execution paths
    still need a simple reusable way to load those released settings without
    duplicating snapshot parsing inside runtime services.
    """

    def __init__(self, db: DBSession) -> None:
        """Store the active database session for runtime resolution.

        Args:
            db: Database session used to load agents, sessions, and releases.
        """
        self.db = db

    def resolve_for_agent(self, agent_id: int) -> AgentRuntimeConfig:
        """Resolve the current mutable runtime for one live agent row.

        Args:
            agent_id: Stable agent identifier.

        Returns:
            Effective runtime config derived from the current agent row.

        Raises:
            ValueError: If the agent does not exist.
        """
        agent = self._get_agent_or_raise(agent_id)
        return AgentRuntimeConfig(
            agent_id=agent.id or 0,
            agent_name=agent.name,
            release_id=None,
            llm_id=agent.llm_id,
            session_idle_timeout_minutes=agent.session_idle_timeout_minutes,
            sandbox_timeout_seconds=agent.sandbox_timeout_seconds,
            compact_threshold_percent=agent.compact_threshold_percent,
            max_iteration=agent.max_iteration,
            raw_tool_ids=agent.tool_ids,
            raw_skill_ids=agent.skill_ids,
            extension_bundle=ExtensionService(self.db).build_agent_extension_snapshot(
                agent.id or 0
            ),
            source="live",
        )

    def resolve_for_session(
        self,
        session_id: str,
        *,
        fallback_to_live_agent: bool = True,
    ) -> AgentRuntimeConfig:
        """Resolve runtime config for one persisted conversation session.

        Args:
            session_id: Stable session UUID.
            fallback_to_live_agent: Whether legacy sessions without release pinning
                should fall back to the current live agent row.

        Returns:
            Effective runtime config for the session.

        Raises:
            ValueError: If the session is missing or its runtime cannot be resolved.
        """
        session = self._get_session_or_raise(session_id)
        if session.test_snapshot_id is not None:
            return self.resolve_for_test_snapshot(
                agent_id=session.agent_id,
                test_snapshot_id=session.test_snapshot_id,
            )
        if session.release_id is None:
            if fallback_to_live_agent:
                return self.resolve_for_agent(session.agent_id)
            raise ValueError("Session does not have a pinned release.")
        return self.resolve_for_release(
            agent_id=session.agent_id,
            release_id=session.release_id,
        )

    def resolve_for_task(
        self,
        task: ReactTask,
        *,
        fallback_to_live_agent: bool = True,
    ) -> AgentRuntimeConfig:
        """Resolve runtime config for one task row.

        Args:
            task: Task whose backing runtime configuration should be loaded.
            fallback_to_live_agent: Whether tasks without session release pinning
                may fall back to the current mutable agent row.

        Returns:
            Effective runtime config for the task.
        """
        if task.session_id:
            return self.resolve_for_session(
                task.session_id,
                fallback_to_live_agent=fallback_to_live_agent,
            )
        return self.resolve_for_agent(task.agent_id)

    def resolve_for_release(
        self,
        *,
        agent_id: int,
        release_id: int,
    ) -> AgentRuntimeConfig:
        """Resolve runtime config from one published release snapshot.

        Args:
            agent_id: Agent expected to own the release.
            release_id: Stable published release identifier.

        Returns:
            Effective runtime config reconstructed from the release snapshot.

        Raises:
            ValueError: If the release is missing or does not match the agent.
        """
        release = self.db.get(AgentRelease, release_id)
        if release is None:
            raise ValueError(f"Release {release_id} not found.")
        if release.agent_id != agent_id:
            raise ValueError("Release does not belong to the requested agent.")

        return self._build_runtime_config_from_snapshot(
            agent_id=agent_id,
            snapshot=_parse_snapshot_json(release.snapshot_json),
            release_id=release_id,
            source="release",
        )

    def resolve_for_test_snapshot(
        self,
        *,
        agent_id: int,
        test_snapshot_id: int,
    ) -> AgentRuntimeConfig:
        """Resolve runtime config from one frozen Studio test snapshot."""
        snapshot = self.db.get(AgentTestSnapshot, test_snapshot_id)
        if snapshot is None:
            raise ValueError(f"Studio test snapshot {test_snapshot_id} not found.")
        if snapshot.agent_id != agent_id:
            raise ValueError("Studio test snapshot does not belong to the agent.")
        return self._build_runtime_config_from_snapshot(
            agent_id=agent_id,
            snapshot=_parse_snapshot_json(snapshot.snapshot_json),
            release_id=None,
            source="studio_test",
        )

    def resolve_for_test_payload(
        self,
        *,
        agent_id: int,
        working_copy_snapshot: dict[str, Any],
    ) -> AgentRuntimeConfig:
        """Resolve runtime config directly from one unsaved Studio working copy."""
        snapshot = AgentSnapshotService(self.db).build_studio_test_snapshot(
            agent_id,
            working_copy_snapshot=working_copy_snapshot,
        )
        return self._build_runtime_config_from_snapshot(
            agent_id=agent_id,
            snapshot=snapshot,
            release_id=None,
            source="studio_test",
        )

    def _build_runtime_config_from_snapshot(
        self,
        *,
        agent_id: int,
        snapshot: dict[str, Any],
        release_id: int | None,
        source: str,
    ) -> AgentRuntimeConfig:
        """Build one runtime config from any canonical snapshot payload."""
        agent_payload = snapshot.get("agent")
        if not isinstance(agent_payload, dict):
            raise ValueError("Snapshot is missing agent runtime data.")

        tool_ids = self._normalize_allowlist(agent_payload.get("tool_ids"))
        skill_ids = self._normalize_allowlist(agent_payload.get("skill_ids"))
        raw_extensions = snapshot.get("extensions")
        if raw_extensions is None:
            extension_bundle: list[dict[str, Any]] = []
        elif isinstance(raw_extensions, list):
            extension_bundle = [
                item for item in raw_extensions if isinstance(item, dict)
            ]
        else:
            raise ValueError("Snapshot extensions payload must be a list.")

        return AgentRuntimeConfig(
            agent_id=agent_id,
            agent_name=self._read_snapshot_string(
                agent_payload,
                "name",
                fallback=self._get_agent_or_raise(agent_id).name,
            ),
            release_id=release_id,
            llm_id=self._read_snapshot_int_or_none(agent_payload, "llm_id"),
            session_idle_timeout_minutes=self._read_snapshot_int(
                agent_payload,
                "session_idle_timeout_minutes",
                fallback=15,
            ),
            sandbox_timeout_seconds=self._read_snapshot_int(
                agent_payload,
                "sandbox_timeout_seconds",
                fallback=60,
            ),
            compact_threshold_percent=self._read_snapshot_int(
                agent_payload,
                "compact_threshold_percent",
                fallback=60,
            ),
            max_iteration=self._read_snapshot_int(
                agent_payload,
                "max_iteration",
                fallback=30,
            ),
            raw_tool_ids=_dump_allowlist_json(tool_ids),
            raw_skill_ids=_dump_allowlist_json(skill_ids),
            extension_bundle=extension_bundle,
            source=source,
        )

    def _get_agent_or_raise(self, agent_id: int) -> Agent:
        """Load one agent row or raise a descriptive error."""
        agent = self.db.get(Agent, agent_id)
        if agent is None:
            raise ValueError(f"Agent {agent_id} not found.")
        return agent

    def _get_session_or_raise(self, session_id: str) -> ConversationSession:
        """Load one conversation session or raise a descriptive error."""
        session = self.db.exec(
            select(ConversationSession).where(
                ConversationSession.session_id == session_id
            )
        ).first()
        if session is None:
            raise ValueError(f"Session {session_id} not found.")
        return session

    @staticmethod
    def _normalize_allowlist(raw_value: Any) -> list[str] | None:
        """Normalize optional release allowlists into sorted unique strings.

        Args:
            raw_value: Parsed ``tool_ids`` or ``skill_ids`` snapshot value.

        Returns:
            ``None`` for unrestricted access, otherwise a sorted unique list.

        Raises:
            ValueError: If the release snapshot contains an invalid allowlist type.
        """
        if raw_value is None:
            return None
        if not isinstance(raw_value, list):
            raise ValueError("Release snapshot contains an invalid allowlist.")

        normalized = sorted(
            {
                item.strip()
                for item in raw_value
                if isinstance(item, str) and item.strip()
            }
        )
        return normalized

    @staticmethod
    def _read_snapshot_int(
        payload: dict[str, Any],
        key: str,
        *,
        fallback: int,
    ) -> int:
        """Read one integer field from a release snapshot.

        Args:
            payload: Parsed release agent payload.
            key: Field name to extract.
            fallback: Default value used when the field is missing.

        Returns:
            Integer runtime value.

        Raises:
            ValueError: If the field exists but is not an integer.
        """
        raw_value = payload.get(key, fallback)
        if not isinstance(raw_value, int):
            raise ValueError(f"Release snapshot field '{key}' must be an integer.")
        return raw_value

    @staticmethod
    def _read_snapshot_int_or_none(
        payload: dict[str, Any],
        key: str,
    ) -> int | None:
        """Read one optional integer field from a release snapshot."""
        raw_value = payload.get(key)
        if raw_value is None:
            return None
        if not isinstance(raw_value, int):
            raise ValueError(
                f"Release snapshot field '{key}' must be an integer or null."
            )
        return raw_value

    @staticmethod
    def _read_snapshot_string(
        payload: dict[str, Any],
        key: str,
        *,
        fallback: str,
    ) -> str:
        """Read one optional string field from a release snapshot."""
        raw_value = payload.get(key)
        if raw_value is None:
            return fallback
        if not isinstance(raw_value, str):
            raise ValueError(f"Release snapshot field '{key}' must be a string.")
        return raw_value
