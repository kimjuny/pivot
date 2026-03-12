"""Built-in channel provider implementations."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import requests
from app.channels.types import (
    ChannelConfigField,
    ChannelEndpointInfo,
    ChannelInboundEvent,
    ChannelManifest,
    ChannelMessageContext,
    ChannelOutboundAction,
    ChannelTestResult,
    ChannelWebhookResult,
)
from app.channels.work_wechat_socket import probe_work_wechat_credentials
from app.config import get_settings


class BaseBuiltinProvider:
    """Base helper for built-in provider adapters."""

    manifest: ChannelManifest

    def validate_config(
        self,
        auth_config: dict[str, Any],
        runtime_config: dict[str, Any],
    ) -> None:
        """Validate required schema-driven fields for a provider."""
        del runtime_config
        for field in self.manifest.auth_schema:
            if field.required and not str(auth_config.get(field.key, "")).strip():
                raise ValueError(f"Missing required auth field: {field.label}")

    def build_endpoint_infos(self, binding_id: int) -> list[ChannelEndpointInfo]:
        """Return generic setup links derived from the configured public URLs."""
        settings = get_settings()
        return [
            ChannelEndpointInfo(
                label="Webhook URL",
                method="GET/POST",
                url=(
                    f"{settings.server_public_base_url}/api/channel-endpoints/"
                    f"{binding_id}/webhook"
                ),
                description=(
                    "Configure this URL in the provider console for inbound events."
                ),
            ),
            ChannelEndpointInfo(
                label="Web Linking Base",
                method="GET",
                url=f"{settings.web_public_base_url}/channel-link",
                description=(
                    "External users will receive a tokenized link under this base path."
                ),
            ),
        ]

    def handle_webhook(
        self,
        auth_config: dict[str, Any],
        runtime_config: dict[str, Any],
        *,
        method: str,
        query_params: dict[str, str],
        headers: dict[str, str],
        body: bytes,
    ) -> ChannelWebhookResult:
        """Default webhook behavior for non-webhook transports."""
        del auth_config, runtime_config, query_params, headers, body
        return ChannelWebhookResult(
            status_code=405,
            body_json={"detail": f"{self.manifest.name} does not use webhooks."},
            content_type="application/json",
        )

    def send_text(
        self,
        auth_config: dict[str, Any],
        runtime_config: dict[str, Any],
        *,
        conversation_id: str,
        user_id: str | None,
        text: str,
    ) -> None:
        """Default outbound text behavior for providers not yet wired for send."""
        del auth_config, runtime_config, conversation_id, user_id, text
        raise NotImplementedError(
            f"{self.manifest.name} outbound send is not implemented yet."
        )

    def send_action(
        self,
        auth_config: dict[str, Any],
        runtime_config: dict[str, Any],
        *,
        context: ChannelMessageContext,
        action: ChannelOutboundAction,
    ) -> None:
        """Deliver a standardized action through the provider's best strategy.

        Why: core orchestration now emits progress/final/system actions instead
        of a single reply string, so each provider needs a single entrypoint that
        can evolve from append-only sends to richer update semantics later.
        """
        if not action.text.strip():
            return
        if context.conversation_id is None:
            raise ValueError(
                f"{self.manifest.name} outbound action is missing a conversation id."
            )
        self.send_text(
            auth_config,
            runtime_config,
            conversation_id=context.conversation_id,
            user_id=context.user_id,
            text=action.text,
        )

    def _delivery_slot_state(
        self,
        *,
        context: ChannelMessageContext,
        slot: str,
    ) -> dict[str, Any]:
        """Return the mutable provider delivery state for one logical slot.

        Why: progress updates and terminal answers in the same assistant turn
        should share a provider-side message reference so channels that support
        editing can update a single visible message instead of spamming chat.
        """
        delivery_slots = context.provider_state.setdefault("delivery_slots", {})
        if not isinstance(delivery_slots, dict):
            delivery_slots = {}
            context.provider_state["delivery_slots"] = delivery_slots

        slot_state = delivery_slots.get(slot)
        if not isinstance(slot_state, dict):
            slot_state = {}
            delivery_slots[slot] = slot_state
        return slot_state


class WorkWeChatProvider(BaseBuiltinProvider):
    """Official Work WeChat long-connection adapter."""

    manifest = ChannelManifest(
        key="work_wechat",
        name="Work WeChat",
        description=(
            "Connect a Work WeChat AI bot through the official websocket long "
            "connection protocol."
        ),
        icon="building2",
        docs_url="https://developer.work.weixin.qq.com/document/path/101463",
        transport_mode="websocket",
        capabilities=["receive_text", "send_text", "event_callback"],
        auth_schema=[
            ChannelConfigField(
                key="bot_id",
                label="Bot ID",
                type="text",
                required=True,
                description="Robot ID from the official Work WeChat AI bot console.",
            ),
            ChannelConfigField(
                key="secret",
                label="Secret",
                type="secret",
                required=True,
                description="Bot secret from the official Work WeChat AI bot console.",
            ),
        ],
        config_schema=[],
        setup_steps=[
            "Create a Work WeChat AI bot that uses the official long-connection mode.",
            "Paste the bot_id and secret into this agent binding.",
            "Save the binding so Pivot can maintain the websocket session automatically.",
            "Link the first user through the generated web login link when they message the bot.",
        ],
    )

    def build_endpoint_infos(self, binding_id: int) -> list[ChannelEndpointInfo]:
        """Return Work WeChat setup details for long-connection mode."""
        del binding_id
        settings = get_settings()
        return [
            ChannelEndpointInfo(
                label="Official WebSocket",
                method="WSS",
                url=settings.WORK_WECHAT_WS_URL,
                description=(
                    "Pivot connects to this official Work WeChat websocket after "
                    "you save bot_id and secret. No callback URL is required."
                ),
            ),
            ChannelEndpointInfo(
                label="Web Linking Base",
                method="GET",
                url=f"{settings.web_public_base_url}/channel-link",
                description=(
                    "External users receive a tokenized link under this base path "
                    "to bind their Work WeChat identity to a Pivot account."
                ),
            ),
        ]

    def test_connection(
        self,
        auth_config: dict[str, Any],
        runtime_config: dict[str, Any],
        binding_id: int,
    ) -> ChannelTestResult:
        """Verify that Work WeChat credentials complete the websocket handshake."""
        del runtime_config
        self.validate_config(auth_config, {})
        try:
            asyncio.run(
                probe_work_wechat_credentials(
                    bot_id=str(auth_config["bot_id"]),
                    secret=str(auth_config["secret"]),
                )
            )
        except Exception as exc:
            return ChannelTestResult(
                ok=False,
                status="error",
                message=f"Work WeChat verification failed: {exc!s}",
                endpoint_infos=self.build_endpoint_infos(binding_id),
            )
        return ChannelTestResult(
            ok=True,
            status="healthy",
            message="Work WeChat credentials verified through the long connection.",
            endpoint_infos=self.build_endpoint_infos(binding_id),
        )


class FeishuProvider(BaseBuiltinProvider):
    """Feishu bot webhook adapter."""

    manifest = ChannelManifest(
        key="feishu",
        name="Feishu",
        description=(
            "Connect a Feishu bot using event subscriptions and message APIs."
        ),
        icon="message-square",
        docs_url=(
            "https://open.feishu.cn/document/server-docs/im-v1/message/events/receive"
        ),
        transport_mode="webhook",
        capabilities=["receive_text", "send_text", "webhook_verification"],
        auth_schema=[
            ChannelConfigField(
                key="app_id",
                label="App ID",
                type="text",
                required=True,
            ),
            ChannelConfigField(
                key="app_secret",
                label="App Secret",
                type="secret",
                required=True,
            ),
            ChannelConfigField(
                key="verification_token",
                label="Verification Token",
                type="secret",
                required=False,
            ),
        ],
        config_schema=[],
        setup_steps=[
            "Create a custom bot or app in Feishu.",
            "Configure the generated webhook URL in event subscriptions.",
            "Enable message receive events and direct message scope.",
        ],
    )

    def _tenant_access_token(self, auth_config: dict[str, Any]) -> str:
        """Exchange Feishu app credentials for a tenant access token."""
        response = requests.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={
                "app_id": auth_config["app_id"],
                "app_secret": auth_config["app_secret"],
            },
            timeout=8,
        )
        payload = response.json()
        token = payload.get("tenant_access_token")
        if not token:
            raise ValueError(payload.get("msg") or "Feishu tenant token missing.")
        return str(token)

    def _send_text_message(
        self,
        *,
        tenant_access_token: str,
        conversation_id: str,
        text: str,
    ) -> str | None:
        """Send a Feishu text message and return its message id when available."""
        response = requests.post(
            "https://open.feishu.cn/open-apis/im/v1/messages",
            params={"receive_id_type": "chat_id"},
            headers={"Authorization": f"Bearer {tenant_access_token}"},
            json={
                "receive_id": conversation_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
            timeout=8,
        )
        payload = response.json()
        if payload.get("code") != 0:
            raise ValueError(payload.get("msg") or "Feishu send failed.")
        data = payload.get("data")
        if not isinstance(data, dict):
            return None
        message_id = data.get("message_id")
        return str(message_id) if message_id is not None else None

    def _edit_text_message(
        self,
        *,
        tenant_access_token: str,
        message_id: str,
        text: str,
    ) -> None:
        """Update one previously sent Feishu text message in place."""
        response = requests.patch(
            f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}",
            headers={"Authorization": f"Bearer {tenant_access_token}"},
            json={
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
            timeout=8,
        )
        payload = response.json()
        if payload.get("code") != 0:
            raise ValueError(payload.get("msg") or "Feishu update failed.")

    def test_connection(
        self,
        auth_config: dict[str, Any],
        runtime_config: dict[str, Any],
        binding_id: int,
    ) -> ChannelTestResult:
        """Verify that Feishu credentials can obtain a tenant token."""
        del runtime_config
        self.validate_config(auth_config, {})
        self._tenant_access_token(auth_config)
        return ChannelTestResult(
            ok=True,
            status="healthy",
            message="Feishu credentials verified successfully.",
            endpoint_infos=self.build_endpoint_infos(binding_id),
        )

    def handle_webhook(
        self,
        auth_config: dict[str, Any],
        runtime_config: dict[str, Any],
        *,
        method: str,
        query_params: dict[str, str],
        headers: dict[str, str],
        body: bytes,
    ) -> ChannelWebhookResult:
        """Handle Feishu URL verification and message events."""
        del runtime_config, method, query_params, headers
        self.validate_config(auth_config, {})
        payload = json.loads(body.decode("utf-8") or "{}")
        if payload.get("type") == "url_verification":
            return ChannelWebhookResult(
                content_type="application/json",
                body_json={"challenge": payload.get("challenge", "")},
            )

        event = payload.get("event", {})
        message = event.get("message", {})
        content_raw = message.get("content", "{}")
        try:
            content = json.loads(content_raw)
        except json.JSONDecodeError:
            content = {}
        text = content.get("text")
        sender = event.get("sender", {}).get("sender_id", {})
        conversation_id = message.get("chat_id")
        user_id = sender.get("open_id") or sender.get("user_id")
        return ChannelWebhookResult(
            content_type="application/json",
            body_json={"code": 0},
            inbound_event=ChannelInboundEvent(
                external_event_id=payload.get("header", {}).get("event_id"),
                external_message_id=message.get("message_id"),
                external_user_id=user_id,
                external_conversation_id=conversation_id,
                message_type=message.get("message_type"),
                text=text,
                raw_payload=payload,
            ),
        )

    def send_text(
        self,
        auth_config: dict[str, Any],
        runtime_config: dict[str, Any],
        *,
        conversation_id: str,
        user_id: str | None,
        text: str,
    ) -> None:
        """Send a plain-text message to a Feishu chat."""
        del runtime_config, user_id
        token = self._tenant_access_token(auth_config)
        self._send_text_message(
            tenant_access_token=token,
            conversation_id=conversation_id,
            text=text,
        )

    def send_action(
        self,
        auth_config: dict[str, Any],
        runtime_config: dict[str, Any],
        *,
        context: ChannelMessageContext,
        action: ChannelOutboundAction,
    ) -> None:
        """Prefer in-place Feishu message updates for streamed progress slots."""
        del runtime_config
        if not action.text.strip():
            return
        if context.conversation_id is None:
            raise ValueError("Feishu outbound action is missing a conversation id.")

        token = self._tenant_access_token(auth_config)
        slot_state = self._delivery_slot_state(context=context, slot=action.slot)
        should_update_in_place = action.delivery_hint in {"stream", "replace"}
        message_id = slot_state.get("message_id")
        if should_update_in_place and isinstance(message_id, str) and message_id:
            try:
                self._edit_text_message(
                    tenant_access_token=token,
                    message_id=message_id,
                    text=action.text,
                )
                return
            except ValueError:
                slot_state.pop("message_id", None)

        created_message_id = self._send_text_message(
            tenant_access_token=token,
            conversation_id=context.conversation_id,
            text=action.text,
        )
        if should_update_in_place and created_message_id:
            slot_state["message_id"] = created_message_id


class TelegramProvider(BaseBuiltinProvider):
    """Telegram bot polling adapter."""

    manifest = ChannelManifest(
        key="telegram",
        name="Telegram",
        description="Connect a Telegram bot through Bot API polling.",
        icon="send",
        docs_url="https://core.telegram.org/bots/api#getupdates",
        transport_mode="polling",
        capabilities=["receive_text", "send_text", "history_pull"],
        auth_schema=[
            ChannelConfigField(
                key="bot_token",
                label="Bot Token",
                type="secret",
                required=True,
            )
        ],
        config_schema=[
            ChannelConfigField(
                key="poll_timeout_seconds",
                label="Poll Timeout Seconds",
                type="number",
                required=False,
                placeholder="30",
                description="Long-poll timeout used for getUpdates.",
            )
        ],
        setup_steps=[
            "Create a Telegram bot with BotFather.",
            "Paste the bot token into Pivot.",
            "Use the manual poll endpoint or a future worker loop to fetch updates.",
        ],
    )

    def _api_base(self, auth_config: dict[str, Any]) -> str:
        """Build the Telegram Bot API base URL for the current token."""
        return f"https://api.telegram.org/bot{auth_config['bot_token']}"

    def _send_message(
        self,
        *,
        auth_config: dict[str, Any],
        chat_id: str,
        text: str,
    ) -> str | None:
        """Send one Telegram message and return its message id when available."""
        response = requests.post(
            f"{self._api_base(auth_config)}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=8,
        )
        payload = response.json()
        if not payload.get("ok"):
            raise ValueError(payload.get("description") or "Telegram send failed.")

        result = payload.get("result")
        if not isinstance(result, dict):
            return None
        message_id = result.get("message_id")
        return str(message_id) if message_id is not None else None

    def _edit_message_text(
        self,
        *,
        auth_config: dict[str, Any],
        chat_id: str,
        message_id: str,
        text: str,
    ) -> None:
        """Edit one Telegram message in place."""
        response = requests.post(
            f"{self._api_base(auth_config)}/editMessageText",
            json={
                "chat_id": chat_id,
                "message_id": int(message_id),
                "text": text,
            },
            timeout=8,
        )
        payload = response.json()
        if payload.get("ok"):
            return
        description = str(payload.get("description") or "Telegram edit failed.")
        if "message is not modified" in description.lower():
            return
        raise ValueError(description)

    def test_connection(
        self,
        auth_config: dict[str, Any],
        runtime_config: dict[str, Any],
        binding_id: int,
    ) -> ChannelTestResult:
        """Verify that the Telegram bot token can call ``getMe``."""
        del runtime_config
        self.validate_config(auth_config, {})
        response = requests.get(f"{self._api_base(auth_config)}/getMe", timeout=8)
        payload = response.json()
        ok = response.ok and bool(payload.get("ok"))
        return ChannelTestResult(
            ok=ok,
            status="healthy" if ok else "error",
            message=(
                "Telegram bot token verified successfully."
                if ok
                else str(payload.get("description") or "Telegram verification failed.")
            ),
            endpoint_infos=self.build_endpoint_infos(binding_id),
        )

    def poll_once(
        self,
        auth_config: dict[str, Any],
        runtime_config: dict[str, Any],
        *,
        offset: int | None,
    ) -> tuple[list[ChannelInboundEvent], int | None]:
        """Fetch one batch of Telegram updates using long polling."""
        self.validate_config(auth_config, runtime_config)
        timeout = int(runtime_config.get("poll_timeout_seconds") or 30)
        response = requests.get(
            f"{self._api_base(auth_config)}/getUpdates",
            params={"timeout": timeout, "offset": offset},
            timeout=timeout + 5,
        )
        payload = response.json()
        if not payload.get("ok"):
            raise ValueError(payload.get("description") or "Telegram poll failed.")

        events: list[ChannelInboundEvent] = []
        next_offset = offset
        for item in payload.get("result", []):
            update_id = item.get("update_id")
            message = item.get("message", {})
            chat = message.get("chat", {})
            from_user = message.get("from", {})
            text = message.get("text")
            if text:
                events.append(
                    ChannelInboundEvent(
                        external_event_id=str(update_id)
                        if update_id is not None
                        else None,
                        external_message_id=(
                            str(message.get("message_id"))
                            if message.get("message_id") is not None
                            else None
                        ),
                        external_user_id=(
                            str(from_user.get("id"))
                            if from_user.get("id") is not None
                            else None
                        ),
                        external_conversation_id=(
                            str(chat.get("id")) if chat.get("id") is not None else None
                        ),
                        message_type="text",
                        text=text,
                        raw_payload=item,
                    )
                )
            if isinstance(update_id, int):
                next_offset = update_id + 1
        return events, next_offset

    def send_text(
        self,
        auth_config: dict[str, Any],
        runtime_config: dict[str, Any],
        *,
        conversation_id: str,
        user_id: str | None,
        text: str,
    ) -> None:
        """Send a plain-text Telegram bot message."""
        del runtime_config, user_id
        self._send_message(
            auth_config=auth_config,
            chat_id=conversation_id,
            text=text,
        )

    def send_action(
        self,
        auth_config: dict[str, Any],
        runtime_config: dict[str, Any],
        *,
        context: ChannelMessageContext,
        action: ChannelOutboundAction,
    ) -> None:
        """Prefer Telegram editMessageText for streamed progress slots."""
        del runtime_config
        if not action.text.strip():
            return
        if context.conversation_id is None:
            raise ValueError("Telegram outbound action is missing a conversation id.")

        slot_state = self._delivery_slot_state(context=context, slot=action.slot)
        should_update_in_place = action.delivery_hint in {"stream", "replace"}
        message_id = slot_state.get("message_id")
        if should_update_in_place and isinstance(message_id, str) and message_id:
            try:
                self._edit_message_text(
                    auth_config=auth_config,
                    chat_id=context.conversation_id,
                    message_id=message_id,
                    text=action.text,
                )
                return
            except ValueError:
                slot_state.pop("message_id", None)

        created_message_id = self._send_message(
            auth_config=auth_config,
            chat_id=context.conversation_id,
            text=action.text,
        )
        if should_update_in_place and created_message_id:
            slot_state["message_id"] = created_message_id


class DingTalkProvider(BaseBuiltinProvider):
    """DingTalk stream mode provider placeholder for V1 setup."""

    manifest = ChannelManifest(
        key="dingtalk",
        name="DingTalk",
        description=(
            "Prepare a DingTalk Stream Mode bot binding. V1 surfaces setup and "
            "credential validation, while stream workers can be added next."
        ),
        icon="radio",
        docs_url=(
            "https://github.com/open-dingtalk/dingtalk-stream-sdk-python"
            "?spm=ding_open_doc.document.0.0.1a5d4a97DMmV9A"
        ),
        transport_mode="websocket",
        capabilities=["receive_text", "send_text"],
        auth_schema=[
            ChannelConfigField(
                key="client_id",
                label="Client ID",
                type="text",
                required=True,
            ),
            ChannelConfigField(
                key="client_secret",
                label="Client Secret",
                type="secret",
                required=True,
            ),
        ],
        config_schema=[],
        setup_steps=[
            "Create a DingTalk app with Stream Mode enabled.",
            "Paste the client id and secret into Pivot.",
            "Run a future stream worker to maintain the websocket connection.",
        ],
    )

    def test_connection(
        self,
        auth_config: dict[str, Any],
        runtime_config: dict[str, Any],
        binding_id: int,
    ) -> ChannelTestResult:
        """Validate DingTalk credentials locally for now."""
        del runtime_config
        self.validate_config(auth_config, {})
        return ChannelTestResult(
            ok=True,
            status="setup_required",
            message=(
                "Credentials saved. DingTalk Stream Mode worker wiring is the next "
                "step after V1 setup."
            ),
            endpoint_infos=self.build_endpoint_infos(binding_id),
        )


BUILTIN_PROVIDERS = {
    "work_wechat": WorkWeChatProvider(),
    "feishu": FeishuProvider(),
    "telegram": TelegramProvider(),
    "dingtalk": DingTalkProvider(),
}
