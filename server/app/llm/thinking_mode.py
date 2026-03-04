"""Utilities for protocol-level thinking mode handling."""

VALID_THINKING_MODES = {"auto", "enabled", "disabled"}


def normalize_thinking_mode(thinking: str | None) -> str:
    """Normalize a thinking mode to a supported value."""
    normalized = (thinking or "auto").strip().lower()
    if normalized not in VALID_THINKING_MODES:
        return "auto"
    return normalized
