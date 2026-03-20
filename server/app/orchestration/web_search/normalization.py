"""Normalization helpers for LLM-facing web-search tool arguments."""

from __future__ import annotations

import re
from datetime import date
from typing import Any
from urllib.parse import urlparse

_DATE_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})")

_SEARCH_DEPTH_ALIASES = {
    "basic": "basic",
    "advanced": "advanced",
    "fast": "fast",
    "ultra-fast": "ultra-fast",
    "ultrafast": "ultra-fast",
    "ultra_fast": "ultra-fast",
    "ultra fast": "ultra-fast",
}

_TOPIC_ALIASES = {
    "general": "general",
    "news": "news",
    "finance": "finance",
}

_TIME_RANGE_ALIASES = {
    "day": "day",
    "d": "day",
    "week": "week",
    "w": "week",
    "month": "month",
    "m": "month",
    "year": "year",
    "y": "year",
}

_TRUE_VALUES = {"true", "1", "yes", "y", "on"}
_FALSE_VALUES = {"false", "0", "no", "n", "off"}


def normalize_required_text(value: Any, *, field_name: str) -> str:
    """Normalize a required string field."""
    normalized = normalize_optional_text(value, field_name=field_name)
    if normalized is None:
        raise ValueError(f"{field_name} must not be blank.")
    return normalized


def normalize_optional_text(value: Any, *, field_name: str) -> str | None:
    """Trim one optional string-like field and collapse blank to None."""
    del field_name
    if value is None:
        return None
    normalized = str(value).strip()
    if normalized == "":
        return None
    return normalized


def normalize_enum_text(
    value: Any,
    *,
    field_name: str,
    aliases: dict[str, str],
) -> str | None:
    """Normalize one enum-like string field through alias mapping."""
    normalized = normalize_optional_text(value, field_name=field_name)
    if normalized is None:
        return None

    lookup_key = normalized.lower()
    canonical = aliases.get(lookup_key)
    if canonical is None:
        raise ValueError(
            f"{field_name} must be one of: {', '.join(sorted(set(aliases.values())))}."
        )
    return canonical


def normalize_date_text(value: Any, *, field_name: str) -> str | None:
    """Normalize date-like text into canonical YYYY-MM-DD form."""
    normalized = normalize_optional_text(value, field_name=field_name)
    if normalized is None:
        return None

    match = _DATE_PATTERN.search(normalized)
    if match is None:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format.")

    normalized_date = match.group(1)
    try:
        return date.fromisoformat(normalized_date).isoformat()
    except ValueError as exc:
        raise ValueError(f"{field_name} must use a valid YYYY-MM-DD date.") from exc


def normalize_domain_list(value: Any) -> list[str]:
    """Normalize one domain allow/deny list into clean hostnames."""
    if value is None:
        return []

    raw_items: list[Any]
    if isinstance(value, str):
        raw_items = [value]
    elif isinstance(value, list | tuple | set):
        raw_items = list(value)
    else:
        raw_items = [value]

    normalized_domains: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        normalized_domain = _normalize_domain(item)
        if normalized_domain is None or normalized_domain in seen:
            continue
        seen.add(normalized_domain)
        normalized_domains.append(normalized_domain)
    return normalized_domains


def normalize_web_search_request_payload(raw_payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize the LLM-facing request payload before strong validation.

    Why: LLM tool arguments frequently include trailing newlines, case drift,
    or date strings with extra suffixes. The tool layer should absorb that
    noise so providers see canonical parameters instead of brittle raw text.
    """
    normalized = dict(raw_payload)
    normalized["query"] = normalize_required_text(
        raw_payload.get("query"),
        field_name="query",
    )
    normalized["max_results"] = normalize_int(
        raw_payload.get("max_results"),
        field_name="max_results",
    )
    provider_value = normalize_optional_text(
        raw_payload.get("provider"),
        field_name="provider",
    )
    normalized["provider"] = provider_value.lower() if provider_value else None
    normalized["search_depth"] = normalize_enum_text(
        raw_payload.get("search_depth"),
        field_name="search_depth",
        aliases=_SEARCH_DEPTH_ALIASES,
    )
    normalized["topic"] = normalize_enum_text(
        raw_payload.get("topic"),
        field_name="topic",
        aliases=_TOPIC_ALIASES,
    )
    normalized["time_range"] = normalize_enum_text(
        raw_payload.get("time_range"),
        field_name="time_range",
        aliases=_TIME_RANGE_ALIASES,
    )
    normalized["start_date"] = normalize_date_text(
        raw_payload.get("start_date"),
        field_name="start_date",
    )
    normalized["end_date"] = normalize_date_text(
        raw_payload.get("end_date"),
        field_name="end_date",
    )
    normalized["country"] = normalize_optional_text(
        raw_payload.get("country"),
        field_name="country",
    )
    if normalized["country"] is not None:
        normalized["country"] = normalized["country"].lower()
    normalized["include_domains"] = normalize_domain_list(
        raw_payload.get("include_domains")
    )
    normalized["exclude_domains"] = normalize_domain_list(
        raw_payload.get("exclude_domains")
    )
    for key in (
        "include_answer",
        "include_raw_content",
        "include_images",
        "include_image_descriptions",
        "include_favicon",
        "auto_parameters",
        "exact_match",
        "include_usage",
        "safe_search",
    ):
        normalized[key] = normalize_bool(raw_payload.get(key), field_name=key)
    return normalized


def _normalize_domain(value: Any) -> str | None:
    """Normalize one domain or URL into a hostname-only string."""
    normalized = normalize_optional_text(value, field_name="domain")
    if normalized is None:
        return None

    parsed = urlparse(
        normalized if "://" in normalized else f"//{normalized}",
        scheme="https",
    )
    host = parsed.netloc or parsed.path
    host = host.strip().lower()
    if host == "":
        return None

    if "/" in host:
        host = host.split("/", 1)[0]
    if ":" in host and not host.startswith("["):
        host = host.split(":", 1)[0]
    return host or None


def normalize_int(value: Any, *, field_name: str) -> int | None:
    """Normalize one integer-like field."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer.")
    if isinstance(value, int):
        return value

    normalized = normalize_optional_text(value, field_name=field_name)
    if normalized is None:
        return None
    try:
        return int(normalized)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an integer.") from exc


def normalize_bool(value: Any, *, field_name: str) -> bool:
    """Normalize one boolean-like field."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False

    normalized = normalize_optional_text(value, field_name=field_name)
    if normalized is None:
        return False

    lookup_key = normalized.lower()
    if lookup_key in _TRUE_VALUES:
        return True
    if lookup_key in _FALSE_VALUES:
        return False
    raise ValueError(f"{field_name} must be a boolean.")
