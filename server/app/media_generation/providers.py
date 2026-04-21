"""Built-in media-generation providers.

Why: the first implementation ships vendor adapters through extensions only, but
the provider registry keeps a built-in slot so future native providers can plug
into the same lookup path without another refactor.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.media_generation.types import MediaGenerationProvider

BUILTIN_MEDIA_GENERATION_PROVIDERS: dict[str, MediaGenerationProvider] = {}
