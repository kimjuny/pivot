"""Tests for the official Work WeChat long-connection helpers."""

from __future__ import annotations

import base64
import sys
import unittest
from importlib import import_module
from pathlib import Path

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

socket_module = import_module("app.channels.work_wechat_socket")


class WorkWeChatSocketTestCase(unittest.TestCase):
    """Validate frame parsing against the official websocket payload shape."""

    def test_parse_text_callback_frame(self) -> None:
        """Text callbacks should produce a neutral text event."""
        event = socket_module.build_work_wechat_inbound_event(
            {
                "cmd": "aibot_msg_callback",
                "headers": {"req_id": "req-1"},
                "body": {
                    "msgid": "msg-1",
                    "aibotid": "bot-1",
                    "chattype": "single",
                    "from": {"userid": "alice"},
                    "msgtype": "text",
                    "text": {"content": "Hello from Work WeChat"},
                },
            }
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.external_event_id, "msg-1")
        self.assertEqual(event.external_user_id, "alice")
        self.assertEqual(event.external_conversation_id, "alice")
        self.assertEqual(event.message_type, "text")
        self.assertEqual(event.text, "Hello from Work WeChat")
        self.assertEqual(event.attachments, [])

    def test_parse_enter_chat_event_frame(self) -> None:
        """Enter-chat events should map to the new official event name."""
        event = socket_module.build_work_wechat_inbound_event(
            {
                "cmd": "aibot_event_callback",
                "headers": {"req_id": "req-2"},
                "body": {
                    "msgid": "event-1",
                    "aibotid": "bot-1",
                    "msgtype": "event",
                    "from": {"userid": "alice"},
                    "event": {"eventtype": "enter_chat"},
                },
            }
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.external_event_id, "event-1")
        self.assertEqual(event.external_user_id, "alice")
        self.assertEqual(event.event_type, "enter_chat")
        self.assertIsNone(event.text)

    def test_parse_image_callback_frame(self) -> None:
        """Image callbacks should expose a decryptable attachment descriptor."""
        event = socket_module.build_work_wechat_inbound_event(
            {
                "cmd": "aibot_msg_callback",
                "headers": {"req_id": "req-3"},
                "body": {
                    "msgid": "msg-image-1",
                    "aibotid": "bot-1",
                    "from": {"userid": "alice"},
                    "msgtype": "image",
                    "image": {
                        "url": "https://example.com/file",
                        "aeskey": "YWJj",
                    },
                },
            }
        )

        self.assertIsNotNone(event)
        self.assertEqual(len(event.attachments), 1)
        self.assertEqual(event.attachments[0]["message_type"], "image")
        self.assertEqual(event.attachments[0]["url"], "https://example.com/file")

    def test_parse_mixed_callback_frame_collects_text_and_images(self) -> None:
        """Mixed callbacks should retain text and image items together."""
        event = socket_module.build_work_wechat_inbound_event(
            {
                "cmd": "aibot_msg_callback",
                "headers": {"req_id": "req-4"},
                "body": {
                    "msgid": "msg-mixed-1",
                    "aibotid": "bot-1",
                    "from": {"userid": "alice"},
                    "msgtype": "mixed",
                    "mixed": {
                        "msg_item": [
                            {"msgtype": "text", "text": {"content": "First line"}},
                            {
                                "msgtype": "image",
                                "image": {
                                    "url": "https://example.com/image",
                                    "aeskey": "YWJj",
                                },
                            },
                            {"msgtype": "text", "text": {"content": "Second line"}},
                        ]
                    },
                },
            }
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.text, "First line\nSecond line")
        self.assertEqual(len(event.attachments), 1)
        self.assertEqual(event.attachments[0]["message_type"], "image")

    def test_decrypt_media_matches_official_algorithm(self) -> None:
        """Media decryption should match the official SDK's AES-CBC behavior."""
        key = b"0123456789abcdef0123456789abcdef"
        iv = key[:16]
        plaintext = b"hello work wechat media"
        padded_plaintext = self._pkcs7_pad_32(plaintext)
        cipher = Cipher(
            algorithms.AES(key),
            modes.CBC(iv),
            backend=default_backend(),
        )
        encryptor = cipher.encryptor()
        encrypted = encryptor.update(padded_plaintext) + encryptor.finalize()

        decrypted = socket_module.decrypt_work_wechat_media(
            encrypted,
            base64.b64encode(key).decode("ascii"),
        )
        self.assertEqual(decrypted, plaintext)

    def test_decrypt_media_accepts_unpadded_base64_key(self) -> None:
        """Provider aeskey values may omit trailing '=' padding."""
        key = b"0123456789abcdef0123456789abcdef"
        plaintext = b"file-bytes"
        encrypted = self._encrypt_media_payload(plaintext, key)
        unpadded_key = base64.b64encode(key).decode("ascii").rstrip("=")

        decrypted = socket_module.decrypt_work_wechat_media(
            encrypted,
            unpadded_key,
        )

        self.assertEqual(decrypted, plaintext)

    @staticmethod
    def _pkcs7_pad_32(value: bytes) -> bytes:
        """Pad bytes to a 32-byte boundary like the official SDK expects."""
        pad_len = 32 - (len(value) % 32)
        if pad_len == 0:
            pad_len = 32
        return value + bytes([pad_len]) * pad_len

    @classmethod
    def _encrypt_media_payload(cls, plaintext: bytes, key: bytes) -> bytes:
        """Encrypt payload bytes using the same mode expected by decrypt tests."""
        iv = key[:16]
        cipher = Cipher(
            algorithms.AES(key),
            modes.CBC(iv),
            backend=default_backend(),
        )
        encryptor = cipher.encryptor()
        return encryptor.update(cls._pkcs7_pad_32(plaintext)) + encryptor.finalize()


if __name__ == "__main__":
    unittest.main()
