"""Helpers for skill markdown discovery and metadata normalization."""

from __future__ import annotations

SKILL_MARKDOWN_FILENAMES = ("SKILL.md", "skill.md", "Skill.md")


def parse_front_matter(source: str) -> dict[str, str]:
    """Parse a minimal YAML-like front matter block from markdown.

    Args:
        source: Full markdown source.

    Returns:
        Lower-cased key/value pairs from the leading front matter block.
    """
    lines = source.splitlines()
    if len(lines) < 3 or lines[0].strip() != "---":
        return {}

    end_idx = -1
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break
    if end_idx == -1:
        return {}

    metadata: dict[str, str] = {}
    for raw_line in lines[1:end_idx]:
        line = raw_line.strip()
        if not line or ":" not in line or line.startswith("#"):
            continue
        key, value = line.split(":", 1)
        metadata[key.strip().lower()] = value.strip().strip('"').strip("'")
    return metadata


def rewrite_skill_name(source: str, skill_name: str) -> str:
    """Ensure the skill markdown front matter uses the provided skill name.

    Args:
        source: Original markdown source.
        skill_name: Target globally unique skill name.

    Returns:
        Markdown source with a normalized ``name`` entry in front matter.
    """
    has_trailing_newline = source.endswith("\n")
    lines = source.splitlines()

    if len(lines) >= 2 and lines[0].strip() == "---":
        end_idx = -1
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                end_idx = idx
                break

        if end_idx != -1:
            replaced = False
            for idx in range(1, end_idx):
                if lines[idx].strip().lower().startswith("name:"):
                    lines[idx] = f"name: {skill_name}"
                    replaced = True
                    break
            if not replaced:
                lines.insert(1, f"name: {skill_name}")
            result = "\n".join(lines)
            return f"{result}\n" if has_trailing_newline else result

    prefix = ["---", f"name: {skill_name}", "---", ""]
    if source:
        prefix.append(source.rstrip("\n"))
    result = "\n".join(prefix)
    return f"{result}\n" if has_trailing_newline or source else result
