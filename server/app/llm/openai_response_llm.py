"""OpenAI Responses API LLM implementation.

This implementation targets the `/responses` endpoint.
"""

import contextlib
import json
import time
import uuid
from collections.abc import Iterator
from typing import Any

import requests
from app.utils.logging_config import get_logger

from .abstract_llm import (
    AbstractLLM,
    ChatMessage,
    Choice,
    FinishReason,
    Response,
    UsageInfo,
)
from .cache_policy import DEFAULT_CACHE_POLICY, validate_cache_policy
from .multimodal import to_openai_response_content
from .thinking_mode import normalize_thinking_mode

logger = get_logger("llm.openai_response")


class OpenAIResponseLLM(AbstractLLM):
    """Implementation for OpenAI Responses API-compatible providers."""

    DEFAULT_TIMEOUT = 120

    def __init__(
        self,
        endpoint: str,
        model: str,
        api_key: str,
        cache_policy: str = DEFAULT_CACHE_POLICY,
        thinking: str = "auto",
        timeout: int | None = None,
        extra_config: dict[str, Any] | None = None,
    ):
        """Initialize the OpenAI Responses API implementation.

        Args:
            endpoint: The base URL for the API (e.g. https://api.openai.com/v1).
            model: The model identifier.
            api_key: API key for authentication.
            timeout: Request timeout in seconds.
            extra_config: Additional API kwargs merged into request payload.
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
        self.cache_policy = validate_cache_policy("openai_response_llm", cache_policy)
        self.thinking = normalize_thinking_mode(thinking)
        self.timeout = timeout or self.DEFAULT_TIMEOUT
        self.extra_config = extra_config or {}

    def _apply_thinking_mode(self, payload_kwargs: dict[str, Any]) -> dict[str, Any]:
        """Apply protocol-level thinking params from LLM entity config."""
        updated_kwargs = dict(payload_kwargs)
        if self.thinking == "auto":
            return updated_kwargs

        if "reasoning" not in updated_kwargs:
            updated_kwargs["reasoning"] = {"enabled": self.thinking == "enabled"}
        return updated_kwargs

    def uses_incremental_request_messages(self) -> bool:
        """Whether this LLM expects incremental input chunks only."""
        return self.cache_policy == "doubao-response-previous-id"

    def _build_input_messages(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Convert chat history to Responses API ``input`` message format."""
        input_messages: list[dict[str, Any]] = []

        for message in messages:
            role = message.get("role", "")
            content = message.get("content", "")

            if role == "system":
                if isinstance(content, str) and content:
                    input_messages.append(
                        {
                            "role": "system",
                            "content": content,
                        }
                    )
                continue

            if role in {"user", "assistant"}:
                converted_content = to_openai_response_content(content, role)
                if isinstance(converted_content, str) and not converted_content:
                    continue
                input_messages.append(
                    {
                        "role": role,
                        "content": (
                            [{"type": "input_text", "text": converted_content}]
                            if isinstance(converted_content, str)
                            else converted_content
                        ),
                    }
                )

        return input_messages

    def _extract_text_and_tools(
        self, raw_dict: dict[str, Any]
    ) -> tuple[str, list[dict[str, Any]] | None]:
        """Extract assistant text and function calls from Responses payload."""
        output_text = raw_dict.get("output_text")
        text = output_text if isinstance(output_text, str) else ""
        tool_calls: list[dict[str, Any]] = []

        output_items = raw_dict.get("output", [])
        if not isinstance(output_items, list):
            return text, None

        for item in output_items:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type == "function_call":
                arguments = item.get("arguments", "")
                if isinstance(arguments, dict):
                    arguments = json.dumps(arguments, ensure_ascii=False)
                if not isinstance(arguments, str):
                    arguments = ""
                tool_calls.append(
                    {
                        "id": item.get("call_id", item.get("id", "")),
                        "type": "function",
                        "function": {
                            "name": item.get("name", ""),
                            "arguments": arguments,
                        },
                    }
                )
            elif item_type == "message" and not text:
                content_list = item.get("content", [])
                if isinstance(content_list, list):
                    text_parts: list[str] = []
                    for content_item in content_list:
                        if not isinstance(content_item, dict):
                            continue
                        content_text = content_item.get("text")
                        if isinstance(content_text, str):
                            text_parts.append(content_text)
                    text = "".join(text_parts)

        return text, tool_calls or None

    @staticmethod
    def _merge_extra_body_kwargs(merged_kwargs: dict[str, Any]) -> dict[str, Any]:
        """Flatten SDK-style ``extra_body`` into raw Responses API payload."""
        normalized_kwargs = dict(merged_kwargs)
        extra_body = normalized_kwargs.pop("extra_body", None)
        if isinstance(extra_body, dict):
            for key, value in extra_body.items():
                normalized_kwargs.setdefault(key, value)
        return normalized_kwargs

    @staticmethod
    def _http_error_detail(response: requests.Response | None) -> str:
        """Build a concise diagnostic string for failed HTTP responses."""
        if response is None:
            return "<no response>"

        text = ""
        with contextlib.suppress(Exception):
            text = (response.text or "").strip()
        if not text:
            text = "<empty response body>"

        request_id = (
            response.headers.get("x-request-id")
            or response.headers.get("x-tt-logid")
            or response.headers.get("x-amzn-requestid")
            or ""
        )
        if request_id:
            return f"{text} (request_id={request_id})"
        return text

    @staticmethod
    def _extract_stream_response_id(event: dict[str, Any]) -> str | None:
        """Extract provider response ID from a streaming event payload."""
        response_id = event.get("response_id")
        if isinstance(response_id, str) and response_id:
            return response_id

        response_obj = event.get("response")
        if isinstance(response_obj, dict):
            nested_id = response_obj.get("id")
            if isinstance(nested_id, str) and nested_id:
                return nested_id

        event_id = event.get("id")
        if isinstance(event_id, str) and event_id.startswith("resp_"):
            return event_id
        return None

    def _parse_dict_response(self, raw_dict: dict[str, Any], model: str) -> Response:
        """Parse raw Responses API JSON dict into structured Response object."""
        response_id = raw_dict.get("id", str(uuid.uuid4()))
        created = int(time.time())
        response_model = raw_dict.get("model", model)
        text, tool_calls = self._extract_text_and_tools(raw_dict)

        finish_reason = None
        status = raw_dict.get("status")
        if status == "completed":
            finish_reason = FinishReason.STOP
        elif status == "incomplete":
            finish_reason = FinishReason.LENGTH

        message = ChatMessage(
            role="assistant",
            content=text,
            tool_calls=tool_calls,
        )
        choice = Choice(index=0, message=message, finish_reason=finish_reason)

        usage = None
        raw_usage = raw_dict.get("usage")
        if isinstance(raw_usage, dict):
            prompt_tokens = raw_usage.get("input_tokens", 0)
            completion_tokens = raw_usage.get("output_tokens", 0)
            total_tokens = raw_usage.get("total_tokens", 0)
            usage = UsageInfo(
                prompt_tokens=prompt_tokens if isinstance(prompt_tokens, int) else 0,
                completion_tokens=(
                    completion_tokens if isinstance(completion_tokens, int) else 0
                ),
                total_tokens=total_tokens if isinstance(total_tokens, int) else 0,
                cached_input_tokens=self._extract_cached_input_tokens(raw_usage),
            )

        return Response(
            id=response_id,
            choices=[choice],
            created=created,
            model=response_model,
            usage=usage,
        )

    def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> Response:
        """Process a conversation with the Responses API."""
        try:
            pivot_task_id = kwargs.pop("_pivot_task_id", "")
            previous_response_id = kwargs.pop("_pivot_previous_response_id", "")
            merged_kwargs = {**self.extra_config, **kwargs}
            normalized_kwargs = self._merge_extra_body_kwargs(merged_kwargs)
            normalized_kwargs = self._apply_thinking_mode(normalized_kwargs)
            input_messages = self._build_input_messages(messages)
            url = f"{self.endpoint.rstrip('/')}/responses"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": self.model,
                "input": input_messages,
                **normalized_kwargs,
            }
            if (
                self.cache_policy == "openai-response-prompt-cache-key"
                and isinstance(pivot_task_id, str)
                and pivot_task_id
            ):
                payload["prompt_cache_key"] = pivot_task_id
            elif self.cache_policy == "doubao-response-previous-id":
                payload["caching"] = {"type": "enabled"}
                if isinstance(previous_response_id, str) and previous_response_id:
                    payload["previous_response_id"] = previous_response_id

            response = requests.post(
                url, headers=headers, json=payload, timeout=self.timeout
            )
            response.raise_for_status()
            return self._parse_dict_response(response.json(), self.model)
        except requests.exceptions.HTTPError as e:
            response = getattr(e, "response", None)
            text = self._http_error_detail(response)
            logger.error(
                "Responses API request failed endpoint=%s model=%s status=%s detail=%s",
                self.endpoint,
                self.model,
                response.status_code if response is not None else "unknown",
                text,
            )
            raise RuntimeError(
                "OpenAI response API request failed for "
                f"{self.endpoint}: HTTP "
                f"{response.status_code if response is not None else 'Unknown'} - {text}"
            ) from e
        except Exception as e:
            raise RuntimeError(
                f"OpenAI response API request failed for {self.endpoint}: {e!s}"
            ) from e

    def chat_stream(
        self, messages: list[dict[str, Any]], **kwargs: Any
    ) -> Iterator[Response]:
        """Process a conversation with the Responses API in streaming mode."""
        try:
            pivot_task_id = kwargs.pop("_pivot_task_id", "")
            previous_response_id = kwargs.pop("_pivot_previous_response_id", "")
            merged_kwargs = {**self.extra_config, **kwargs}
            normalized_kwargs = self._merge_extra_body_kwargs(merged_kwargs)
            normalized_kwargs = self._apply_thinking_mode(normalized_kwargs)
            input_messages = self._build_input_messages(messages)
            url = f"{self.endpoint.rstrip('/')}/responses"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": self.model,
                "input": input_messages,
                "stream": True,
                **normalized_kwargs,
            }
            if (
                self.cache_policy == "openai-response-prompt-cache-key"
                and isinstance(pivot_task_id, str)
                and pivot_task_id
            ):
                payload["prompt_cache_key"] = pivot_task_id
            elif self.cache_policy == "doubao-response-previous-id":
                payload["caching"] = {"type": "enabled"}
                if isinstance(previous_response_id, str) and previous_response_id:
                    payload["previous_response_id"] = previous_response_id

            with requests.post(
                url, headers=headers, json=payload, timeout=self.timeout, stream=True
            ) as response:
                response.raise_for_status()
                stream_response_id: str | None = None
                for line in response.iter_lines():
                    if not line:
                        continue
                    decoded = line.decode("utf-8").strip()
                    if not decoded.startswith("data: "):
                        continue
                    data_str = decoded[len("data: ") :].strip()
                    if data_str == "[DONE]":
                        break

                    with contextlib.suppress(json.JSONDecodeError):
                        event = json.loads(data_str)
                        event_type = event.get("type", "")
                        extracted_response_id = self._extract_stream_response_id(event)
                        if extracted_response_id:
                            stream_response_id = extracted_response_id
                        if event_type == "response.output_text.delta":
                            delta = event.get("delta", "")
                            if isinstance(delta, str) and delta:
                                yield Response(
                                    id=stream_response_id or "",
                                    choices=[
                                        Choice(
                                            index=0,
                                            message=ChatMessage(
                                                role="assistant",
                                                content=delta,
                                            ),
                                        )
                                    ],
                                    created=int(time.time()),
                                    model=self.model,
                                )
                        elif event_type in {
                            "response.reasoning_summary_text.delta",
                            "response.reasoning_text.delta",
                        }:
                            reasoning_delta = event.get("delta", "")
                            if isinstance(reasoning_delta, str) and reasoning_delta:
                                yield Response(
                                    id=stream_response_id or "",
                                    choices=[
                                        Choice(
                                            index=0,
                                            message=ChatMessage(
                                                role="assistant",
                                                content="",
                                                reasoning_content=reasoning_delta,
                                            ),
                                        )
                                    ],
                                    created=int(time.time()),
                                    model=self.model,
                                )
                        elif event_type == "response.completed":
                            usage = None
                            response_payload = event.get("response")
                            if isinstance(response_payload, dict):
                                raw_usage = response_payload.get("usage")
                                if isinstance(raw_usage, dict):
                                    prompt_tokens = raw_usage.get("input_tokens", 0)
                                    completion_tokens = raw_usage.get(
                                        "output_tokens", 0
                                    )
                                    total_tokens = raw_usage.get("total_tokens", 0)
                                    usage = UsageInfo(
                                        prompt_tokens=(
                                            prompt_tokens
                                            if isinstance(prompt_tokens, int)
                                            else 0
                                        ),
                                        completion_tokens=(
                                            completion_tokens
                                            if isinstance(completion_tokens, int)
                                            else 0
                                        ),
                                        total_tokens=(
                                            total_tokens
                                            if isinstance(total_tokens, int)
                                            else 0
                                        ),
                                        cached_input_tokens=self._extract_cached_input_tokens(
                                            raw_usage
                                        ),
                                    )

                            # Delta text has already been emitted via streaming events.
                            # Emit usage-only terminal chunk so upper layers can persist
                            # provider-reported token counts and cache chaining ID.
                            yield Response(
                                id=stream_response_id or "",
                                choices=[
                                    Choice(
                                        index=0,
                                        message=ChatMessage(
                                            role="assistant",
                                            content="",
                                        ),
                                    )
                                ],
                                created=int(time.time()),
                                model=self.model,
                                usage=usage,
                            )
        except requests.exceptions.HTTPError as e:
            response = getattr(e, "response", None)
            text = self._http_error_detail(response)
            logger.error(
                "Responses API streaming request failed endpoint=%s model=%s status=%s detail=%s",
                self.endpoint,
                self.model,
                response.status_code if response is not None else "unknown",
                text,
            )
            raise RuntimeError(
                "OpenAI response streaming failed for "
                f"{self.endpoint}: HTTP "
                f"{response.status_code if response is not None else 'Unknown'} - {text}"
            ) from e
        except Exception as e:
            raise RuntimeError(
                f"OpenAI response streaming failed for {self.endpoint}: {e!s}"
            ) from e
