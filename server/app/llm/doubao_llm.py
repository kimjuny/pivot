from collections.abc import Iterator
from typing import Any

from openai import OpenAI

from .abstract_llm import (
    AbstractLLM,
    Response,
)


class DoubaoLLM(AbstractLLM):
    """
    Implementation of AbstractLLM for Doubao AI model.
    Uses OpenAI-compatible API via the OpenAI library.
    """

    DEFAULT_MODEL = "doubao-seed-1-6-250615"
    # DEFAULT_MODEL = "doubao-seed-1-8-251228"
    API_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
    DEFAULT_TIMEOUT = 60  # Request timeout in seconds
    MAX_RETRIES = 3  # Maximum number of retry attempts

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        timeout: int | None = None,
    ):
        """
        Initialize the DoubaoLLM with the given model and API key.

        Args:
            model: The model identifier to use. Defaults to doubao-seed-1-6-250615
            api_key: API key for authentication. Must be provided as parameter.
            timeout: Request timeout in seconds. Defaults to 60 seconds.

        Raises:
            ValueError: If API key is not provided
        """
        self.model = model or self.DEFAULT_MODEL

        if api_key is None:
            raise ValueError("API key must be provided as a parameter")

        self.api_key = api_key
        self.timeout = timeout or self.DEFAULT_TIMEOUT

        # Initialize OpenAI client with Doubao's base URL
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.API_BASE_URL,
            timeout=self.timeout,
            max_retries=self.MAX_RETRIES,
        )

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> Response:
        """
        Process a conversation with the Doubao LLM.

        Args:
            messages: List of message dictionaries with 'role' and 'content'
            **kwargs: Additional arguments for the chat completion

        Returns:
            Response: The structured response from the LLM

        Raises:
            ValueError: If API key is not provided
            RuntimeError: If the API request fails
        """
        if not self.api_key:
            raise ValueError("API key is required for Doubao LLM")

        try:
            # Call OpenAI-compatible API
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                **kwargs,  # type: ignore[arg-type]
            )

            # Convert to our structured response format
            return self._convert_response(completion, self.model)

        except Exception as e:
            raise RuntimeError(f"API request failed: {e!s}") from e

    def chat_stream(
        self, messages: list[dict[str, str]], **kwargs: Any
    ) -> Iterator[Response]:
        """
        Process a conversation with the Doubao LLM in streaming mode.

        Args:
            messages: List of message dictionaries with 'role' and 'content'
            **kwargs: Additional arguments for the chat completion

        Yields:
            Response: A chunk of the structured response from the LLM

        Raises:
            ValueError: If API key is not provided
            RuntimeError: If the API request fails
        """
        if not self.api_key:
            raise ValueError("API key is required for Doubao LLM")

        try:
            # Call OpenAI-compatible API with streaming
            stream = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True,
                **kwargs,  # type: ignore[arg-type]
            )

            # Process the stream
            for chunk in stream:
                yield self._convert_response(chunk, self.model)

        except Exception as e:
            raise RuntimeError(f"Error processing stream: {e!s}") from e
