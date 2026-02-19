"""OpenAI-compatible LLM implementation.

This is a generic implementation that works with any OpenAI-compatible API,
including OpenAI, Azure OpenAI, and other providers that follow the same protocol.
"""

from collections.abc import Iterator
from typing import Any

from openai import OpenAI

from .abstract_llm import AbstractLLM, Response


class OpenAILLM(AbstractLLM):
    """Generic implementation for OpenAI-compatible APIs.

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

    DEFAULT_TIMEOUT = 60  # Request timeout in seconds
    MAX_RETRIES = 3  # Maximum number of retry attempts

    def __init__(
        self,
        endpoint: str,
        model: str,
        api_key: str,
        timeout: int | None = None,
    ):
        """Initialize the OpenAI-compatible LLM implementation.

        Args:
            endpoint: The base URL for the API (e.g., "https://api.openai.com/v1")
            model: The model identifier to use (e.g., "gpt-4", "glm-4")
            api_key: API key for authentication
            timeout: Request timeout in seconds. Defaults to 60 seconds.

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
        self.timeout = timeout or self.DEFAULT_TIMEOUT

        # Initialize OpenAI client with custom endpoint
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.endpoint,
            timeout=self.timeout,
            max_retries=self.MAX_RETRIES,
        )

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
            # Call OpenAI-compatible API
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=messages,  # type: ignore[arg-type]
                response_format={"type": "json_object"},
                **kwargs,  # type: ignore[arg-type]
            )

            # Convert to our structured response format
            return self._convert_response(completion, self.model)

        except Exception as e:
            raise RuntimeError(
                f"OpenAI-compatible API request failed for {self.endpoint}: {e!s}"
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
            # Call OpenAI-compatible API with streaming
            stream = self.client.chat.completions.create(
                model=self.model,
                messages=messages,  # type: ignore[arg-type]
                stream=True,
                **kwargs,  # type: ignore[arg-type]
            )

            # Process the stream
            for chunk in stream:
                yield self._convert_response(chunk, self.model)
        except Exception as e:
            raise RuntimeError(
                f"OpenAI-compatible streaming failed for {self.endpoint}: {e!s}"
            ) from e
