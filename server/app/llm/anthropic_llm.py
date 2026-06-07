"""Anthropic-compatible LLM implementation.

This implementation works with Anthropic's Messages API (Claude models)
using raw HTTP requests instead of the Anthropic SDK.
"""

import contextlib
import json
import logging
import time
import uuid
from collections.abc import Iterator
from typing import Any

import requests

from .abstract_llm import (
    AbstractLLM,
    ChatMessage,
    Choice,
    FinishReason,
    Response,
    UsageInfo,
)
from .cache_policy import DEFAULT_CACHE_POLICY, validate_cache_policy
from .message_converter import to_anthropic_messages
from .openrouter_attribution import build_openrouter_attribution_headers
from .thinking_policy import DEFAULT_THINKING_POLICY, validate_thinking_policy

logger = logging.getLogger(__name__)


class AnthropicLLM(AbstractLLM):
    """Generic implementation for Anthropic Messages API.

    This implementation works with Anthropic's Claude models and any
    compatible APIs that follow the same protocol, using raw HTTP requests.
    """

    DEFAULT_TIMEOUT = 60  # Request timeout in seconds
    DEFAULT_MAX_TOKENS = 16384  # Default max tokens for response

    def __init__(
        self,
        endpoint: str,
        model: str,
        api_key: str,
        cache_policy: str = DEFAULT_CACHE_POLICY,
        thinking_policy: str = DEFAULT_THINKING_POLICY,
        thinking_effort: str | None = None,
        thinking_budget_tokens: int | None = None,
        timeout: int | None = None,
        extra_config: dict[str, Any] | None = None,
    ):
        """Initialize the Anthropic-compatible LLM implementation.

        Args:
            endpoint: The base URL for the API (e.g., "https://api.anthropic.com")
            model: The model identifier to use (e.g., "claude-3-5-sonnet-20241022")
            api_key: API key for authentication
            cache_policy: Cache policy for prompt caching.
            thinking_policy: Thinking/reasoning policy for extended thinking.
            thinking_effort: Thinking effort level (e.g. "low", "medium", "high").
            thinking_budget_tokens: Token budget for thinking.
            timeout: Request timeout in seconds. Defaults to 60 seconds.
            extra_config: Additional kwargs to pass to API calls.

        Raises:
            ValueError: If any required parameter is missing
        """
        if not endpoint:
            raise ValueError("Endpoint is required")
        if not model:
            raise ValueError("Model is required")
        if not api_key:
            raise ValueError("API key is required")

        self.endpoint = endpoint
        self.model = model
        self.api_key = api_key
        self.cache_policy = validate_cache_policy("anthropic_compatible", cache_policy)
        (
            self.thinking_policy,
            self.thinking_effort,
            self.thinking_budget_tokens,
        ) = validate_thinking_policy(
            "anthropic_compatible",
            thinking_policy,
            thinking_effort,
            thinking_budget_tokens,
        )
        self.timeout = timeout or self.DEFAULT_TIMEOUT
        self.extra_config = extra_config or {}

    def _convert_tools_to_anthropic(
        self, openai_tools: list[dict[str, Any]] | None
    ) -> list[dict[str, Any]] | None:
        """Convert OpenAI-format tools to Anthropic format.

        Args:
            openai_tools: Tools in OpenAI format

        Returns:
            Tools in Anthropic format, or None if no tools provided
        """
        if not openai_tools:
            return None

        anthropic_tools = []
        for tool in openai_tools:
            if tool.get("type") == "function":
                func = tool.get("function", {})
                anthropic_tool = {
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                    "input_schema": func.get("parameters", {}),
                }
                anthropic_tools.append(anthropic_tool)

        return anthropic_tools if anthropic_tools else None

    def _apply_block_cache_to_messages(
        self, formatted_messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Apply ephemeral cache control to the last message content block."""
        if not formatted_messages:
            return formatted_messages

        cached_messages = [dict(message) for message in formatted_messages]
        last_message = dict(cached_messages[-1])
        last_content = last_message.get("content", "")

        if isinstance(last_content, str):
            last_message["content"] = [
                {
                    "type": "text",
                    "text": last_content,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        elif isinstance(last_content, list) and last_content:
            content_blocks = [dict(block) for block in last_content]
            if isinstance(content_blocks[-1], dict):
                content_blocks[-1]["cache_control"] = {"type": "ephemeral"}
            last_message["content"] = content_blocks

        cached_messages[-1] = last_message
        return cached_messages

    def _apply_block_cache_to_prompt(
        self,
        system_message: str,
        formatted_messages: list[dict[str, Any]],
    ) -> tuple[str | list[dict[str, Any]], list[dict[str, Any]]]:
        """Mark the last cacheable block in prompt order.

        Why: MiniMax Anthropic block cache uses one explicit breakpoint to cache
        the longest matching prefix. In our cumulative ReAct history, the latest
        message becomes part of the stable prefix for the next recursion, so the
        breakpoint should live on the prompt tail, not be pinned to ``system``.
        """
        if formatted_messages:
            return system_message, self._apply_block_cache_to_messages(
                formatted_messages
            )

        if system_message:
            return (
                [
                    {
                        "type": "text",
                        "text": system_message,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                formatted_messages,
            )

        return system_message, formatted_messages

    @staticmethod
    def _http_error_detail(response: requests.Response | None) -> str:
        """Build a concise provider-facing diagnostic string for failed responses."""
        if response is None:
            return "<no response>"

        request_id = ""
        for header_name in (
            "x-request-id",
            "request-id",
            "x-amzn-requestid",
            "trace-id",
        ):
            header_value = response.headers.get(header_name)
            if isinstance(header_value, str) and header_value.strip():
                request_id = header_value.strip()
                break

        content_type = response.headers.get("content-type", "").strip()

        parsed_body: Any = None
        with contextlib.suppress(Exception):
            parsed_body = response.json()

        detail = ""
        if isinstance(parsed_body, dict):
            summary_keys = (
                "error",
                "message",
                "type",
            )
            summary = {
                key: parsed_body[key]
                for key in summary_keys
                if key in parsed_body and parsed_body[key] not in (None, "")
            }
            detail = json.dumps(
                summary or parsed_body,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        else:
            with contextlib.suppress(Exception):
                detail = (response.text or "").strip()

        if not detail:
            detail = "<empty response body>"
        if len(detail) > 1200:
            detail = f"{detail[:1200]}...(truncated)"

        suffix_parts: list[str] = []
        if content_type:
            suffix_parts.append(f"content_type={content_type}")
        if request_id:
            suffix_parts.append(f"request_id={request_id}")
        if suffix_parts:
            return f"{detail} ({', '.join(suffix_parts)})"
        return detail

    def _build_headers(self) -> dict[str, str]:
        """Build HTTP headers for Anthropic API requests."""
        return {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
            **build_openrouter_attribution_headers(self.endpoint),
        }

    def _build_api_url(self) -> str:
        """Build the full API URL for the Messages endpoint."""
        return f"{self.endpoint.rstrip('/')}/v1/messages"

    def _build_api_params(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Build the full API request payload.

        Args:
            messages: Raw message list from caller.
            **kwargs: Additional API parameters.

        Returns:
            Complete JSON payload dict for the Anthropic Messages API.
        """
        kwargs.pop("_pivot_task_id", None)
        kwargs.pop("_pivot_previous_response_id", None)

        system_message, formatted_messages = to_anthropic_messages(messages)
        merged_kwargs = {**self.extra_config, **kwargs}

        tools = merged_kwargs.pop("tools", None)
        anthropic_tools = self._convert_tools_to_anthropic(tools)

        if "max_tokens" not in merged_kwargs:
            merged_kwargs["max_tokens"] = self.DEFAULT_MAX_TOKENS

        api_params: dict[str, Any] = {
            "model": self.model,
            "messages": formatted_messages,
            **merged_kwargs,
        }

        if system_message:
            api_params["system"] = system_message

        if anthropic_tools:
            api_params["tools"] = anthropic_tools

        if self.cache_policy == "anthropic-auto-cache":
            api_params["cache_control"] = {"type": "ephemeral"}
        elif self.cache_policy == "anthropic-block-cache":
            cached_system, cached_messages = self._apply_block_cache_to_prompt(
                system_message,
                formatted_messages,
            )
            if cached_system:
                api_params["system"] = cached_system
            api_params["messages"] = cached_messages

        return api_params

    def _parse_response(self, raw_dict: dict[str, Any]) -> Response:
        """Parse a non-streaming Anthropic Messages API response dict.

        Args:
            raw_dict: Parsed JSON response from the Anthropic API.

        Returns:
            Structured Response in our standard format.
        """
        response_id = raw_dict.get("id", str(uuid.uuid4()))
        response_model = raw_dict.get("model", self.model)

        content_blocks = raw_dict.get("content", [])
        content_text = ""
        reasoning_text = ""
        tool_calls: list[dict[str, Any]] = []

        for block in content_blocks:
            block_type = block.get("type", "")

            if block_type == "text":
                content_text += block.get("text", "")
            elif block_type == "thinking":
                thinking = block.get("thinking", "")
                if not isinstance(thinking, str) or not thinking:
                    thinking = block.get("text", "")
                if isinstance(thinking, str):
                    reasoning_text += thinking
            elif block_type == "tool_use":
                tool_calls.append(
                    {
                        "id": block.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": block.get("name", ""),
                            "arguments": json.dumps(
                                block.get("input", {}), ensure_ascii=False
                            ),
                        },
                    }
                )

        finish_reason = None
        raw_stop_reason = raw_dict.get("stop_reason")
        if raw_stop_reason:
            stop_reason_map = {
                "end_turn": FinishReason.STOP,
                "max_tokens": FinishReason.LENGTH,
                "tool_use": FinishReason.TOOL_CALLS,
            }
            finish_reason = stop_reason_map.get(raw_stop_reason)
            if finish_reason is None:
                with contextlib.suppress(ValueError):
                    finish_reason = FinishReason(raw_stop_reason)

        message = ChatMessage(
            role="assistant",
            content=content_text if content_text else None,
            reasoning_content=reasoning_text if reasoning_text else None,
            tool_calls=tool_calls if tool_calls else None,
        )

        choice = Choice(index=0, message=message, finish_reason=finish_reason)

        usage = None
        raw_usage = raw_dict.get("usage")
        if isinstance(raw_usage, dict):
            cache_creation = raw_usage.get("cache_creation_input_tokens", 0) or 0
            cache_read = raw_usage.get("cache_read_input_tokens", 0) or 0
            input_tokens = (
                raw_usage.get("input_tokens", 0) + cache_creation + cache_read
            )
            completion_tokens = raw_usage.get("output_tokens", 0)
            usage = UsageInfo(
                prompt_tokens=input_tokens,
                completion_tokens=completion_tokens,
                total_tokens=input_tokens + completion_tokens,
                cached_input_tokens=cache_read,
            )

        return Response(
            id=response_id,
            choices=[choice],
            created=int(time.time()),
            model=response_model,
            usage=usage,
        )

    def _parse_stream_event(self, event_data: dict[str, Any]) -> Response | None:
        """Parse a single Anthropic SSE event into a Response, or None if ignorable.

        Args:
            event_data: Parsed JSON dict of one SSE event.

        Returns:
            Response with text/reasoning/tool content, usage-only Response,
            or None for events that don't carry user-visible content.
        """
        event_type = event_data.get("type", "")

        if event_type == "message_start":
            return None

        if event_type == "message_delta":
            # message_delta carries stop_reason and sometimes usage.
            return None

        if event_type == "content_block_start":
            # Emit tool_call with name + id when a tool_use block starts.
            content_block = event_data.get("content_block", {})
            if (
                isinstance(content_block, dict)
                and content_block.get("type") == "tool_use"
            ):
                block_index = event_data.get("index")
                message = ChatMessage(
                    role="assistant",
                    content="",
                    tool_calls=[
                        {
                            "index": block_index
                            if isinstance(block_index, int)
                            else None,
                            "id": content_block.get("id", ""),
                            "type": "function",
                            "function": {
                                "name": content_block.get("name", ""),
                                "arguments": "",
                            },
                        }
                    ],
                )
                choice = Choice(index=0, message=message)
                return Response(
                    id=str(uuid.uuid4()),
                    choices=[choice],
                    created=int(time.time()),
                    model=self.model,
                )
            return None

        if event_type == "content_block_stop":
            return None

        if event_type == "content_block_delta":
            delta = event_data.get("delta", {})
            delta_type = delta.get("type", "")

            if delta_type == "text_delta":
                text = delta.get("text", "")
                message = ChatMessage(role="assistant", content=text)
                choice = Choice(index=0, message=message)
                return Response(
                    id=str(uuid.uuid4()),
                    choices=[choice],
                    created=int(time.time()),
                    model=self.model,
                )

            if delta_type == "thinking_delta":
                thinking = delta.get("thinking", "")
                if isinstance(thinking, str) and thinking:
                    message = ChatMessage(
                        role="assistant",
                        content="",
                        reasoning_content=thinking,
                    )
                    choice = Choice(index=0, message=message)
                    return Response(
                        id=str(uuid.uuid4()),
                        choices=[choice],
                        created=int(time.time()),
                        model=self.model,
                    )

            if delta_type == "input_json_delta":
                # Yield incremental tool input JSON fragment.
                partial_json = delta.get("partial_json", "")
                if isinstance(partial_json, str) and partial_json:
                    block_index = event_data.get("index")
                    message = ChatMessage(
                        role="assistant",
                        content="",
                        tool_calls=[
                            {
                                "index": block_index
                                if isinstance(block_index, int)
                                else None,
                                "id": "",
                                "type": "function",
                                "function": {
                                    "name": "",
                                    "arguments": partial_json,
                                },
                            }
                        ],
                    )
                    choice = Choice(index=0, message=message)
                    return Response(
                        id=str(uuid.uuid4()),
                        choices=[choice],
                        created=int(time.time()),
                        model=self.model,
                    )
                return None

            return None

        return None

    def _extract_stream_usage(self, event_data: dict[str, Any]) -> UsageInfo | None:
        """Extract usage tokens from Anthropic streaming events.

        Anthropic emits usage in ``message_start`` (with initial input tokens)
        and ``message_delta`` (with final output tokens). We extract whichever
        is present.
        """
        event_type = event_data.get("type", "")

        raw_usage: dict[str, Any] | None = None
        if event_type == "message_start":
            message_obj = event_data.get("message", {})
            raw_usage = (
                message_obj.get("usage") if isinstance(message_obj, dict) else None
            )
        elif event_type == "message_delta":
            raw_usage = event_data.get("usage")
        else:
            return None

        if not isinstance(raw_usage, dict):
            return None

        input_tokens = raw_usage.get("input_tokens", 0)
        if not isinstance(input_tokens, int):
            input_tokens = 0
        completion_tokens = raw_usage.get("output_tokens", 0)
        if not isinstance(completion_tokens, int):
            completion_tokens = 0

        cache_creation = raw_usage.get("cache_creation_input_tokens", 0) or 0
        cache_read = raw_usage.get("cache_read_input_tokens", 0) or 0
        prompt_tokens = max(input_tokens, 0) + cache_creation + cache_read

        return UsageInfo(
            prompt_tokens=prompt_tokens,
            completion_tokens=max(completion_tokens, 0),
            total_tokens=prompt_tokens + max(completion_tokens, 0),
            cached_input_tokens=cache_read,
        )

    def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> Response:
        """Process a conversation with the LLM.

        Args:
            messages: List of message dictionaries with 'role' and 'content'
            **kwargs: Additional arguments for the chat completion
                     (e.g., temperature, max_tokens, tools, etc.)

        Returns:
            Response: The structured response from the LLM

        Raises:
            RuntimeError: If the API request fails
        """
        try:
            url = self._build_api_url()
            headers = self._build_headers()
            payload = self._build_api_params(messages, **kwargs)

            response = requests.post(
                url, headers=headers, json=payload, timeout=self.timeout
            )
            response.raise_for_status()

            return self._parse_response(response.json())

        except requests.exceptions.HTTPError as e:
            resp = getattr(e, "response", None)
            text = self._http_error_detail(resp)
            logger.error(
                "Anthropic request failed endpoint=%s model=%s status=%s detail=%s",
                self.endpoint,
                self.model,
                resp.status_code if resp is not None else "unknown",
                text,
            )
            raise RuntimeError(
                "Anthropic API request failed for "
                f"{self.endpoint}: HTTP "
                f"{resp.status_code if resp is not None else 'Unknown'} - {text}"
            ) from e
        except Exception as e:
            raise RuntimeError(
                f"Anthropic API request failed for {self.endpoint}: {e!s}"
            ) from e

    def chat_stream(
        self, messages: list[dict[str, Any]], **kwargs: Any
    ) -> Iterator[Response]:
        """Process a conversation with the LLM in streaming mode.

        Args:
            messages: List of message dictionaries with 'role' and 'content'
            **kwargs: Additional arguments for the chat completion
                     (e.g., temperature, max_tokens, tools, etc.)

        Yields:
            Response: A chunk of the structured response from the LLM

        Raises:
            RuntimeError: If the API request fails
        """
        try:
            url = self._build_api_url()
            headers = self._build_headers()
            payload = self._build_api_params(messages, **kwargs)
            payload["stream"] = True

            with requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=self.timeout,
                stream=True,
            ) as resp:
                if not resp.ok:
                    text = self._http_error_detail(resp)
                    raise RuntimeError(
                        "Anthropic streaming failed for "
                        f"{self.endpoint}: HTTP {resp.status_code} - {text}"
                    )

                stream_response_id = ""

                for line in resp.iter_lines():
                    if not line:
                        continue
                    line = line.decode("utf-8")
                    if not line.startswith("data:"):
                        continue

                    data_str = line[len("data:") :].strip()
                    if not data_str:
                        continue

                    try:
                        event_data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    # Track message ID from message_start.
                    if event_data.get("type") == "message_start":
                        msg_obj = event_data.get("message", {})
                        msg_id = (
                            msg_obj.get("id", "") if isinstance(msg_obj, dict) else ""
                        )
                        if isinstance(msg_id, str) and msg_id:
                            stream_response_id = msg_id

                    usage = self._extract_stream_usage(event_data)
                    if usage is not None:
                        # message_delta carries the final stop_reason alongside usage.
                        finish_reason = None
                        if event_data.get("type") == "message_delta":
                            delta = event_data.get("delta")
                            if isinstance(delta, dict):
                                raw_stop = delta.get("stop_reason")
                                if raw_stop == "end_turn":
                                    finish_reason = FinishReason.STOP
                                elif raw_stop == "max_tokens":
                                    finish_reason = FinishReason.LENGTH
                                elif raw_stop == "tool_use":
                                    finish_reason = FinishReason.TOOL_CALLS
                        if finish_reason is not None:
                            yield Response(
                                id=stream_response_id or str(uuid.uuid4()),
                                choices=[
                                    Choice(
                                        index=0,
                                        message=ChatMessage(
                                            role="assistant", content=""
                                        ),
                                        finish_reason=finish_reason,
                                    )
                                ],
                                created=int(time.time()),
                                model=self.model,
                                usage=usage,
                            )
                        else:
                            yield Response(
                                id=stream_response_id or str(uuid.uuid4()),
                                choices=[],
                                created=int(time.time()),
                                model=self.model,
                                usage=usage,
                            )

                    parsed = self._parse_stream_event(event_data)
                    if parsed is not None:
                        if stream_response_id:
                            parsed.id = stream_response_id
                        yield parsed

        except requests.exceptions.HTTPError as e:
            resp = getattr(e, "response", None)
            text = self._http_error_detail(resp)
            logger.error(
                "Anthropic streaming failed endpoint=%s model=%s status=%s detail=%s",
                self.endpoint,
                self.model,
                resp.status_code if resp is not None else "unknown",
                text,
            )
            raise RuntimeError(
                "Anthropic streaming failed for "
                f"{self.endpoint}: HTTP "
                f"{resp.status_code if resp is not None else 'Unknown'} - {text}"
            ) from e
        except Exception as e:
            raise RuntimeError(
                f"Anthropic streaming failed for {self.endpoint}: {e!s}"
            ) from e
