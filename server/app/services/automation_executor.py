"""Execute a single automation run by delegating to ReactTaskSupervisor."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from app.db.session import managed_session
from app.services.automation_service import AutomationService
from app.services.react_task_supervisor import (
    ReactTaskLaunchRequest,
    get_react_task_supervisor,
)
from app.utils.logging_config import get_logger

logger = get_logger("automation.executor")

# Template variables available in prompt_template.
_TEMPLATE_VARIABLES: dict[str, Any] = {}

_VARIABLE_RESOLVERS: dict[str, Callable[[], str]] = {}


def _resolve_date() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _resolve_time() -> str:
    return datetime.now(UTC).strftime("%H:%M")


def _resolve_datetime() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _resolve_weekday() -> str:
    return datetime.now(UTC).strftime("%A")


_VARIABLE_RESOLVERS = {
    "date": _resolve_date,
    "time": _resolve_time,
    "datetime": _resolve_datetime,
    "weekday": _resolve_weekday,
}


def render_prompt_template(
    template: str, extra_vars: dict[str, str] | None = None
) -> str:
    """Replace ``{{variable}}`` placeholders in a prompt template string."""
    variables: dict[str, str] = {}
    for key, resolver in _VARIABLE_RESOLVERS.items():
        variables[key] = resolver()
    if extra_vars:
        variables.update(extra_vars)

    result = template
    for key, value in variables.items():
        result = result.replace("{{" + key + "}}", value)
    return result


async def execute_automation_run(run_id: int) -> None:
    """Execute one automation run from claim to result.

    This coroutine runs inside an ``asyncio.Task`` spawned by the scheduler.
    It resolves the session, renders the prompt, calls
    ``ReactTaskSupervisor.start_task()``, and records the result.
    """
    with managed_session() as db:
        svc = AutomationService(db)
        run = svc.get_run(run_id)
        if run is None:
            logger.error("AutomationRun %d disappeared before execution", run_id)
            return

        automation = svc.get_automation(run.automation_id)
        if automation is None:
            logger.error(
                "Automation %d disappeared before execution",
                run.automation_id,
            )
            return

        if automation.status != "active":
            logger.info(
                "Automation %d is no longer active, skipping run %d",
                automation.id,
                run.id,
            )
            svc.update_run_result(
                run, status="cancelled", error_message="Automation paused or disabled"
            )
            return

    # Resolve or create session.
    with managed_session() as db:
        svc = AutomationService(db)
        automation = svc.get_required_automation(run.automation_id)
        session = svc.get_or_create_automation_session(automation)
        run.session_id = session.id
        run.status = "running"
        run.started_at = datetime.now(UTC)
        db.add(run)
        db.commit()

    # Render prompt template.
    rendered_prompt = render_prompt_template(automation.prompt_template)

    # Launch task via supervisor.
    launch = ReactTaskLaunchRequest(
        agent_id=automation.agent_id,
        message=rendered_prompt,
        user_id=automation.owner_id,
        session_id=session.session_id,
        file_ids=[],
    )

    try:
        supervisor = get_react_task_supervisor()
        result = await asyncio.wait_for(
            supervisor.start_task(launch),
            timeout=automation.timeout_seconds,
        )
        run.task_id = result.task_id

        # Wait for task completion by polling.
        await _wait_for_task_completion(result.task_id, automation.timeout_seconds)

        with managed_session() as db:
            svc = AutomationService(db)
            run = svc.get_run(run_id)
            if run is not None:
                svc.update_run_result(run, status="completed")
                automation = svc.get_required_automation(run.automation_id)
                svc.update_automation_after_run(automation)

        logger.info(
            "Automation %d run %d completed (task %s)",
            automation.id,
            run_id,
            result.task_id,
        )

    except TimeoutError:
        logger.warning(
            "Automation %d run %d timed out after %ds",
            automation.id,
            run_id,
            automation.timeout_seconds,
        )
        with managed_session() as db:
            svc = AutomationService(db)
            run = svc.get_run(run_id)
            if run is not None:
                svc.update_run_result(
                    run,
                    status="timeout",
                    error_message=f"Timed out after {automation.timeout_seconds}s",
                )
                automation = svc.get_required_automation(run.automation_id)
                svc.update_automation_after_run(automation)

    except Exception as exc:
        logger.exception(
            "Automation %d run %d failed: %s",
            automation.id,
            run_id,
            exc,
        )
        with managed_session() as db:
            svc = AutomationService(db)
            run = svc.get_run(run_id)
            if run is not None:
                svc.update_run_result(
                    run,
                    status="failed",
                    error_message=str(exc),
                )
                automation = svc.get_required_automation(run.automation_id)
                svc.update_automation_after_run(automation)


async def _wait_for_task_completion(task_id: str, timeout: int) -> None:
    """Poll until the ReactTask reaches a terminal state."""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with managed_session() as db:
            from app.models.react import ReactTask
            from sqlmodel import select

            statement = select(ReactTask).where(ReactTask.task_id == task_id)
            task = db.exec(statement).first()
            if task is not None and task.status in (
                "completed",
                "failed",
                "cancelled",
            ):
                return
        await asyncio.sleep(2)
    raise TimeoutError()
