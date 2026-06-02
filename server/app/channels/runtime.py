"""Background channel runtimes for websocket and polling transports."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from app.config import get_settings
from app.db.session import managed_session
from app.models.channel import AgentChannelBinding
from app.services.channel_runtime_health_service import ChannelRuntimeHealthService
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


def _build_binding_fingerprint(
    binding: AgentChannelBinding,
    provider_version: str | None = None,
) -> str:
    """Build a restart fingerprint from binding config and provider version.

    Why: runtime health updates must not look like credential changes, otherwise
    the supervisor will continuously restart healthy websocket bindings.
    Including ``provider_version`` ensures the runtime is restarted when the
    backing extension is upgraded, so the new module code takes effect.
    """
    return json.dumps(
        {
            "channel_key": binding.channel_key,
            "enabled": binding.enabled,
            "auth": _load_json_object(binding.auth_config),
            "runtime": _load_json_object(binding.runtime_config),
            "provider_version": provider_version,
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


def _classify_runtime_error(provider: Any, exc: BaseException) -> str:
    """Return a provider-specific or generic runtime error kind."""
    classifier = getattr(provider, "classify_runtime_error", None)
    if callable(classifier):
        try:
            result = classifier(exc)
            if isinstance(result, str) and result:
                return result
        except Exception:
            logger.exception(
                "Channel provider %s failed to classify runtime error.",
                getattr(getattr(provider, "manifest", None), "key", "unknown"),
            )
    return ChannelRuntimeHealthService.classify_exception(exc)


class ChannelRuntimeManager:
    """Supervise background runtimes for enabled channel bindings."""

    def __init__(self) -> None:
        """Initialize task registries for runtime supervision."""
        self._supervisor_task: asyncio.Task[None] | None = None
        self._binding_tasks: dict[int, asyncio.Task[None]] = {}
        self._binding_stop_events: dict[int, asyncio.Event] = {}
        self._binding_fingerprints: dict[int, str] = {}
        self._binding_providers: dict[int, Any] = {}

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
            fingerprint = _build_binding_fingerprint(
                row,
                provider_version=provider.manifest.extension_version,
            )
            desired_bindings[binding_id] = fingerprint

            if self._is_retry_deferred(row):
                continue

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
        with managed_session() as session:
            ChannelRuntimeHealthService(session).mark_starting(
                binding_id,
                f"Starting {provider.manifest.name} runtime.",
            )
        stop_event = asyncio.Event()
        runtime = factory(binding_id)
        task = asyncio.create_task(runtime.run(stop_event))
        task.add_done_callback(
            lambda completed_task, completed_binding_id=binding_id: (
                self._log_binding_task_result(completed_binding_id, completed_task)
            )
        )
        self._binding_tasks[binding_id] = task
        self._binding_stop_events[binding_id] = stop_event
        self._binding_fingerprints[binding_id] = fingerprint
        self._binding_providers[binding_id] = provider

    def _log_binding_task_result(
        self,
        binding_id: int,
        task: asyncio.Task[None],
    ) -> None:
        """Log unexpected runtime task failures for post-mortem debugging."""
        if task.cancelled():
            return
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        if exc is not None:
            logger.error(
                "Channel runtime task for binding %s stopped unexpectedly.",
                binding_id,
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            provider = self._binding_providers.get(binding_id)
            with managed_session() as session:
                binding = session.get(AgentChannelBinding, binding_id)
                if binding is None or not binding.enabled:
                    return
                error_kind = (
                    _classify_runtime_error(provider, exc)
                    if provider is not None
                    else ChannelRuntimeHealthService.classify_exception(exc)
                )
                ChannelRuntimeHealthService(session).record_failure(
                    binding_id,
                    message=f"Runtime stopped unexpectedly: {exc!s}",
                    error_kind=error_kind,
                    error=exc,
                )
            return

        with managed_session() as session:
            binding = session.get(AgentChannelBinding, binding_id)
            if binding is None or not binding.enabled:
                return
            ChannelRuntimeHealthService(session).record_failure(
                binding_id,
                message="Runtime stopped unexpectedly.",
                error_kind="unknown",
            )

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
        self._binding_providers.pop(binding_id, None)

    @staticmethod
    def _is_retry_deferred(binding: AgentChannelBinding) -> bool:
        """Return whether a failed binding is still inside its retry window."""
        if (
            binding.last_health_status == "error"
            and (binding.consecutive_failure_count or 0) > 0
            and binding.next_retry_at is None
        ):
            return True
        if binding.next_retry_at is None:
            return False
        retry_at = binding.next_retry_at
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        return retry_at > datetime.now(UTC)


channel_runtime_manager = ChannelRuntimeManager()
