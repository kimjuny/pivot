"""OpenAI Chat Completions API LLM implementation.

This implementation targets `/chat/completions` compatible providers.
"""

import contextlib
import json
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
from .multimodal import to_openai_completion_content
from .thinking_mode import normalize_thinking_mode


class OpenAICompletionLLM(AbstractLLM):
    """Implementation for OpenAI Chat Completions-compatible APIs.

    This implementation works with any provider that follows the OpenAI Chat
    Completions API specification, including:
    - OpenAI (GPT-3.5, GPT-4, etc.)
    - Azure OpenAI
    - GLM (ZhipuAI)
    - DeepSeek
    - Any other OpenAI-compatible endpoints

    The endpoint, model, and API key are provided dynamically rather than
    hardcoded, allowing this single implementation to work with any provider.
    """

    DEFAULT_TIMEOUT = 120  # Request timeout in seconds
    MAX_RETRIES = 3  # Maximum number of retry attempts
    QWEN_MAX_CACHE_MARKERS = 4

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
        """Initialize the OpenAI Chat Completions implementation.

        Args:
            endpoint: The base URL for the API (e.g., "https://api.openai.com/v1")
            model: The model identifier to use (e.g., "gpt-4", "glm-4")
            api_key: API key for authentication
            timeout: Request timeout in seconds. Defaults to 60 seconds.
            extra_config: Additional kwargs to pass to API calls.
                         Example: {"extra_body": {"reasoning_split": True}}

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
        self.cache_policy = validate_cache_policy(
            "openai_completion_llm",
            cache_policy,
        )
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

    @staticmethod
    def _normalize_qwen_cacheable_content(
        content: str | list[dict[str, Any]],
    ) -> str | list[dict[str, Any]]:
        """Normalize message content into a stable block format for Qwen caching.

        Why: explicit cache reuse compares prompt prefixes across requests. When a
        text message is sometimes sent as a raw string and sometimes as a block list
        with ``cache_control``, providers may treat those requests as different
        prompt shapes. We therefore keep Chat Completions payloads structurally
        stable whenever Qwen block cache is enabled.
        """
        if isinstance(content, str):
            return [{"type": "text", "text": content}]
        if isinstance(content, list):
            return [dict(block) for block in content if isinstance(block, dict)]
        return content

    @staticmethod
    def _with_ephemeral_cache_control(
        content: str | list[dict[str, Any]],
    ) -> str | list[dict[str, Any]]:
        """Return content with an ephemeral cache marker on the last block."""
        if not isinstance(content, list) or not content:
            return content

        content_blocks = [dict(block) for block in content]
        content_blocks[-1]["cache_control"] = {"type": "ephemeral"}
        return content_blocks

    def _messages_with_qwen_cache_markers(
        self, messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Return messages with stable content blocks and rolling Qwen markers.

        Qwen explicit cache supports up to four cache markers per request. We mark
        the most recent cacheable messages so each recursion can reuse the newest
        stable prefix from the prior recursion while also creating fresh prefixes
        for the next one.
        """
        if not messages:
            return []

        cached_messages: list[dict[str, Any]] = []
        eligible_indexes: list[int] = []
        for message in messages:
            normalized_message = dict(message)
            normalized_content = self._normalize_qwen_cacheable_content(
                message.get("content", "")
            )
            normalized_message["content"] = normalized_content
            cached_messages.append(normalized_message)

            if isinstance(normalized_content, list) and normalized_content:
                eligible_indexes.append(len(cached_messages) - 1)

        for index in eligible_indexes[-self.QWEN_MAX_CACHE_MARKERS :]:
            cached_messages[index]["content"] = self._with_ephemeral_cache_control(
                cached_messages[index]["content"]
            )

        return cached_messages

    @staticmethod
    def _with_stream_usage_enabled(
        payload_kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        """Ensure streaming payloads request usage so cache hits surface in the UI."""
        updated_kwargs = dict(payload_kwargs)
        raw_stream_options = updated_kwargs.get("stream_options")
        stream_options = (
            dict(raw_stream_options) if isinstance(raw_stream_options, dict) else {}
        )
        stream_options["include_usage"] = True
        updated_kwargs["stream_options"] = stream_options
        return updated_kwargs

    def _parse_dict_response(self, raw_dict: dict[str, Any], model: str) -> Response:
        """Parse raw JSON dict into structured Response object."""
        response_id = raw_dict.get("id", str(uuid.uuid4()))
        created = raw_dict.get("created", int(time.time()))
        response_model = raw_dict.get("model", model)

        choices = []
        for i, raw_choice in enumerate(raw_dict.get("choices", [])):
            message_data = raw_choice.get("message") or raw_choice.get("delta") or {}

            role = message_data.get("role", "assistant")
            content = message_data.get("content", "") or ""
            reasoning_content = message_data.get("reasoning_content", None)
            if not isinstance(reasoning_content, str) or not reasoning_content:
                reasoning_content = self._extract_reasoning_details_text(message_data)

            tool_calls = None
            raw_tool_calls = message_data.get("tool_calls", None)
            if raw_tool_calls:
                tool_calls = []
                for tc in raw_tool_calls:
                    func_data = tc.get("function", {})
                    tool_call_dict = {
                        "id": tc.get("id", ""),
                        "type": tc.get("type", "function"),
                        "function": {
                            "name": func_data.get("name", ""),
                            "arguments": func_data.get("arguments", ""),
                        },
                    }
                    tool_calls.append(tool_call_dict)

            tool_call_id = message_data.get("tool_call_id", None)

            message = ChatMessage(
                role=role,
                content=content,
                reasoning_content=reasoning_content,
                tool_calls=tool_calls,
                tool_call_id=tool_call_id,
            )

            finish_reason = None
            raw_fr = raw_choice.get("finish_reason", None)
            if raw_fr:
                with contextlib.suppress(ValueError):
                    finish_reason = FinishReason(raw_fr)

            choice = Choice(index=i, message=message, finish_reason=finish_reason)
            choices.append(choice)

        usage = None
        raw_usage = raw_dict.get("usage")
        if raw_usage:
            usage = UsageInfo(
                prompt_tokens=raw_usage.get("prompt_tokens", 0),
                completion_tokens=raw_usage.get("completion_tokens", 0),
                total_tokens=raw_usage.get("total_tokens", 0),
                cached_input_tokens=self._extract_cached_input_tokens(raw_usage),
            )

        return Response(
            id=response_id,
            choices=choices,
            created=created,
            model=response_model,
            usage=usage,
        )

    @staticmethod
    def _extract_reasoning_details_text(message_data: dict[str, Any]) -> str | None:
        """Extract reasoning text from MiniMax-style ``reasoning_details`` blocks."""
        raw_details = message_data.get("reasoning_details")
        if not isinstance(raw_details, list):
            return None

        parts: list[str] = []
        for detail in raw_details:
            if not isinstance(detail, dict):
                continue
            detail_text = detail.get("text")
            if isinstance(detail_text, str) and detail_text:
                parts.append(detail_text)
        if not parts:
            return None
        return "".join(parts)

    @staticmethod
    def _merge_extra_body_kwargs(merged_kwargs: dict[str, Any]) -> dict[str, Any]:
        """Normalize OpenAI SDK-style ``extra_body`` into raw HTTP payload keys.

        Why: this implementation sends raw HTTP JSON. ``extra_body`` is an SDK-level
        argument (used by OpenAI SDK) and should be flattened when present.
        """
        normalized_kwargs = dict(merged_kwargs)
        extra_body = normalized_kwargs.pop("extra_body", None)
        if isinstance(extra_body, dict):
            # Preserve explicit top-level kwargs if both are provided.
            for key, value in extra_body.items():
                normalized_kwargs.setdefault(key, value)
        return normalized_kwargs

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
            pivot_task_id = kwargs.pop("_pivot_task_id", "")
            # Merge extra_config with kwargs (kwargs takes precedence)
            merged_kwargs = {**self.extra_config, **kwargs}
            normalized_kwargs = self._merge_extra_body_kwargs(merged_kwargs)
            normalized_kwargs = self._apply_thinking_mode(normalized_kwargs)

            url = f"{self.endpoint.rstrip('/')}/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            request_messages: list[dict[str, Any]] = [
                {
                    **message,
                    "content": to_openai_completion_content(message.get("content", "")),
                }
                for message in messages
            ]
            if self.cache_policy == "qwen-completion-block-cache":
                request_messages = self._messages_with_qwen_cache_markers(
                    request_messages
                )

            payload: dict[str, Any] = {
                "model": self.model,
                "messages": request_messages,
                **normalized_kwargs,
            }
            if (
                self.cache_policy == "kimi-completion-prompt-cache-key"
                and isinstance(pivot_task_id, str)
                and pivot_task_id
            ):
                payload["prompt_cache_key"] = pivot_task_id

            response = requests.post(
                url, headers=headers, json=payload, timeout=self.timeout
            )
            response.raise_for_status()

            # print(f"response: \n{json.dumps(response.json(), ensure_ascii=False, indent=2)}")

            return self._parse_dict_response(response.json(), self.model)

        except requests.exceptions.HTTPError as e:
            text = (
                e.response.text if getattr(e, "response", None) is not None else str(e)
            )
            raise RuntimeError(
                f"OpenAI completion API request failed for {self.endpoint}: HTTP {e.response.status_code if hasattr(e, 'response') else 'Unknown'} - {text}"
            ) from e
        except Exception as e:
            raise RuntimeError(
                f"OpenAI completion API request failed for {self.endpoint}: {e!s}"
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
            pivot_task_id = kwargs.pop("_pivot_task_id", "")
            # Merge extra_config with kwargs (kwargs takes precedence)
            merged_kwargs = {**self.extra_config, **kwargs}
            normalized_kwargs = self._merge_extra_body_kwargs(merged_kwargs)
            normalized_kwargs = self._apply_thinking_mode(normalized_kwargs)
            if self.cache_policy == "qwen-completion-block-cache":
                normalized_kwargs = self._with_stream_usage_enabled(normalized_kwargs)

            url = f"{self.endpoint.rstrip('/')}/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            request_messages: list[dict[str, Any]] = [
                {
                    **message,
                    "content": to_openai_completion_content(message.get("content", "")),
                }
                for message in messages
            ]
            if self.cache_policy == "qwen-completion-block-cache":
                request_messages = self._messages_with_qwen_cache_markers(
                    request_messages
                )

            payload: dict[str, Any] = {
                "model": self.model,
                "messages": request_messages,
                "stream": True,
                **normalized_kwargs,
            }
            if (
                self.cache_policy == "kimi-completion-prompt-cache-key"
                and isinstance(pivot_task_id, str)
                and pivot_task_id
            ):
                payload["prompt_cache_key"] = pivot_task_id

            with requests.post(
                url, headers=headers, json=payload, timeout=self.timeout, stream=True
            ) as response:
                response.raise_for_status()

                for line in response.iter_lines():
                    if line:
                        line = line.decode("utf-8")
                        if line.startswith("data: "):
                            data_str = line[len("data: ") :].strip()
                            if data_str == "[DONE]":
                                break

                            try:
                                data_dict = json.loads(data_str)
                                yield self._parse_dict_response(data_dict, self.model)
                            except json.JSONDecodeError:
                                continue

        except requests.exceptions.HTTPError as e:
            text = (
                e.response.text if getattr(e, "response", None) is not None else str(e)
            )
            raise RuntimeError(
                f"OpenAI completion streaming failed for {self.endpoint}: HTTP {e.response.status_code if hasattr(e, 'response') else 'Unknown'} - {text}"
            ) from e
        except Exception as e:
            raise RuntimeError(
                f"OpenAI completion streaming failed for {self.endpoint}: {e!s}"
            ) from e
