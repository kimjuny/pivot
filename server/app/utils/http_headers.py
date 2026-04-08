"""Helpers for building HTTP headers that survive non-ASCII filenames."""

from __future__ import annotations

from urllib.parse import quote


def build_inline_content_disposition(filename: str) -> str:
    """Return a safe inline Content-Disposition value for arbitrary filenames.

    Why: chat uploads and generated artifacts often contain user-provided names
    with non-ASCII characters. Starlette ultimately serializes headers as
    latin-1, so directly embedding those names can crash otherwise healthy file
    responses during history reload.

    Args:
        filename: Original filename to expose to the client.

    Returns:
        One RFC 5987-compatible inline Content-Disposition header value.
    """
    normalized = filename.strip() or "download"
    ascii_fallback = (
        normalized.encode("ascii", "ignore").decode("ascii").strip() or "download"
    )
    escaped_fallback = (
        ascii_fallback.replace("\\", "_")
        .replace('"', "'")
        .replace("/", "_")
        .replace(";", "_")
    )
    encoded_filename = quote(normalized, safe="")
    return (
        f'inline; filename="{escaped_fallback}"; '
        f"filename*=UTF-8''{encoded_filename}"
    )
