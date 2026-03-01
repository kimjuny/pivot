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

    def __init__(
        self,
        endpoint: str,
        model: str,
        api_key: str,
        cache_policy: str = DEFAULT_CACHE_POLICY,
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
        self.timeout = timeout or self.DEFAULT_TIMEOUT
        self.extra_config = extra_config or {}

    def _messages_with_cached_last_block(
        self, messages: list[dict[str, str]]
    ) -> list[dict[str, Any]]:
        """Return messages with ephemeral cache control on the last block."""
        if not messages:
            return []

        cached_messages: list[dict[str, Any]] = [dict(m) for m in messages]
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

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> Response:
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

            url = f"{self.endpoint.rstrip('/')}/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            request_messages: list[dict[str, Any]] = list(messages)
            if self.cache_policy == "qwen-completion-block-cache":
                request_messages = self._messages_with_cached_last_block(messages)

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
        self, messages: list[dict[str, str]], **kwargs: Any
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

            url = f"{self.endpoint.rstrip('/')}/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            request_messages: list[dict[str, Any]] = list(messages)
            if self.cache_policy == "qwen-completion-block-cache":
                request_messages = self._messages_with_cached_last_block(messages)

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
