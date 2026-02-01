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


class GlmLLM(AbstractLLM):
    """
    Implementation of AbstractLLM for GLM (ZhipuAI) model.
    Communicates with the GLM API via REST interface.
    """

    DEFAULT_MODEL = "glm-4.7"
    API_ENDPOINT = "https://open.bigmodel.cn/api/coding/paas/v4/chat/completions"
    DEFAULT_TIMEOUT = 60
    MAX_RETRIES = 3

    def __init__(self, model: str | None = None, api_key: str | None = None, timeout: int | None = None):
        """
        Initialize the GlmLLM with the given model and API key.
        
        Args:
            model (str): The model identifier to use. Defaults to glm-4.7
            api_key (str): API key for authentication. Must be provided as parameter.
            timeout (int): Request timeout in seconds. Defaults to 60 seconds.
        """
        self.model = model or self.DEFAULT_MODEL
        
        if api_key is None:
            raise ValueError("API key must be provided as a parameter")
            
        self.api_key = api_key
        self.timeout = timeout or self.DEFAULT_TIMEOUT

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> Response:
        """
        Process a conversation with the GLM LLM.
        
        Args:
            messages (List[Dict[str, str]]): List of message dictionaries with 'role' and 'content'
            **kwargs: Additional arguments for the chat completion
            
        Returns:
            Response: The structured response from the LLM
            
        Raises:
            ValueError: If API key is not provided
            RuntimeError: If the API request fails or response parsing fails
        """
        if not self.api_key:
            raise ValueError("API key is required for GLM LLM")
        
        payload = {
            "model": self.model,
            "messages": messages,
            **kwargs
        }
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        for attempt in range(self.MAX_RETRIES):
            try:
                response = requests.post(
                    self.API_ENDPOINT,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout
                )
                
                response.raise_for_status()
                raw_response = response.json()
                return self._convert_response(raw_response)
                
            except requests.exceptions.HTTPError as e:
                if attempt < self.MAX_RETRIES - 1:
                    # Handle 429 Too Many Requests specifically
                    if e.response.status_code == 429:
                        print(f"Rate limit hit (429). Retrying immediately (attempt {attempt + 1}/{self.MAX_RETRIES})...")
                    else:
                        pass
                    
                    continue
                else:
                    raise RuntimeError(f"API request failed after {self.MAX_RETRIES} attempts: {e!s}") from e
                    
            except requests.exceptions.Timeout:
                if attempt < self.MAX_RETRIES - 1:
                    continue
                else:
                    raise RuntimeError(f"API request timed out after {self.MAX_RETRIES} attempts.") from None
                    
            except requests.exceptions.RequestException as e:
                if attempt < self.MAX_RETRIES - 1:
                    continue
                else:
                    raise RuntimeError(f"API request failed after {self.MAX_RETRIES} attempts: {e!s}") from e
            except Exception as e:
                raise RuntimeError(f"Failed to parse JSON response: {e!s}") from e
        
        raise RuntimeError("Unexpected error in chat method")

    def chat_stream(self, messages: list[dict[str, str]], **kwargs: Any) -> Iterator[Response]:
        """
        Process a conversation with the GLM LLM in streaming mode.
        
        Args:
            messages (List[Dict[str, str]]): List of message dictionaries with 'role' and 'content'
            **kwargs: Additional arguments for the chat completion
            
        Yields:
            Response: A chunk of the structured response from the LLM
            
        Raises:
            ValueError: If API key is not provided
            RuntimeError: If the API request fails
        """
        if not self.api_key:
            raise ValueError("API key is required for GLM LLM")
        
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            **kwargs
        }
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        response = None
        for attempt in range(self.MAX_RETRIES):
            try:
                response = requests.post(
                    self.API_ENDPOINT,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                    stream=True
                )
                
                response.raise_for_status()
                break
                
            except requests.exceptions.HTTPError as e:
                if attempt < self.MAX_RETRIES - 1:
                    if e.response.status_code == 429:
                        # Simple backoff for rate limits
                        time.sleep(1)
                    continue
                else:
                    raise RuntimeError(f"API request failed after {self.MAX_RETRIES} attempts: {e!s}") from e
                    
            except requests.exceptions.Timeout:
                if attempt < self.MAX_RETRIES - 1:
                    continue
                else:
                    raise RuntimeError(f"API request timed out after {self.MAX_RETRIES} attempts.") from None
                    
            except requests.exceptions.RequestException as e:
                if attempt < self.MAX_RETRIES - 1:
                    continue
                else:
                    raise RuntimeError(f"API request failed after {self.MAX_RETRIES} attempts: {e!s}") from e
        
        if response is None:
             raise RuntimeError("Failed to establish connection for streaming")

        try:
            for line in response.iter_lines():
                if not line:
                    continue
                    
                decoded_line = line.decode('utf-8')
                if decoded_line.startswith('data: '):
                    data_str = decoded_line[6:]
                    
                    if data_str.strip() == '[DONE]':
                        break
                        
                    try:
                        raw_response = json.loads(data_str)
                        yield self._convert_response(raw_response)
                    except json.JSONDecodeError:
                        continue
                        
        except Exception as e:
            raise RuntimeError(f"Error processing stream: {e!s}") from e

    def _convert_response(self, raw_response: dict[str, Any]) -> Response:
        """
        Convert the raw API response to our structured Response.
        """
        response_id = raw_response.get("id", str(uuid.uuid4()))
        created = raw_response.get("created", int(time.time()))
        model = raw_response.get("model", self.model)
        
        choices = []
        raw_choices = raw_response.get("choices", [])
        for i, raw_choice in enumerate(raw_choices):
            raw_message = raw_choice.get("message") or raw_choice.get("delta", {})
            role = raw_message.get("role", "assistant")
            content = raw_message.get("content", "")
            reasoning_content = raw_message.get("reasoning_content", None)
            message = ChatMessage(role=role, content=content, reasoning_content=reasoning_content)
            
            finish_reason = None
            raw_finish_reason = raw_choice.get("finish_reason")
            if raw_finish_reason:
                with contextlib.suppress(ValueError):
                    finish_reason = FinishReason(raw_finish_reason)
            
            choice = Choice(
                index=i,
                message=message,
                finish_reason=finish_reason
            )
            choices.append(choice)
        
        usage = None
        raw_usage = raw_response.get("usage")
        if raw_usage:
            usage = UsageInfo(
                prompt_tokens=raw_usage.get("prompt_tokens", 0),
                completion_tokens=raw_usage.get("completion_tokens", 0),
                total_tokens=raw_usage.get("total_tokens", 0)
            )
        
        return Response(
            id=response_id,
            choices=choices,
            created=created,
            model=model,
            usage=usage
        )
