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
from .message_converter import to_openai_response_messages
from .openrouter_attribution import build_openrouter_attribution_headers
from .thinking_policy import DEFAULT_THINKING_POLICY, validate_thinking_policy

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
        thinking_policy: str = DEFAULT_THINKING_POLICY,
        thinking_effort: str | None = None,
        thinking_budget_tokens: int | None = None,
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
        (
            self.thinking_policy,
            self.thinking_effort,
            self.thinking_budget_tokens,
        ) = validate_thinking_policy(
            "openai_response_llm",
            thinking_policy,
            thinking_effort,
            thinking_budget_tokens,
        )
        self.timeout = timeout or self.DEFAULT_TIMEOUT
        self.extra_config = extra_config or {}

    def uses_incremental_request_messages(self) -> bool:
        """Whether this LLM expects incremental input chunks only."""
        return self.cache_policy == "doubao-response-previous-id"

    @staticmethod
    def _convert_tools_to_response_format(
        openai_tools: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]] | None:
        """Convert Chat Completions tools to Responses API flat format.

        Chat Completions uses a nested ``function`` wrapper:
            {"type": "function", "function": {"name": ..., "parameters": ...}}

        Responses API expects a flat structure:
            {"type": "function", "name": ..., "parameters": ...}
        """
        if not openai_tools:
            return None

        response_tools: list[dict[str, Any]] = []
        for tool in openai_tools:
            if tool.get("type") == "function":
                func = tool.get("function", {})
                response_tool: dict[str, Any] = {
                    "type": "function",
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                    "parameters": func.get("parameters", {}),
                }
                # Forward any extra keys already in flat format (e.g. strict).
                for key in ("strict",):
                    if key in tool:
                        response_tool[key] = tool[key]
                response_tools.append(response_tool)
            else:
                # Pass through non-function tools as-is (custom, namespace, etc.).
                response_tools.append(tool)

        return response_tools or None

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
    def _extract_reasoning_text(raw_dict: dict[str, Any]) -> str | None:
        """Extract reasoning text from non-stream Responses payloads."""
        parts: list[str] = []

        def collect_text(value: Any) -> None:
            if isinstance(value, str) and value:
                parts.append(value)

        def collect_from_content_items(items: Any) -> None:
            if not isinstance(items, list):
                return
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_type = item.get("type")
                if item_type in {
                    "reasoning_text",
                    "reasoning_summary_text",
                    "summary_text",
                } or (isinstance(item_type, str) and "reasoning" in item_type):
                    collect_text(item.get("text"))

        raw_reasoning = raw_dict.get("reasoning")
        if isinstance(raw_reasoning, dict):
            collect_text(raw_reasoning.get("text"))
            collect_from_content_items(raw_reasoning.get("content"))
            summary = raw_reasoning.get("summary")
            if isinstance(summary, list):
                for item in summary:
                    if isinstance(item, dict):
                        collect_text(item.get("text"))

        output_items = raw_dict.get("output", [])
        if isinstance(output_items, list):
            for item in output_items:
                if not isinstance(item, dict):
                    continue
                item_type = item.get("type")
                if item_type == "reasoning":
                    collect_text(item.get("text"))
                    collect_from_content_items(item.get("content"))
                    summary = item.get("summary")
                    if isinstance(summary, list):
                        for summary_item in summary:
                            if isinstance(summary_item, dict):
                                collect_text(summary_item.get("text"))
                elif item_type == "message":
                    collect_from_content_items(item.get("content"))

        if not parts:
            return None
        return "".join(parts)

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

        request_id = ""
        for header_name in (
            "x-request-id",
            "request-id",
            "x-tt-logid",
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
                "msg",
                "error_msg",
                "error_code",
                "code",
                "type",
                "request_id",
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
            reasoning_content=self._extract_reasoning_text(raw_dict),
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

    def _build_headers(self) -> dict[str, str]:
        """Build HTTP headers for Responses API requests."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **build_openrouter_attribution_headers(self.endpoint),
        }

    def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> Response:
        """Process a conversation with the Responses API."""
        try:
            pivot_task_id = kwargs.pop("_pivot_task_id", "")
            previous_response_id = kwargs.pop("_pivot_previous_response_id", "")
            merged_kwargs = {**self.extra_config, **kwargs}
            normalized_kwargs = self._merge_extra_body_kwargs(merged_kwargs)
            tools = normalized_kwargs.pop("tools", None)
            response_tools = self._convert_tools_to_response_format(tools)
            input_messages = to_openai_response_messages(messages)
            url = f"{self.endpoint.rstrip('/')}/responses"
            headers = self._build_headers()
            payload: dict[str, Any] = {
                "model": self.model,
                "input": input_messages,
                **normalized_kwargs,
            }
            if response_tools and not previous_response_id:
                payload["tools"] = response_tools
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
            tools = normalized_kwargs.pop("tools", None)
            response_tools = self._convert_tools_to_response_format(tools)
            input_messages = to_openai_response_messages(messages)
            url = f"{self.endpoint.rstrip('/')}/responses"
            headers = self._build_headers()
            payload: dict[str, Any] = {
                "model": self.model,
                "input": input_messages,
                "stream": True,
                **normalized_kwargs,
            }
            if response_tools and not previous_response_id:
                payload["tools"] = response_tools
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
                if not response.ok:
                    detail = self._http_error_detail(response)
                    raise RuntimeError(
                        "OpenAI response streaming failed for "
                        f"{self.endpoint}: HTTP {response.status_code} - {detail}"
                    )
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
                        elif event_type == "response.output_item.added":
                            # New function_call item: emit tool_call with name + call_id.
                            item = event.get("item", {})
                            output_index = event.get("output_index")
                            if (
                                isinstance(item, dict)
                                and item.get("type") == "function_call"
                            ):
                                yield Response(
                                    id=stream_response_id or "",
                                    choices=[
                                        Choice(
                                            index=0,
                                            message=ChatMessage(
                                                role="assistant",
                                                content="",
                                                tool_calls=[
                                                    {
                                                        "index": output_index
                                                        if isinstance(output_index, int)
                                                        else None,
                                                        "id": item.get("call_id", ""),
                                                        "type": "function",
                                                        "function": {
                                                            "name": item.get(
                                                                "name", ""
                                                            ),
                                                            "arguments": "",
                                                        },
                                                    }
                                                ],
                                            ),
                                        )
                                    ],
                                    created=int(time.time()),
                                    model=self.model,
                                )
                        elif event_type == "response.function_call_arguments.delta":
                            # Incremental arguments fragment for a function_call.
                            delta_args = event.get("delta", "")
                            output_index = event.get("output_index")
                            if isinstance(delta_args, str) and delta_args:
                                yield Response(
                                    id=stream_response_id or "",
                                    choices=[
                                        Choice(
                                            index=0,
                                            message=ChatMessage(
                                                role="assistant",
                                                content="",
                                                tool_calls=[
                                                    {
                                                        "index": output_index
                                                        if isinstance(output_index, int)
                                                        else None,
                                                        "id": "",
                                                        "type": "function",
                                                        "function": {
                                                            "name": "",
                                                            "arguments": delta_args,
                                                        },
                                                    }
                                                ],
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
