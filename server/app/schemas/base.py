"""Shared Pydantic v2 base models for API schemas."""

import re
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, model_serializer

_naive_dt_re = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?$")


def _ensure_utc_iso(v: Any) -> Any:
    """Convert a value to a UTC-aware ISO 8601 string if it is a datetime."""
    if isinstance(v, datetime):
        return v.replace(tzinfo=UTC).isoformat()
    # Pydantic's JSON handler pre-serializes datetimes to strings without
    # timezone info. Detect those and append +00:00.
    if isinstance(v, str) and _naive_dt_re.match(v):
        return v + "+00:00"
    return v


class AppBaseModel(BaseModel):
    """Base schema with automatic UTC datetime serialization.

    All response schemas inherit from this model.  A wrap-style
    ``model_serializer`` ensures that every ``datetime`` field is
    automatically rendered as an explicit UTC ISO 8601 string, so
    callers never need to remember ``.replace(tzinfo=UTC).isoformat()``.
    """

    model_config = ConfigDict(from_attributes=True)

    @model_serializer(mode="wrap")
    def _serialize_datetimes(self, handler: Any) -> dict[str, Any]:
        result = handler(self)
        return {k: _ensure_utc_iso(v) for k, v in result.items()}
