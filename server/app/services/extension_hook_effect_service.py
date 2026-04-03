"""Application helpers for normalized extension hook effects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class HookEffectApplicationResult:
    """Structured result produced after applying normalized hook effects.

    Attributes:
        emitted_events: Runtime events that should be published through the
            normal task event stream.
        task_bootstrap_head_blocks: Prompt blocks inserted before the standard
            task bootstrap user prompt body.
        task_bootstrap_tail_blocks: Prompt blocks inserted after the standard
            task bootstrap user prompt body.
    """

    emitted_events: list[dict[str, Any]] = field(default_factory=list)
    task_bootstrap_head_blocks: list[str] = field(default_factory=list)
    task_bootstrap_tail_blocks: list[str] = field(default_factory=list)


class ExtensionHookEffectService:
    """Apply normalized hook effects without exposing runtime internals.

    Why: hooks should return stable effects, while Pivot decides how those
    effects mutate runtime state or publish observable events.
    """

    def apply_effects(
        self,
        *,
        event_name: str,
        effects: list[dict[str, Any]],
    ) -> HookEffectApplicationResult:
        """Apply one list of normalized effects for a lifecycle event.

        Args:
            event_name: Lifecycle event that produced the effects.
            effects: Normalized effects returned by one or more hooks.

        Returns:
            A structured application result consumed by the supervisor.

        Raises:
            ValueError: If one effect is malformed or not allowed for the event.
        """
        result = HookEffectApplicationResult()
        for effect in effects:
            if not isinstance(effect, dict):
                raise ValueError("Normalized hook effects must be dictionaries.")

            effect_type = str(effect.get("type", "")).strip()
            payload = effect.get("payload")
            if not isinstance(payload, dict):
                raise ValueError("Normalized hook effects must declare a payload.")

            if effect_type == "emit_event":
                result.emitted_events.append(payload)
                continue

            if effect_type != "append_prompt_block":
                raise ValueError(f"Unsupported normalized hook effect '{effect_type}'.")

            if event_name != "task.before_start":
                raise ValueError(
                    "append_prompt_block is only supported for task.before_start."
                )

            target = str(payload.get("target", "")).strip()
            if target != "task_bootstrap":
                raise ValueError(
                    "append_prompt_block currently supports only the task_bootstrap target."
                )

            content = str(payload.get("content", "")).strip()
            if content == "":
                raise ValueError("append_prompt_block requires non-empty content.")

            position = str(payload.get("position", "tail")).strip().lower()
            if position == "head":
                result.task_bootstrap_head_blocks.append(content)
            elif position == "tail":
                result.task_bootstrap_tail_blocks.append(content)
            else:
                raise ValueError(
                    "append_prompt_block position must be either 'head' or 'tail'."
                )

        return result
