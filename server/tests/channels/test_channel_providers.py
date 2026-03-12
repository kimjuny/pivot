"""Tests for provider-specific channel delivery behavior."""

import sys
import unittest
from importlib import import_module
from pathlib import Path
from unittest.mock import Mock, patch

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

providers_module = import_module("app.channels.providers")
ChannelMessageContext = import_module("app.channels.types").ChannelMessageContext
ChannelOutboundAction = import_module("app.channels.types").ChannelOutboundAction


class ProviderDeliveryTestCase(unittest.TestCase):
    """Validate in-place progress updates for built-in providers."""

    def test_feishu_progress_and_answer_share_one_message(self) -> None:
        """Feishu should send once, then patch the same message for the final answer."""
        provider = providers_module.FeishuProvider()
        context = ChannelMessageContext(
            conversation_id="chat-1",
            user_id="user-1",
        )

        def post_side_effect(*args: object, **kwargs: object) -> Mock:
            url = str(args[0])
            response = Mock()
            if url.endswith("/tenant_access_token/internal"):
                response.json.return_value = {"tenant_access_token": "tenant-token"}
            elif url.endswith("/im/v1/messages"):
                response.json.return_value = {
                    "code": 0,
                    "data": {"message_id": "om_xxx"},
                }
            else:
                self.fail(f"Unexpected POST url: {url}")
            return response

        with (
            patch.object(
                providers_module.requests, "post", side_effect=post_side_effect
            ) as post_mock,
            patch.object(providers_module.requests, "patch") as patch_mock,
        ):
            patch_mock.return_value.json.return_value = {"code": 0}

            provider.send_action(
                {"app_id": "cli_xxx", "app_secret": "sec"},
                {},
                context=context,
                action=ChannelOutboundAction(
                    kind="progress",
                    text="Thinking...",
                    delivery_hint="stream",
                    slot="assistant_turn",
                ),
            )
            provider.send_action(
                {"app_id": "cli_xxx", "app_secret": "sec"},
                {},
                context=context,
                action=ChannelOutboundAction(
                    kind="answer",
                    text="Done.",
                    delivery_hint="stream",
                    slot="assistant_turn",
                    is_terminal=True,
                ),
            )

        self.assertEqual(post_mock.call_count, 3)
        self.assertEqual(patch_mock.call_count, 1)
        patch_call = patch_mock.call_args
        self.assertIsNotNone(patch_call)
        self.assertIn("/im/v1/messages/om_xxx", str(patch_call.args[0]))
        slot_state = context.provider_state["delivery_slots"]["assistant_turn"]
        self.assertEqual(slot_state["message_id"], "om_xxx")

    def test_telegram_progress_and_answer_share_one_message(self) -> None:
        """Telegram should send once, then edit the same bot message."""
        provider = providers_module.TelegramProvider()
        context = ChannelMessageContext(
            conversation_id="12345",
            user_id="67890",
        )

        def post_side_effect(*args: object, **kwargs: object) -> Mock:
            url = str(args[0])
            response = Mock()
            if url.endswith("/sendMessage"):
                response.json.return_value = {
                    "ok": True,
                    "result": {"message_id": 88},
                }
            elif url.endswith("/editMessageText"):
                response.json.return_value = {"ok": True, "result": True}
            else:
                self.fail(f"Unexpected POST url: {url}")
            return response

        with patch.object(
            providers_module.requests,
            "post",
            side_effect=post_side_effect,
        ) as post_mock:
            provider.send_action(
                {"bot_token": "token"},
                {},
                context=context,
                action=ChannelOutboundAction(
                    kind="progress",
                    text="Thinking...",
                    delivery_hint="stream",
                    slot="assistant_turn",
                ),
            )
            provider.send_action(
                {"bot_token": "token"},
                {},
                context=context,
                action=ChannelOutboundAction(
                    kind="answer",
                    text="Done.",
                    delivery_hint="stream",
                    slot="assistant_turn",
                    is_terminal=True,
                ),
            )

        self.assertEqual(post_mock.call_count, 2)
        first_call = post_mock.call_args_list[0]
        second_call = post_mock.call_args_list[1]
        self.assertIn("/sendMessage", str(first_call.args[0]))
        self.assertIn("/editMessageText", str(second_call.args[0]))
        slot_state = context.provider_state["delivery_slots"]["assistant_turn"]
        self.assertEqual(slot_state["message_id"], "88")


if __name__ == "__main__":
    unittest.main()
