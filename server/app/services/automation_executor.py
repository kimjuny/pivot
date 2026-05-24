"""Execute a single automation run by delegating to ReactTaskSupervisor."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.db.session import managed_session
from app.services.agent_service import AgentService
from app.services.automation_service import AutomationService
from app.services.react_task_supervisor import (
    ReactTaskLaunchRequest,
    get_react_task_supervisor,
)
from app.utils.logging_config import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

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
    # ── Setup phase: extract scalar values while DB session is active. ──
    automation_id: int
    agent_id: int
    owner_id: int
    timeout_seconds: int
    prompt_template: str
    session_id_str: str

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

        # Capture scalars before session closes.
        if automation.id is None:
            logger.error("Automation has no primary key")
            return
        automation_id = automation.id
        agent_id = automation.agent_id
        owner_id = automation.owner_id
        timeout_seconds = automation.timeout_seconds
        prompt_template = automation.prompt_template

        session = svc.get_or_create_automation_session(automation)
        session_id_str = session.session_id

        run.session_id = session.id
        run.status = "running"
        run.started_at = datetime.now(UTC)
        db.add(run)
        db.commit()

    # Resolve agent name and run count for template variables.
    extra_vars: dict[str, str] = {}
    with managed_session() as db:
        agent_row = AgentService(db).get_agent(agent_id)
        if agent_row is not None:
            extra_vars["agent_name"] = agent_row.name
        run_number = AutomationService(db).count_runs(automation_id) + 1
        extra_vars["run_number"] = str(run_number)

    # Render prompt template.
    rendered_prompt = render_prompt_template(
        prompt_template, extra_vars=extra_vars
    )

    # Launch task via supervisor.
    launch = ReactTaskLaunchRequest(
        agent_id=agent_id,
        message=rendered_prompt,
        user_id=owner_id,
        session_id=session_id_str,
        file_ids=[],
    )

    try:
        supervisor = get_react_task_supervisor()
        result = await asyncio.wait_for(
            supervisor.start_task(launch),
            timeout=timeout_seconds,
        )

        await _wait_for_task_completion(result.task_id, timeout_seconds)

        with managed_session() as db:
            svc = AutomationService(db)
            run = svc.get_run(run_id)
            if run is not None:
                svc.update_run_result(run, status="completed")
                automation = svc.get_required_automation(run.automation_id)
                svc.update_automation_after_run(automation)

        logger.info(
            "Automation %d run %d completed (task %s)",
            automation_id,
            run_id,
            result.task_id,
        )

    except TimeoutError:
        logger.warning(
            "Automation %d run %d timed out after %ds",
            automation_id,
            run_id,
            timeout_seconds,
        )
        with managed_session() as db:
            svc = AutomationService(db)
            run = svc.get_run(run_id)
            if run is not None:
                svc.update_run_result(
                    run,
                    status="timeout",
                    error_message=f"Timed out after {timeout_seconds}s",
                )
                automation = svc.get_required_automation(run.automation_id)
                svc.update_automation_after_run(automation)

    except Exception as exc:
        logger.exception(
            "Automation %d run %d failed: %s",
            automation_id,
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
