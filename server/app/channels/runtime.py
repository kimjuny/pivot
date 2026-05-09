"""Background channel runtimes for websocket and polling transports."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.config import get_settings
from app.db.session import managed_session
from app.models.channel import AgentChannelBinding
from app.services.channel_service import ChannelService
from app.utils.logging_config import get_logger
from sqlmodel import select

logger = get_logger("channel.runtime")


def _load_json_object(raw_value: str | None) -> dict[str, Any]:
    """Parse a JSON object stored in a text column."""
    if not raw_value:
        return {}
    try:
        parsed = json.loads(raw_value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _build_binding_fingerprint(binding: AgentChannelBinding) -> str:
    """Build a restart fingerprint from user-controlled binding config only.

    Why: runtime health updates must not look like credential changes, otherwise
    the supervisor will continuously restart healthy websocket bindings.
    """
    return json.dumps(
        {
            "channel_key": binding.channel_key,
            "enabled": binding.enabled,
            "auth": _load_json_object(binding.auth_config),
            "runtime": _load_json_object(binding.runtime_config),
        },
        sort_keys=True,
        ensure_ascii=False,
    )


def _get_runtime_factory(provider: Any) -> Any | None:
    """Return the provider's create_binding_runtime callable if available.

    Why: websocket and polling providers need background tasks, but the
    ChannelProvider protocol intentionally omits runtime creation so that
    webhook-only providers stay simple.  Duck-typing keeps the check cheap.
    """
    factory = getattr(provider, "create_binding_runtime", None)
    return factory if callable(factory) else None


class ChannelRuntimeManager:
    """Supervise background runtimes for enabled channel bindings."""

    def __init__(self) -> None:
        """Initialize task registries for runtime supervision."""
        self._supervisor_task: asyncio.Task[None] | None = None
        self._binding_tasks: dict[int, asyncio.Task[None]] = {}
        self._binding_stop_events: dict[int, asyncio.Event] = {}
        self._binding_fingerprints: dict[int, str] = {}

    async def start(self) -> None:
        """Start the background supervisor if it is not already running."""
        if self._supervisor_task is not None and not self._supervisor_task.done():
            return
        self._supervisor_task = asyncio.create_task(self._supervise())

    async def stop(self) -> None:
        """Stop the supervisor and all binding runtimes."""
        supervisor_task = self._supervisor_task
        self._supervisor_task = None
        if supervisor_task is not None:
            supervisor_task.cancel()
            await asyncio.gather(supervisor_task, return_exceptions=True)

        binding_ids = list(self._binding_tasks)
        for binding_id in binding_ids:
            await self._stop_binding(binding_id)

    async def _supervise(self) -> None:
        """Continuously reconcile desired websocket bindings with running tasks."""
        scan_interval = get_settings().CHANNEL_RUNTIME_SCAN_INTERVAL_SECONDS
        while True:
            try:
                await self._reconcile_bindings()
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover - defensive logging
                logger.exception("Channel runtime reconciliation failed.")
            await asyncio.sleep(scan_interval)

    async def _reconcile_bindings(self) -> None:
        """Start, restart, or stop binding runtimes based on DB state."""
        desired_bindings: dict[int, str] = {}
        with managed_session() as session:
            rows = session.exec(
                select(AgentChannelBinding).where(
                    AgentChannelBinding.enabled == True,  # noqa: E712
                )
            ).all()
            channel_service = ChannelService(session)

        for row in rows:
            provider = channel_service._get_channel_provider(row.channel_key)
            if _get_runtime_factory(provider) is None:
                continue
            if not channel_service._is_provider_available_to_agent(
                agent_id=row.agent_id,
                provider=provider,
                enabled_only=True,
            ):
                continue
            binding_id = row.id
            if binding_id is None:
                continue
            fingerprint = _build_binding_fingerprint(row)
            desired_bindings[binding_id] = fingerprint

            existing_task = self._binding_tasks.get(binding_id)
            previous_fingerprint = self._binding_fingerprints.get(binding_id)
            if (
                existing_task is not None
                and not existing_task.done()
                and previous_fingerprint == fingerprint
            ):
                continue

            if existing_task is not None:
                await self._stop_binding(binding_id)

            await self._start_binding(binding_id, provider, fingerprint)

        for binding_id in list(self._binding_tasks):
            if binding_id not in desired_bindings:
                await self._stop_binding(binding_id)

    async def _start_binding(
        self,
        binding_id: int,
        provider: Any,
        fingerprint: str,
    ) -> None:
        """Start a background runtime for one binding via its provider factory."""
        factory = _get_runtime_factory(provider)
        if factory is None:
            logger.warning(
                "No runtime factory for %s binding %s — skipping.",
                provider.manifest.key,
                binding_id,
            )
            return

        logger.info(
            "Starting %s runtime for binding %s.",
            provider.manifest.name,
            binding_id,
        )
        stop_event = asyncio.Event()
        runtime = factory(binding_id)
        task = asyncio.create_task(runtime.run(stop_event))
        self._binding_tasks[binding_id] = task
        self._binding_stop_events[binding_id] = stop_event
        self._binding_fingerprints[binding_id] = fingerprint

    async def _stop_binding(self, binding_id: int) -> None:
        """Stop and forget one binding runtime."""
        stop_event = self._binding_stop_events.pop(binding_id, None)
        if stop_event is not None:
            stop_event.set()

        task = self._binding_tasks.pop(binding_id, None)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        self._binding_fingerprints.pop(binding_id, None)


channel_runtime_manager = ChannelRuntimeManager()
