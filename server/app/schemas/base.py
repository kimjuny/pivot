"""Shared Pydantic v2 base models for API schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class AppBaseModel(BaseModel):
    """Base schema with backwards-compatible helpers for the API layer."""

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_orm(cls, obj: Any) -> "AppBaseModel":
        """Preserve the legacy ``from_orm`` call pattern on Pydantic v2."""
        return cls.model_validate(obj)

    def dict(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Preserve the legacy ``dict`` helper on top of ``model_dump``."""
        return self.model_dump(*args, **kwargs)

    def json(self, *args: Any, **kwargs: Any) -> str:
        """Preserve the legacy ``json`` helper on top of ``model_dump_json``."""
        return self.model_dump_json(*args, **kwargs)
