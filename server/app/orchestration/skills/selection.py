"""Skill selection orchestration for ReAct pre-processing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.llm.abstract_llm import AbstractLLM

_TEMPLATE_PATH = Path(__file__).parent / "skill_selection.md"
try:
    _SKILL_SELECTION_PROMPT = _TEMPLATE_PATH.read_text(encoding="utf-8")
except FileNotFoundError as exc:  # pragma: no cover - startup misconfiguration
    raise RuntimeError(f"Missing skill selection template: {_TEMPLATE_PATH}") from exc


def _safe_load_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    return json.loads(text)


def build_skill_selection_prompt(
    user_intent: str,
    skill_metadata: list[dict[str, Any]],
    session_memory: dict[str, Any],
) -> str:
    """Render skill selection prompt from template."""
    prompt = _SKILL_SELECTION_PROMPT
    prompt = prompt.replace("{{user_intent}}", user_intent)

    metadata_json = json.dumps(skill_metadata, ensure_ascii=False, indent=2)
    # Support both template spellings.
    prompt = prompt.replace("{{skills_metadata}}", metadata_json)
    prompt = prompt.replace("{{skill_metadata}}", metadata_json)

    session_memory_json = json.dumps(session_memory, ensure_ascii=False, indent=2)
    prompt = prompt.replace("{{session_memory}}", session_memory_json)
    return prompt


def select_skills(
    llm: AbstractLLM,
    user_intent: str,
    skill_metadata: list[dict[str, Any]],
    session_memory: dict[str, Any],
) -> list[str]:
    """Run LLM-based skill selection and return selected skill names."""
    if not skill_metadata:
        return []

    prompt = build_skill_selection_prompt(
        user_intent=user_intent,
        skill_metadata=skill_metadata,
        session_memory=session_memory,
    )

    response = llm.chat(
        messages=[
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": "Select skills and return strict JSON only.",
            },
        ]
    )

    content = response.first().message.content or "{}"
    parsed = _safe_load_json(content)
    selected_raw = parsed.get("selected_skills", [])
    if not isinstance(selected_raw, list):
        return []

    available_names = {item.get("name") for item in skill_metadata}
    result: list[str] = []
    for item in selected_raw:
        if not isinstance(item, str):
            continue
        if item in available_names and item not in result:
            result.append(item)
    return result
