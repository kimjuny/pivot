import os
import requests
import time
import uuid
from typing import List, Dict, Any, Optional
from .abstract_llm import AbstractLLM, Response, Choice, ChatMessage, UsageInfo, FinishReason


class DoubaoLLM(AbstractLLM):
    """
    Implementation of AbstractLLM for Doubao AI model.
    Communicates with the Doubao API via REST interface.
    """

    DEFAULT_MODEL = "doubao-seed-1-6-250615"
    API_ENDPOINT = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"

    def __init__(self, model: str = None, api_key: str = None):
        """
        Initialize the DoubaoLLM with the given model and API key.
        
        Args:
            model (str): The model identifier to use. Defaults to doubao-seed-1-6-250615
            api_key (str): API key for authentication. Must be provided as parameter.
        """
        self.model = model or self.DEFAULT_MODEL
        
        if api_key is None:
            raise ValueError("API key must be provided as a parameter")
            
        self.api_key = api_key

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> Response:
        """
        Process a conversation with the Doubao LLM.
        
        Args:
            messages (List[Dict[str, str]]): List of message dictionaries with 'role' and 'content'
            **kwargs: Additional arguments for the chat completion
            
        Returns:
            Response: The structured response from the LLM
            
        Raises:
            ValueError: If API key is not provided
            RuntimeError: If the API request fails or response parsing fails
        """
        # Validate API key
        if not self.api_key:
            raise ValueError("API key is required for Doubao LLM")
        
        # Prepare the request payload
        payload = {
            "model": self.model,
            "messages": messages,
            **kwargs  # Include any additional arguments
        }
        
        # Prepare headers
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        try:
            # Make the API request
            response = requests.post(
                self.API_ENDPOINT,
                headers=headers,
                json=payload,
                timeout=30  # 30 second timeout
            )
            
            # Raise an exception for bad status codes
            response.raise_for_status()
            
            # Parse the JSON response
            raw_response = response.json()
            
            # Convert to our structured response format
            return self._convert_response(raw_response)
            
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"API request failed: {str(e)}") from e
        except Exception as e:
            raise RuntimeError(f"Failed to parse JSON response: {str(e)}") from e

    def _convert_response(self, raw_response: Dict[str, Any]) -> Response:
        """
        Convert the raw API response to our structured Response.
        
        Args:
            raw_response (Dict[str, Any]): Raw response from the Doubao API
            
        Returns:
            Response: Structured response
        """
        # Extract basic information
        response_id = raw_response.get("id", str(uuid.uuid4()))
        created = raw_response.get("created", int(time.time()))
        model = raw_response.get("model", self.model)
        
        # Extract choices
        choices = []
        raw_choices = raw_response.get("choices", [])
        for i, raw_choice in enumerate(raw_choices):
            # Extract message
            raw_message = raw_choice.get("message", {})
            role = raw_message.get("role", "assistant")
            content = raw_message.get("content", "")
            message = ChatMessage(role=role, content=content)
            
            # Extract finish reason
            finish_reason = None
            raw_finish_reason = raw_choice.get("finish_reason")
            if raw_finish_reason:
                try:
                    finish_reason = FinishReason(raw_finish_reason)
                except ValueError:
                    # If the finish reason is not in our enum, we'll leave it as None
                    pass
            
            choice = Choice(
                index=i,
                message=message,
                finish_reason=finish_reason
            )
            choices.append(choice)
        
        # Extract usage information
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