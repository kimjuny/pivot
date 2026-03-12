"""Official Work WeChat long-connection protocol helpers."""

from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import re
import uuid
from typing import Any
from urllib.parse import unquote

import requests
import websockets
from app.channels.types import ChannelInboundEvent
from app.config import get_settings
from app.utils.logging_config import get_logger
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from websockets.exceptions import ConnectionClosed

logger = get_logger("channel.work_wechat")

WORK_WECHAT_CALLBACK_COMMAND = "aibot_msg_callback"
WORK_WECHAT_EVENT_COMMAND = "aibot_event_callback"
WORK_WECHAT_HEARTBEAT_COMMAND = "ping"
WORK_WECHAT_RESPONSE_COMMAND = "aibot_respond_msg"
WORK_WECHAT_SEND_COMMAND = "aibot_send_msg"
WORK_WECHAT_SUBSCRIBE_COMMAND = "aibot_subscribe"
WORK_WECHAT_UPDATE_COMMAND = "aibot_respond_update_msg"
WORK_WECHAT_WELCOME_COMMAND = "aibot_respond_welcome_msg"


def generate_work_wechat_req_id(prefix: str) -> str:
    """Create a request identifier compatible with the official SDK.

    Args:
        prefix: Command prefix such as ``aibot_subscribe`` or ``ping``.

    Returns:
        A unique request id with the provided prefix.
    """
    return f"{prefix}-{uuid.uuid4().hex}"


def build_work_wechat_auth_frame(bot_id: str, secret: str) -> dict[str, Any]:
    """Build the official subscription frame used to authenticate a socket.

    Args:
        bot_id: Work WeChat bot identifier.
        secret: Work WeChat bot secret.

    Returns:
        A JSON-serializable websocket frame.
    """
    return {
        "cmd": WORK_WECHAT_SUBSCRIBE_COMMAND,
        "headers": {
            "req_id": generate_work_wechat_req_id(WORK_WECHAT_SUBSCRIBE_COMMAND)
        },
        "body": {
            "bot_id": bot_id,
            "secret": secret,
        },
    }


def build_work_wechat_stream_reply(
    text: str,
    *,
    stream_id: str | None = None,
    finish: bool = False,
) -> dict[str, Any]:
    """Build a stream reply body for normal message callbacks.

    Args:
        text: Markdown-compatible reply content.
        stream_id: Stable stream identifier reused across progressive updates.
        finish: Whether this chunk completes the stream.

    Returns:
        The websocket body expected by ``aibot_respond_msg``.
    """
    return {
        "msgtype": "stream",
        "stream": {
            "id": stream_id or generate_work_wechat_req_id("stream"),
            "finish": finish,
            "content": text,
        },
    }


def build_work_wechat_welcome_reply(text: str) -> dict[str, Any]:
    """Build a welcome reply body for ``enter_chat`` events.

    Args:
        text: Welcome text content.

    Returns:
        The websocket body expected by ``aibot_respond_welcome_msg``.
    """
    return {
        "msgtype": "text",
        "text": {
            "content": text,
        },
    }


def build_work_wechat_markdown_send(
    conversation_id: str,
    text: str,
) -> dict[str, Any]:
    """Build a proactive markdown send body for a conversation.

    Args:
        conversation_id: User id for single chat, or chat id for group chat.
        text: Markdown-compatible reply content.

    Returns:
        The websocket body expected by ``aibot_send_msg``.
    """
    return {
        "chatid": conversation_id,
        "msgtype": "markdown",
        "markdown": {
            "content": text,
        },
    }


def build_work_wechat_inbound_event(
    frame: dict[str, Any],
) -> ChannelInboundEvent | None:
    """Translate a Work WeChat websocket frame into Pivot's neutral event model.

    Args:
        frame: Parsed websocket frame from the Work WeChat stream.

    Returns:
        A neutral inbound event, or ``None`` if the frame does not contain a
        routable message/event body.
    """
    command = str(frame.get("cmd") or "")
    body = frame.get("body")
    if not isinstance(body, dict):
        return None

    headers = frame.get("headers")
    header_req_id = None
    if isinstance(headers, dict):
        req_id = headers.get("req_id")
        header_req_id = str(req_id) if req_id is not None else None

    sender = body.get("from")
    external_user_id = None
    if isinstance(sender, dict):
        user_id = sender.get("userid")
        if user_id is not None:
            external_user_id = str(user_id)

    chat_id = body.get("chatid")
    external_conversation_id = str(chat_id) if chat_id is not None else external_user_id

    raw_message_type = body.get("msgtype")
    message_type = str(raw_message_type) if raw_message_type is not None else None

    text: str | None = None
    attachments: list[dict[str, Any]] = []
    if message_type == "text":
        text_body = body.get("text")
        if isinstance(text_body, dict):
            content = text_body.get("content")
            text = str(content) if content is not None else None
    elif message_type == "image":
        image_body = body.get("image")
        if isinstance(image_body, dict):
            attachment = _extract_media_attachment(
                payload=image_body,
                message_type="image",
            )
            if attachment is not None:
                attachments.append(attachment)
    elif message_type == "file":
        file_body = body.get("file")
        if isinstance(file_body, dict):
            attachment = _extract_media_attachment(
                payload=file_body,
                message_type="file",
            )
            if attachment is not None:
                attachments.append(attachment)
    elif message_type == "voice":
        voice_body = body.get("voice")
        if isinstance(voice_body, dict):
            content = voice_body.get("content")
            text = str(content) if content is not None else None
    elif message_type == "mixed":
        mixed_body = body.get("mixed")
        if isinstance(mixed_body, dict):
            parts: list[str] = []
            for item in mixed_body.get("msg_item", []):
                if not isinstance(item, dict):
                    continue
                item_type = str(item.get("msgtype") or "")
                if item_type == "text":
                    text_item = item.get("text")
                    if not isinstance(text_item, dict):
                        continue
                    content = text_item.get("content")
                    if content is not None:
                        parts.append(str(content))
                elif item_type == "image":
                    image_item = item.get("image")
                    if isinstance(image_item, dict):
                        attachment = _extract_media_attachment(
                            payload=image_item,
                            message_type="image",
                        )
                        if attachment is not None:
                            attachments.append(attachment)
            if parts:
                text = "\n".join(parts)

    event_type = None
    if command == WORK_WECHAT_EVENT_COMMAND:
        event_body = body.get("event")
        if isinstance(event_body, dict):
            raw_event_type = event_body.get("eventtype")
            if raw_event_type is not None:
                event_type = str(raw_event_type)

    message_id = body.get("msgid")
    return ChannelInboundEvent(
        external_event_id=str(message_id) if message_id is not None else header_req_id,
        external_message_id=str(message_id) if message_id is not None else None,
        external_user_id=external_user_id,
        external_conversation_id=external_conversation_id,
        message_type=message_type,
        event_type=event_type,
        text=text,
        attachments=attachments,
        raw_payload=frame,
    )


def _extract_media_attachment(
    *,
    payload: dict[str, Any],
    message_type: str,
) -> dict[str, Any] | None:
    """Extract one decryptable media attachment descriptor from a payload.

    Args:
        payload: Provider-specific ``image`` or ``file`` payload.
        message_type: Provider message type such as ``image`` or ``file``.

    Returns:
        A normalized attachment descriptor, or ``None`` if required fields are
        missing.
    """
    url = payload.get("url")
    aes_key = payload.get("aeskey")
    if url is None or aes_key is None:
        return None
    return {
        "provider": "work_wechat",
        "message_type": message_type,
        "url": str(url),
        "aes_key": str(aes_key),
    }


def download_work_wechat_media(
    url: str,
    timeout_seconds: int | None = None,
) -> tuple[bytes, str | None, str | None]:
    """Download encrypted media bytes and best-effort filename metadata.

    Args:
        url: Work WeChat temporary download URL.
        timeout_seconds: Optional HTTP timeout.

    Returns:
        Tuple of encrypted bytes, filename, and content type.

    Raises:
        ValueError: If the download fails.
    """
    timeout = timeout_seconds or get_settings().WORK_WECHAT_WS_REQUEST_TIMEOUT_SECONDS
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    content_type = response.headers.get("Content-Type")
    content_disposition = response.headers.get("Content-Disposition")
    return response.content, _parse_filename(content_disposition), content_type


def decrypt_work_wechat_media(encrypted_bytes: bytes, aes_key: str) -> bytes:
    """Decrypt Work WeChat media using the official SDK-compatible algorithm.

    Args:
        encrypted_bytes: Downloaded encrypted media bytes.
        aes_key: Base64-encoded media AES key from the websocket message.

    Returns:
        Decrypted binary content.

    Raises:
        ValueError: If the key or padding is invalid.
    """
    if not encrypted_bytes:
        raise ValueError("Encrypted media payload is empty.")
    if not aes_key.strip():
        raise ValueError("Work WeChat media aes_key is empty.")

    key = _decode_work_wechat_aes_key(aes_key)

    iv = key[:16]
    cipher = Cipher(
        algorithms.AES(key),
        modes.CBC(iv),
        backend=default_backend(),
    )
    decryptor = cipher.decryptor()
    decrypted = decryptor.update(encrypted_bytes) + decryptor.finalize()
    return _strip_pkcs7_padding(decrypted)


def _decode_work_wechat_aes_key(aes_key: str) -> bytes:
    """Decode a Work WeChat media AES key, tolerating omitted base64 padding.

    Args:
        aes_key: Base64-encoded media key from the provider payload.

    Returns:
        Decoded 32-byte AES key.

    Raises:
        ValueError: If the key is not valid base64 or not 32 bytes after decode.
    """
    normalized_key = "".join(aes_key.strip().split())
    padding = "=" * (-len(normalized_key) % 4)
    try:
        decoded_key = base64.b64decode(f"{normalized_key}{padding}")
    except Exception as exc:  # pragma: no cover - invalid provider payload
        raise ValueError("Work WeChat media aes_key is not valid base64.") from exc

    if len(decoded_key) != 32:
        raise ValueError(
            "Work WeChat media aes_key must decode to 32 bytes for AES-256."
        )
    return decoded_key


def infer_work_wechat_filename(
    *,
    message_type: str,
    header_filename: str | None,
    content_type: str | None,
) -> str:
    """Infer a stable filename for a downloaded Work WeChat media payload.

    Args:
        message_type: Work WeChat message type such as ``image`` or ``file``.
        header_filename: Filename parsed from ``Content-Disposition`` when present.
        content_type: HTTP ``Content-Type`` header when present.

    Returns:
        A filename suitable for ``FileService.store_uploaded_file``.
    """
    if header_filename:
        return header_filename

    extension = None
    if content_type:
        normalized_content_type = content_type.split(";", 1)[0].strip().lower()
        extension = mimetypes.guess_extension(normalized_content_type)

    if not extension:
        extension = ".png" if message_type == "image" else ".bin"
    return f"work-wechat-{message_type}{extension}"


def _parse_filename(content_disposition: str | None) -> str | None:
    """Parse a download filename from ``Content-Disposition`` headers."""
    if not content_disposition:
        return None
    utf8_match = re.search(r"filename\*=UTF-8''([^;\s]+)", content_disposition, re.I)
    if utf8_match:
        return unquote(utf8_match.group(1))

    plain_match = re.search(r'filename="?([^";]+)"?', content_disposition, re.I)
    if plain_match:
        return unquote(plain_match.group(1))
    return None


def _strip_pkcs7_padding(decrypted: bytes) -> bytes:
    """Remove the 32-byte-block PKCS#7 padding used by the official SDK."""
    if not decrypted:
        raise ValueError("Decrypted Work WeChat media is empty.")
    pad_len = decrypted[-1]
    if pad_len < 1 or pad_len > 32 or pad_len > len(decrypted):
        raise ValueError(f"Invalid Work WeChat media padding value: {pad_len}")
    if any(byte != pad_len for byte in decrypted[-pad_len:]):
        raise ValueError("Invalid Work WeChat media padding bytes.")
    return decrypted[:-pad_len]


class WorkWeChatSocketConnection:
    """Async websocket client for the official Work WeChat bot protocol.

    The class mirrors the behavior documented in the official SDK:
    authenticate with ``aibot_subscribe``, keep the connection alive with
    ``ping``, and route callback frames separately from ACK frames.
    """

    def __init__(
        self,
        *,
        bot_id: str,
        secret: str,
        ws_url: str | None = None,
        request_timeout_seconds: int | None = None,
    ) -> None:
        """Initialize one socket client.

        Args:
            bot_id: Work WeChat bot identifier.
            secret: Work WeChat bot secret.
            ws_url: Optional override for the websocket URL.
            request_timeout_seconds: Timeout used for auth and command ACKs.
        """
        settings = get_settings()
        self.bot_id = bot_id
        self.secret = secret
        self.ws_url = ws_url or settings.WORK_WECHAT_WS_URL
        self.request_timeout_seconds = (
            request_timeout_seconds or settings.WORK_WECHAT_WS_REQUEST_TIMEOUT_SECONDS
        )
        self.websocket: Any | None = None
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._inbound_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._reader_task: asyncio.Task[None] | None = None
        self._closed_future: asyncio.Future[str] | None = None

    async def connect(self) -> None:
        """Open the websocket and complete the official subscribe handshake.

        Raises:
            ValueError: If the subscribe ACK reports an error.
            TimeoutError: If the subscribe ACK does not arrive in time.
        """
        self.websocket = await websockets.connect(
            self.ws_url,
            open_timeout=self.request_timeout_seconds,
            close_timeout=self.request_timeout_seconds,
            ping_interval=None,
            ping_timeout=None,
        )
        self._closed_future = asyncio.get_running_loop().create_future()
        self._reader_task = asyncio.create_task(self._read_loop())
        auth_frame = build_work_wechat_auth_frame(self.bot_id, self.secret)
        await self.send_command(
            auth_frame["cmd"],
            auth_frame["body"],
            req_id=str(auth_frame["headers"]["req_id"]),
        )

    async def close(self) -> None:
        """Close the websocket and reject any pending ACK waiters."""
        reader_task = self._reader_task
        self._reader_task = None
        websocket = self.websocket
        self.websocket = None

        if websocket is not None:
            await websocket.close()
        if reader_task is not None:
            await asyncio.gather(reader_task, return_exceptions=True)

        for req_id, future in list(self._pending.items()):
            if future.done():
                continue
            future.set_exception(ConnectionError("Work WeChat websocket closed."))
            self._pending.pop(req_id, None)

    async def send_command(
        self,
        command: str,
        body: dict[str, Any] | None = None,
        *,
        req_id: str | None = None,
    ) -> dict[str, Any]:
        """Send a command frame and wait for its ACK.

        Args:
            command: Work WeChat websocket command.
            body: Optional command body.
            req_id: Optional request id to preserve a callback's req_id.

        Returns:
            The ACK frame returned by Work WeChat.

        Raises:
            ConnectionError: If the socket is not connected.
            TimeoutError: If the ACK does not arrive in time.
            ValueError: If the ACK reports an error.
        """
        websocket = self.websocket
        if websocket is None:
            raise ConnectionError("Work WeChat websocket is not connected.")

        loop = asyncio.get_running_loop()
        request_id = req_id or generate_work_wechat_req_id(command)
        ack_future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[request_id] = ack_future

        frame: dict[str, Any] = {
            "cmd": command,
            "headers": {"req_id": request_id},
        }
        if body is not None:
            frame["body"] = body

        await websocket.send(json.dumps(frame, ensure_ascii=False))
        try:
            ack_frame = await asyncio.wait_for(
                ack_future,
                timeout=self.request_timeout_seconds,
            )
        finally:
            self._pending.pop(request_id, None)

        if int(ack_frame.get("errcode") or 0) != 0:
            raise ValueError(
                str(ack_frame.get("errmsg") or f"Work WeChat command {command} failed.")
            )
        return ack_frame

    async def next_inbound_frame(self) -> dict[str, Any]:
        """Wait for the next callback/event frame from the websocket.

        Returns:
            The next inbound callback frame.

        Raises:
            ConnectionError: If the reader loop stops before a frame arrives.
        """
        if self._closed_future is None:
            raise ConnectionError("Work WeChat websocket is not connected.")

        queue_task = asyncio.create_task(self._inbound_queue.get())
        try:
            done, _ = await asyncio.wait(
                {queue_task, self._closed_future},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if queue_task in done:
                return queue_task.result()

            queue_task.cancel()
            await asyncio.gather(queue_task, return_exceptions=True)
            close_reason = await self._closed_future
            raise ConnectionError(close_reason)
        except asyncio.CancelledError:
            queue_task.cancel()
            await asyncio.gather(queue_task, return_exceptions=True)
            raise

    async def send_heartbeat(self) -> None:
        """Send the official application-layer heartbeat frame."""
        await self.send_command(WORK_WECHAT_HEARTBEAT_COMMAND)

    async def _read_loop(self) -> None:
        """Dispatch incoming frames to pending ACKs or the inbound queue."""
        close_reason = "Work WeChat websocket closed."
        try:
            websocket = self.websocket
            if websocket is None:
                return

            async for raw_message in websocket:
                message_text = (
                    raw_message.decode("utf-8")
                    if isinstance(raw_message, bytes)
                    else str(raw_message)
                )
                try:
                    frame = json.loads(message_text)
                except json.JSONDecodeError:
                    logger.warning(
                        "Discarded invalid Work WeChat websocket payload: %s",
                        message_text[:200],
                    )
                    continue

                headers = frame.get("headers")
                req_id = ""
                if isinstance(headers, dict):
                    raw_req_id = headers.get("req_id")
                    req_id = str(raw_req_id) if raw_req_id is not None else ""

                command = str(frame.get("cmd") or "")
                pending_ack = self._pending.get(req_id)
                if pending_ack is not None and command not in {
                    WORK_WECHAT_CALLBACK_COMMAND,
                    WORK_WECHAT_EVENT_COMMAND,
                }:
                    if not pending_ack.done():
                        pending_ack.set_result(frame)
                    continue

                if command in {
                    WORK_WECHAT_CALLBACK_COMMAND,
                    WORK_WECHAT_EVENT_COMMAND,
                }:
                    await self._inbound_queue.put(frame)
                    continue

                logger.debug(
                    "Received unclassified Work WeChat frame: %s",
                    json.dumps(frame, ensure_ascii=False)[:500],
                )
        except ConnectionClosed as exc:
            close_reason = (
                exc.reason or f"Work WeChat websocket closed with code {exc.code}."
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            close_reason = f"Work WeChat reader failed: {exc!s}"
            logger.exception("Work WeChat websocket reader crashed.")
        finally:
            for req_id, future in list(self._pending.items()):
                if future.done():
                    continue
                future.set_exception(ConnectionError(close_reason))
                self._pending.pop(req_id, None)

            if self._closed_future is not None and not self._closed_future.done():
                self._closed_future.set_result(close_reason)


async def probe_work_wechat_credentials(
    bot_id: str,
    secret: str,
) -> None:
    """Verify Work WeChat credentials by completing the websocket handshake.

    Args:
        bot_id: Work WeChat bot identifier.
        secret: Work WeChat bot secret.

    Raises:
        ValueError: If authentication fails.
        TimeoutError: If the handshake times out.
    """
    client = WorkWeChatSocketConnection(bot_id=bot_id, secret=secret)
    try:
        await client.connect()
    finally:
        await client.close()
