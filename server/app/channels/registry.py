"""Registry helpers for built-in channel providers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.channels.providers import BUILTIN_PROVIDERS

if TYPE_CHECKING:
    from app.channels.types import ChannelProvider


def list_channel_providers() -> list[ChannelProvider]:
    """Return every installed built-in provider."""
    return list(BUILTIN_PROVIDERS.values())


def get_channel_provider(channel_key: str) -> ChannelProvider:
    """Resolve one channel provider by its stable key.

    Args:
        channel_key: Provider identifier, such as ``work_wechat``.

    Returns:
        The registered channel provider.

    Raises:
        KeyError: If the provider is not registered.
    """
    return BUILTIN_PROVIDERS[channel_key]
