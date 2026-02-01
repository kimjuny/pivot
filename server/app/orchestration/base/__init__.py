"""
Agent base module.

Contains input/output message structures and system prompts for agent communication.
"""

from .input_message import InputMessage
from .output_message import OutputMessage
from .stream import AgentResponseChunk, AgentResponseChunkType
from .system_prompt import get_build_prompt, get_chat_prompt

__all__ = [
    "AgentResponseChunk",
    "AgentResponseChunkType",
    "InputMessage",
    "OutputMessage",
    "get_build_prompt",
    "get_chat_prompt",
]
