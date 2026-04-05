"""Background channel runtimes for websocket and polling transports."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.channels.registry import get_channel_provider
from app.channels.work_wechat_socket import (
    WORK_WECHAT_CALLBACK_COMMAND,
    WORK_WECHAT_EVENT_COMMAND,
    WORK_WECHAT_RESPONSE_COMMAND,
    WORK_WECHAT_SEND_COMMAND,
    WORK_WECHAT_WELCOME_COMMAND,
    WorkWeChatSocketConnection,
    build_work_wechat_inbound_event,
    build_work_wechat_markdown_send,
    build_work_wechat_stream_reply,
    build_work_wechat_welcome_reply,
    generate_work_wechat_req_id,
)
from app.config import get_settings
from app.db.session import managed_session
from app.models.channel import AgentChannelBinding, ChannelEventLog
from app.services.channel_service import ChannelService
from app.utils.logging_config import get_logger
from sqlmodel import select

if TYPE_CHECKING:
    from app.channels.types import (
        ChannelMessageContext,
        ChannelOutboundAction,
    )

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


class WorkWeChatBindingRuntime:
    """Maintain one official Work WeChat websocket binding."""

    def __init__(self, binding_id: int) -> None:
        """Store the binding identifier.

        Args:
            binding_id: Agent-channel binding primary key.
        """
        self.binding_id = binding_id

    async def run(self, stop_event: asyncio.Event) -> None:
        """Run the reconnecting websocket loop for one binding.

        Args:
            stop_event: Signals that the binding should stop.
        """
        reconnect_delay_seconds = 1
        while not stop_event.is_set():
            binding_state = self._load_binding_state()
            if binding_state is None:
                return

            auth_config = binding_state["auth_config"]
            bot_id = str(auth_config.get("bot_id", "")).strip()
            secret = str(auth_config.get("secret", "")).strip()
            if not bot_id or not secret:
                self._update_health(
                    status="error",
                    message="Missing Work WeChat bot_id or secret.",
                )
                await asyncio.sleep(reconnect_delay_seconds)
                reconnect_delay_seconds = min(reconnect_delay_seconds * 2, 30)
                continue

            self._update_health(
                status="connecting",
                message="Connecting to the official Work WeChat websocket.",
            )

            client = WorkWeChatSocketConnection(
                bot_id=bot_id,
                secret=secret,
            )
            heartbeat_task: asyncio.Task[None] | None = None
            try:
                await client.connect()
                self._update_health(
                    status="healthy",
                    message="Connected to Work WeChat long connection.",
                )
                reconnect_delay_seconds = 1
                heartbeat_task = asyncio.create_task(
                    self._heartbeat_loop(client, stop_event)
                )

                while not stop_event.is_set():
                    frame = await client.next_inbound_frame()
                    await self._handle_inbound_frame(client, frame)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Work WeChat binding %s disconnected: %s",
                    self.binding_id,
                    exc,
                )
                self._update_health(
                    status="error",
                    message=f"Work WeChat connection lost: {exc!s}",
                )
                await asyncio.sleep(reconnect_delay_seconds)
                reconnect_delay_seconds = min(reconnect_delay_seconds * 2, 30)
            finally:
                if heartbeat_task is not None:
                    heartbeat_task.cancel()
                    await asyncio.gather(heartbeat_task, return_exceptions=True)
                await client.close()

    async def _heartbeat_loop(
        self,
        client: WorkWeChatSocketConnection,
        stop_event: asyncio.Event,
    ) -> None:
        """Keep the Work WeChat socket alive with official heartbeat frames."""
        heartbeat_seconds = get_settings().WORK_WECHAT_WS_HEARTBEAT_SECONDS
        while not stop_event.is_set():
            await asyncio.sleep(heartbeat_seconds)
            if stop_event.is_set():
                return
            await client.send_heartbeat()

    async def _handle_inbound_frame(
        self,
        client: WorkWeChatSocketConnection,
        frame: dict[str, Any],
    ) -> None:
        """Route one inbound Work WeChat callback through channel service."""
        event = build_work_wechat_inbound_event(frame)
        if event is None:
            return

        with managed_session() as session:
            binding = session.get(AgentChannelBinding, self.binding_id)
            if binding is None or not binding.enabled:
                return

            service = ChannelService(session)
            event_log: ChannelEventLog | None = None
            if event.external_event_id:
                event_log = service.get_event_log(
                    channel_binding_id=self.binding_id,
                    external_event_id=event.external_event_id,
                    direction="inbound",
                )
                if event_log is not None:
                    return

            event_log = service.create_event_log(
                channel_binding_id=self.binding_id,
                external_event_id=event.external_event_id,
                direction="inbound",
                status="received",
                payload=event.model_dump(),
            )

            try:
                context = service.build_message_context(event=event)
                async for action in service.stream_inbound_actions(
                    binding=binding,
                    event=event,
                ):
                    await self._send_action(
                        client=client,
                        context=context,
                        action=action,
                    )
                    service.create_event_log(
                        channel_binding_id=self.binding_id,
                        external_event_id=event.external_event_id,
                        direction="outbound",
                        status="sent",
                        payload={
                            "conversation_id": context.conversation_id,
                            "external_user_id": context.user_id,
                            "action": action.model_dump(),
                        },
                    )
                service.update_event_log(event_log, status="processed")
            except Exception as exc:
                service.update_event_log(
                    event_log,
                    status="failed",
                    error_message=str(exc),
                )
                logger.exception(
                    "Failed to process Work WeChat frame for binding %s.",
                    self.binding_id,
                )

    async def _send_action(
        self,
        client: WorkWeChatSocketConnection,
        *,
        context: ChannelMessageContext,
        action: ChannelOutboundAction,
    ) -> None:
        """Send one official Work WeChat action based on callback semantics."""
        if not action.text.strip():
            return

        headers = context.provider_state.get("headers")
        req_id = None
        if isinstance(headers, dict):
            raw_req_id = headers.get("req_id")
            req_id = str(raw_req_id) if raw_req_id is not None else None

        command = str(context.provider_state.get("cmd") or "")
        if (
            command == WORK_WECHAT_EVENT_COMMAND
            and context.event_type == "enter_chat"
            and req_id
        ):
            await client.send_command(
                WORK_WECHAT_WELCOME_COMMAND,
                build_work_wechat_welcome_reply(action.text),
                req_id=req_id,
            )
            return

        if req_id and command in {
            WORK_WECHAT_CALLBACK_COMMAND,
            WORK_WECHAT_EVENT_COMMAND,
        }:
            delivery_slots = context.provider_state.setdefault("delivery_slots", {})
            if not isinstance(delivery_slots, dict):
                delivery_slots = {}
                context.provider_state["delivery_slots"] = delivery_slots
            slot_state = delivery_slots.get(action.slot)
            if not isinstance(slot_state, dict):
                slot_state = {}
                delivery_slots[action.slot] = slot_state

            stream_id = slot_state.get("stream_id")
            if not isinstance(stream_id, str) or not stream_id:
                stream_id = generate_work_wechat_req_id("stream")
                slot_state["stream_id"] = stream_id
            await client.send_command(
                WORK_WECHAT_RESPONSE_COMMAND,
                build_work_wechat_stream_reply(
                    action.text,
                    stream_id=stream_id,
                    finish=action.is_terminal,
                ),
                req_id=req_id,
            )
            return

        if context.conversation_id is None:
            raise ValueError("Work WeChat reply is missing a conversation identifier.")

        await client.send_command(
            WORK_WECHAT_SEND_COMMAND,
            build_work_wechat_markdown_send(context.conversation_id, action.text),
        )

    def _load_binding_state(self) -> dict[str, Any] | None:
        """Load the current binding row and parsed configs from the database."""
        with managed_session() as session:
            binding = session.get(AgentChannelBinding, self.binding_id)
            if binding is None or not binding.enabled:
                return None
            return {
                "binding_id": binding.id or 0,
                "auth_config": _load_json_object(binding.auth_config),
                "runtime_config": _load_json_object(binding.runtime_config),
            }

    def _update_health(self, *, status: str, message: str) -> None:
        """Persist the latest runtime health status for the binding."""
        with managed_session() as session:
            binding = session.get(AgentChannelBinding, self.binding_id)
            if binding is None:
                return
            binding.last_health_status = status
            binding.last_health_message = message
            binding.last_health_check_at = datetime.now(UTC)
            session.add(binding)
            session.commit()


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
                    AgentChannelBinding.channel_key == "work_wechat",
                )
            ).all()

        for row in rows:
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

            await self._start_binding(binding_id, fingerprint)

        for binding_id in list(self._binding_tasks):
            if binding_id not in desired_bindings:
                await self._stop_binding(binding_id)

    async def _start_binding(self, binding_id: int, fingerprint: str) -> None:
        """Start a websocket runtime for one binding."""
        provider = get_channel_provider("work_wechat")
        logger.info(
            "Starting %s runtime for binding %s.",
            provider.manifest.name,
            binding_id,
        )
        stop_event = asyncio.Event()
        runtime = WorkWeChatBindingRuntime(binding_id)
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
