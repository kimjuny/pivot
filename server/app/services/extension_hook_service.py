"""Runtime execution for packaged extension lifecycle hooks."""

from __future__ import annotations

import importlib.util
import inspect
import sys
from datetime import UTC, datetime
from time import perf_counter
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.extension_hook_execution_service import (
        ExtensionHookExecutionService,
    )


class ExtensionHookService:
    """Load and execute packaged extension hooks from one resolved bundle.

    Why: Phase 3 should start with a deliberately narrow ABI. Hooks may observe
    task-level lifecycle events and return structured effects, but they do not
    get direct access to mutable runtime internals or persistence handles.
    """

    def __init__(
        self,
        extension_bundle: list[dict[str, Any]],
        *,
        execution_service: ExtensionHookExecutionService | None = None,
    ) -> None:
        """Store the pinned extension bundle and optional execution logger."""
        self.extension_bundle = extension_bundle
        self.execution_service = execution_service

    async def run_hooks(
        self,
        *,
        event_name: str,
        hook_context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Execute packaged hooks for one lifecycle event."""
        normalized_effects: list[dict[str, Any]] = []
        for extension in self.extension_bundle:
            hooks = extension.get("hooks", [])
            if not isinstance(hooks, list):
                continue

            for hook in hooks:
                if not isinstance(hook, dict):
                    continue
                if hook.get("event") != event_name:
                    continue
                normalized_effects.extend(
                    await self._run_single_hook(
                        extension=extension,
                        hook=hook,
                        hook_context=hook_context,
                    )
                )
        return normalized_effects

    async def run_task_hooks(
        self,
        *,
        event_name: str,
        hook_context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Backward-compatible wrapper for task-level hook execution."""
        return await self.run_hooks(
            event_name=event_name,
            hook_context=hook_context,
        )

    async def replay_hook(
        self,
        *,
        extension_package_id: str,
        extension_version: str,
        event_name: str,
        hook_callable: str,
        hook_context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Replay one specific hook invocation without recording a new log row."""
        extension, hook = self._find_hook(
            extension_package_id=extension_package_id,
            extension_version=extension_version,
            event_name=event_name,
            hook_callable=hook_callable,
        )
        return await self._run_single_hook(
            extension=extension,
            hook=hook,
            hook_context=hook_context,
            record_execution=False,
        )

    async def _run_single_hook(
        self,
        *,
        extension: dict[str, Any],
        hook: dict[str, Any],
        hook_context: dict[str, Any],
        record_execution: bool = True,
    ) -> list[dict[str, Any]]:
        """Execute one hook entry and normalize its returned effects."""
        started_at = datetime.now(UTC)
        started_perf = perf_counter()
        hook_callable = self._load_hook_callable(extension=extension, hook=hook)
        try:
            result = hook_callable(hook_context)
            if inspect.isawaitable(result):
                result = await result
            normalized_events = self._normalize_effects(
                extension=extension,
                hook=hook,
                hook_context=hook_context,
                result=result,
            )
        except Exception as exc:
            if record_execution:
                self._record_execution(
                    extension=extension,
                    hook=hook,
                    hook_context=hook_context,
                    status="failed",
                    started_at=started_at,
                    duration_ms=int((perf_counter() - started_perf) * 1000),
                    effects_payload=None,
                    error_payload={
                        "type": exc.__class__.__name__,
                        "message": str(exc),
                    },
                )
            raise

        if record_execution:
            self._record_execution(
                extension=extension,
                hook=hook,
                hook_context=hook_context,
                status="succeeded",
                started_at=started_at,
                duration_ms=int((perf_counter() - started_perf) * 1000),
                effects_payload=result,
                error_payload=None,
            )
        return normalized_events

    def _find_hook(
        self,
        *,
        extension_package_id: str,
        extension_version: str,
        event_name: str,
        hook_callable: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return one exact hook definition from the pinned bundle."""
        for extension in self.extension_bundle:
            if extension.get("package_id") != extension_package_id:
                continue
            if extension.get("version") != extension_version:
                continue

            hooks = extension.get("hooks", [])
            if not isinstance(hooks, list):
                continue
            for hook in hooks:
                if not isinstance(hook, dict):
                    continue
                if hook.get("event") != event_name:
                    continue
                if hook.get("callable") != hook_callable:
                    continue
                return extension, hook

        raise ValueError(
            "The recorded hook could not be found in the current extension bundle."
        )

    def _load_hook_callable(
        self,
        *,
        extension: dict[str, Any],
        hook: dict[str, Any],
    ) -> Any:
        """Import one hook module and return the configured callable."""
        extension_name = str(extension.get("package_id", "extension"))
        extension_version = str(extension.get("version", "unknown"))
        callable_name = str(hook.get("callable", "")).strip()
        source_path = str(hook.get("source_path", "")).strip()
        if callable_name == "" or source_path == "":
            raise ValueError("Hook source path and callable must be defined.")

        module_key = (
            "_pivot_extension_hook_"
            f"{extension_name}_{extension_version}_{hook.get('event', 'hook')}_"
            f"{callable_name}"
        ).replace("@", "_").replace("/", "_").replace(".", "_")
        spec = importlib.util.spec_from_file_location(module_key, source_path)
        if spec is None or spec.loader is None:
            raise ValueError(f"Unable to import hook entrypoint '{source_path}'.")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_key] = module
        try:
            spec.loader.exec_module(module)  # type: ignore[union-attr]
            hook_callable = getattr(module, callable_name, None)
            if not callable(hook_callable):
                raise ValueError(
                    f"Hook callable '{callable_name}' was not found in '{source_path}'."
                )
            return hook_callable
        finally:
            sys.modules.pop(module_key, None)

    def _normalize_effects(
        self,
        *,
        extension: dict[str, Any],
        hook: dict[str, Any],
        hook_context: dict[str, Any],
        result: Any,
    ) -> list[dict[str, Any]]:
        """Normalize one hook result into stable extension effects."""
        if result is None:
            return []
        if not isinstance(result, list):
            raise ValueError("Hook result must be a list of effects.")

        normalized_effects: list[dict[str, Any]] = []
        extension_hook_metadata = {
            "package_id": extension.get("package_id"),
            "version": extension.get("version"),
            "event": hook.get("event"),
            "callable": hook.get("callable"),
        }
        for effect in result:
            if not isinstance(effect, dict):
                raise ValueError("Hook effects must be dictionaries.")
            effect_type = str(effect.get("type", "")).strip()
            payload = effect.get("payload")
            if effect_type == "emit_event":
                if not isinstance(payload, dict):
                    raise ValueError("emit_event effects must declare a payload object.")
                event_type = str(payload.get("type", "")).strip()
                if event_type == "":
                    raise ValueError("emit_event payload must declare an event type.")
                payload_data = payload.get("data")
                normalized_data = (
                    payload_data if isinstance(payload_data, dict) else {}
                )

                normalized_effects.append(
                    {
                        "type": "emit_event",
                        "payload": {
                            "type": event_type,
                            "task_id": hook_context.get("task_id"),
                            "trace_id": hook_context.get("trace_id"),
                            "iteration": hook_context.get("iteration", 0),
                            "timestamp": payload.get("timestamp")
                            or hook_context.get("timestamp"),
                            "data": {
                                **normalized_data,
                                "extension_hook": extension_hook_metadata,
                            },
                        },
                    }
                )
                continue

            if effect_type != "append_prompt_block":
                raise ValueError(
                    "Only 'emit_event' and 'append_prompt_block' hook effects are currently supported."
                )
            if not isinstance(payload, dict):
                raise ValueError(
                    "append_prompt_block effects must declare a payload object."
                )
            content = str(payload.get("content", "")).strip()
            if content == "":
                raise ValueError("append_prompt_block requires non-empty content.")
            position = str(payload.get("position", "tail")).strip().lower()
            if position not in {"head", "tail"}:
                raise ValueError(
                    "append_prompt_block position must be 'head' or 'tail'."
                )
            target = str(payload.get("target", "task_bootstrap")).strip()
            normalized_effects.append(
                {
                    "type": "append_prompt_block",
                    "payload": {
                        "target": target,
                        "position": position,
                        "content": content,
                        "extension_hook": extension_hook_metadata,
                    },
                }
            )
        return normalized_effects

    def _record_execution(
        self,
        *,
        extension: dict[str, Any],
        hook: dict[str, Any],
        hook_context: dict[str, Any],
        status: str,
        started_at: datetime,
        duration_ms: int,
        effects_payload: Any,
        error_payload: Any,
    ) -> None:
        """Persist one hook execution log row when logging is enabled."""
        if self.execution_service is None:
            return

        raw_release_id = hook_context.get("release_id")

        self.execution_service.create_execution(
            session_id=(
                str(hook_context.get("session_id"))
                if isinstance(hook_context.get("session_id"), str)
                else None
            ),
            task_id=str(hook_context.get("task_id", "")),
            trace_id=(
                str(hook_context.get("trace_id"))
                if isinstance(hook_context.get("trace_id"), str)
                else None
            ),
            iteration=int(hook_context.get("iteration", 0) or 0),
            agent_id=int(hook_context.get("agent_id", 0) or 0),
            release_id=int(raw_release_id) if isinstance(raw_release_id, int) else None,
            extension_package_id=str(extension.get("package_id", "")),
            extension_version=str(extension.get("version", "")),
            hook_event=str(hook.get("event", "")),
            hook_callable=str(hook.get("callable", "")),
            status=status,
            hook_context_payload=hook_context,
            effects_payload=effects_payload,
            error_payload=error_payload,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            duration_ms=duration_ms,
        )
