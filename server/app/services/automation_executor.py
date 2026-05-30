"""Execute a single automation run by delegating to ReactTaskSupervisor."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

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
    from zoneinfo import ZoneInfo

logger = get_logger("automation.executor")


def _resolve_date(tz: ZoneInfo) -> str:
    return datetime.now(tz).strftime("%Y-%m-%d")


def _resolve_time(tz: ZoneInfo) -> str:
    return datetime.now(tz).strftime("%H:%M")


def _resolve_datetime(tz: ZoneInfo) -> str:
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")


def _resolve_weekday(tz: ZoneInfo) -> str:
    return datetime.now(tz).strftime("%A")


_VARIABLE_RESOLVERS: dict[str, Callable[[ZoneInfo], str]] = {
    "date": _resolve_date,
    "time": _resolve_time,
    "datetime": _resolve_datetime,
    "weekday": _resolve_weekday,
}


def render_prompt_template(
    template: str,
    extra_vars: dict[str, str] | None = None,
    *,
    timezone_name: str | None = None,
) -> str:
    """Replace ``{{variable}}`` placeholders in a prompt template string.

    Args:
        template: The prompt template with ``{{variable}}`` placeholders.
        extra_vars: Additional variable key-value pairs to substitute.
        timezone_name: IANA timezone name for date/time variables. Falls
            back to UTC when ``None``.
    """
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(timezone_name) if timezone_name else ZoneInfo("UTC")

    variables: dict[str, str] = {}
    for key, resolver in _VARIABLE_RESOLVERS.items():
        variables[key] = resolver(tz)
    if extra_vars:
        variables.update(extra_vars)

    result = template
    for key, value in variables.items():
        result = result.replace("{{" + key + "}}", value)
    return result


def _has_active_react_task(session_id_str: str) -> bool:
    """Check whether a session has a pending or running ReactTask."""
    from app.models.react import ReactTask
    from sqlmodel import col, select

    with managed_session() as db:
        stmt = select(ReactTask).where(
            ReactTask.session_id == session_id_str,
            col(ReactTask.status).in_(["pending", "running"]),
        )
        return db.exec(stmt).first() is not None


async def execute_automation_run(run_id: int) -> None:
    """Execute one automation run from claim to result.

    This coroutine runs inside an ``asyncio.Task`` spawned by the scheduler
    or the queue consumer.  It resolves the session, renders the prompt,
    calls ``ReactTaskSupervisor.start_task()``, records the result, and
    delivers it to the Channel if applicable.
    """
    # ── Setup phase: extract scalar values while DB session is active. ──
    automation_id: int
    agent_id: int
    owner_id: int
    timeout_seconds: int
    prompt_template: str
    session_id_str: str
    session_strategy: str
    channel_session_id: int | None

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

        from app.services.system_settings_service import SystemSettingsService

        _system_tz = SystemSettingsService(db).get_time_zone()

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
        session_strategy = automation.session_strategy
        channel_session_id = automation.channel_session_id

        session = svc.get_or_create_automation_session(automation)
        session_id_str = session.session_id

        # Queue check: if the session has an active ReactTask, enqueue
        # instead of starting a conflicting task.
        if session_strategy == "this_session" and _has_active_react_task(
            session_id_str
        ):
            from app.services.session_task_queue_service import (
                SessionTaskQueueService,
            )

            # Render the prompt now so the queue item is self-contained.
            extra_vars = _resolve_template_vars(agent_id, automation_id)
            rendered = render_prompt_template(
                prompt_template, extra_vars=extra_vars, timezone_name=_system_tz
            )
            q_svc = SessionTaskQueueService(db)
            q_svc.enqueue(
                session_id=session_id_str,
                queue_type="wait_for_completion",
                source="automation",
                source_ref_id=run_id,
                prompt=rendered,
            )
            logger.info(
                "Automation %d run %d queued (session %s has active task)",
                automation_id,
                run_id,
                session_id_str,
            )
            return

        run.session_id = session.id
        run.status = "running"
        run.started_at = datetime.now(UTC)
        db.add(run)
        db.commit()

    # Resolve template variables.
    extra_vars = _resolve_template_vars(agent_id, automation_id)

    # Render prompt template.
    rendered_prompt = render_prompt_template(
        prompt_template, extra_vars=extra_vars, timezone_name=_system_tz
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

        (
            task_status,
            task_error,
            task_tokens,
            task_summary,
        ) = await _wait_for_task_completion(result.task_id, timeout_seconds)

        with managed_session() as db:
            svc = AutomationService(db)
            run = svc.get_run(run_id)
            if run is not None:
                run_status = "completed" if task_status == "completed" else "failed"
                svc.update_run_result(
                    run,
                    status=run_status,
                    error_message=task_error,
                    token_usage=task_tokens,
                    result_summary=task_summary,
                )
                automation = svc.get_required_automation(run.automation_id)
                svc.update_automation_after_run(automation)

        logger.info(
            "Automation %d run %d finished (task %s, status=%s)",
            automation_id,
            run_id,
            result.task_id,
            task_status,
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

    # Channel delivery (best-effort, after run result is recorded).
    if channel_session_id is not None:
        await _deliver_to_channel(run_id, automation_id, channel_session_id)


def _resolve_template_vars(agent_id: int, automation_id: int) -> dict[str, str]:
    """Resolve agent_name and run_number for template variables."""
    extra_vars: dict[str, str] = {}
    with managed_session() as db:
        agent_row = AgentService(db).get_agent(agent_id)
        if agent_row is not None:
            extra_vars["agent_name"] = agent_row.name
        run_number = AutomationService(db).count_runs(automation_id) + 1
        extra_vars["run_number"] = str(run_number)
    return extra_vars


async def _deliver_to_channel(
    run_id: int,
    automation_id: int,
    channel_session_id: int,
) -> None:
    """Deliver automation run result to the bound Channel conversation."""
    import json

    from app.models.automation import Automation, AutomationRun
    from app.models.channel import AgentChannelBinding, ChannelSession

    try:
        conversation_id: str | None = None
        external_user_id: str | None = None
        provider = None

        with managed_session() as db:
            run = db.get(AutomationRun, run_id)
            if run is None:
                return
            automation = db.get(Automation, automation_id)
            if automation is None:
                return

            cs = db.get(ChannelSession, channel_session_id)
            if cs is None:
                logger.warning(
                    "ChannelSession %d not found for delivery", channel_session_id
                )
                return

            # Capture scalars before session closes.
            conversation_id = cs.external_conversation_id
            external_user_id = cs.external_user_id

            binding = db.get(AgentChannelBinding, cs.channel_binding_id)
            if binding is None:
                logger.warning(
                    "AgentChannelBinding %d not found for delivery",
                    cs.channel_binding_id,
                )
                return

            auth_config = json.loads(binding.auth_config)
            runtime_config = json.loads(binding.runtime_config)

            from app.services.provider_registry_service import (
                ProviderRegistryService,
            )

            provider = ProviderRegistryService(db).get_channel_provider(
                binding.channel_key
            )

            if run.result_summary:
                delivery_text = run.result_summary
            elif run.error_message:
                delivery_text = f"[{automation.name}] {run.status}\n{run.error_message}"
            else:
                delivery_text = f"[{automation.name}] {run.status}"

            run.delivery_status = "pending"
            db.add(run)
            db.commit()

        # Provider call outside DB session to avoid holding locks.
        if provider is not None and conversation_id is not None:
            result = provider.send_text(
                auth_config,
                runtime_config,
                conversation_id=conversation_id,
                user_id=external_user_id,
                text=delivery_text,
            )
            if asyncio.iscoroutine(result):
                await result  # type: ignore[reportGeneralTypeIssues]

        with managed_session() as db:
            run = db.get(AutomationRun, run_id)
            if run is not None:
                run.delivery_status = "delivered"
                db.add(run)
                db.commit()

        logger.info(
            "Delivered automation %d run %d to channel session %d",
            automation_id,
            run_id,
            channel_session_id,
        )

    except Exception as exc:
        logger.exception(
            "Failed to deliver automation %d run %d to channel: %s",
            automation_id,
            run_id,
            exc,
        )
        try:
            with managed_session() as db:
                run = db.get(AutomationRun, run_id)
                if run is not None:
                    run.delivery_status = "failed"
                    run.delivery_error = str(exc)[:2000]
                    db.add(run)
                    db.commit()
        except Exception:
            logger.exception("Failed to record delivery failure for run %d", run_id)


def _extract_answer_text(action_output: str) -> str:
    """Extract the ``answer`` field from a JSON action_output string.

    Falls back to the raw string if parsing fails or no ``answer`` key exists.
    """
    try:
        parsed = json.loads(action_output)
        if isinstance(parsed, dict):
            answer = parsed.get("answer")
            if isinstance(answer, str) and answer:
                return answer
    except (json.JSONDecodeError, ValueError):
        pass
    return action_output


async def _wait_for_task_completion(
    task_id: str, timeout: int
) -> tuple[str, str | None, str | None, str | None]:
    """Poll until the ReactTask reaches a terminal state.

    Returns:
        (status, error_message, token_usage_json, result_summary) from the
        ReactTask.  *result_summary* is the ``action_output`` of the final
        ANSWER recursion, or ``None`` when unavailable.
    """
    import json
    import time

    from sqlmodel import col, select

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with managed_session() as db:
            from app.models.react import ReactTask

            statement = select(ReactTask).where(ReactTask.task_id == task_id)
            task = db.exec(statement).first()
            if task is not None and task.status in (
                "completed",
                "failed",
                "cancelled",
            ):
                token_json = json.dumps(
                    {
                        "prompt": task.total_prompt_tokens,
                        "completion": task.total_completion_tokens,
                        "total": task.total_tokens,
                    }
                )

                error_msg: str | None = None
                result_summary: str | None = None

                from app.models.react import ReactRecursion

                if task.status == "completed":
                    ans_stmt = (
                        select(ReactRecursion)
                        .where(
                            ReactRecursion.react_task_id == task.id,
                            ReactRecursion.action_type == "ANSWER",
                        )
                        .order_by(col(ReactRecursion.iteration_index).desc())
                    )
                    last_ans = db.exec(ans_stmt).first()
                    if last_ans is not None and last_ans.action_output:
                        result_summary = _extract_answer_text(last_ans.action_output)
                elif task.status in ("failed", "cancelled"):
                    err_stmt = (
                        select(ReactRecursion)
                        .where(
                            ReactRecursion.react_task_id == task.id,
                            ReactRecursion.status == "error",
                        )
                        .order_by(col(ReactRecursion.iteration_index).desc())
                    )
                    last_err = db.exec(err_stmt).first()
                    if last_err is not None and last_err.error_log:
                        error_msg = last_err.error_log

                return (task.status, error_msg, token_json, result_summary)
        await asyncio.sleep(2)
    raise TimeoutError
