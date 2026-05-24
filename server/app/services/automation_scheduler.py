"""Background scheduler that scans for due automations and dispatches runs."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app.config import get_settings
from app.db.session import managed_session
from app.models.automation import AutomationRun
from app.services.automation_executor import execute_automation_run
from app.services.automation_service import AutomationService
from app.utils.logging_config import get_logger
from sqlmodel import select

logger = get_logger("automation.scheduler")


class AutomationScheduler:
    """Background loop that claims and dispatches due automation runs.

    Follows the same pattern as ``ChannelRuntimeManager``: started in
    ``main.py`` startup, runs as an ``asyncio.Task``, and is cancelled
    on shutdown.
    """

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._active_runs: set[int] = set()
        self._run_tasks: dict[int, asyncio.Task[None]] = {}

    async def start(self) -> None:
        """Start the background scheduler loop."""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop())
        logger.info("Automation scheduler started")

    async def stop(self) -> None:
        """Stop the scheduler and wait for in-flight runs to finish."""
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        run_task_ids = list(self._run_tasks)
        for rid in run_task_ids:
            t = self._run_tasks.pop(rid, None)
            if t is not None and not t.done():
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass

        logger.info("Automation scheduler stopped")

    # ── Internal ──────────────────────────────────────────────────

    async def _loop(self) -> None:
        """Main scan-dispatch-sleep cycle."""
        settings = get_settings()

        while True:
            try:
                if settings.AUTOMATION_SCHEDULER_ENABLED:
                    await self._scan_and_dispatch()
                    await self._reap_stale_runs()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Automation scheduler scan failed")

            await asyncio.sleep(settings.AUTOMATION_SCHEDULER_SCAN_INTERVAL_SECONDS)

    async def _scan_and_dispatch(self) -> None:
        """Find due automations, claim runs, and dispatch executors."""
        settings = get_settings()

        with managed_session() as db:
            svc = AutomationService(db)
            due = svc.get_due_automations()

        if not due:
            return

        for automation in due:
            if (
                len(self._active_runs)
                >= settings.AUTOMATION_SCHEDULER_MAX_CONCURRENT_RUNS
            ):
                logger.info(
                    "Concurrency limit reached, deferring remaining automations"
                )
                break

            with managed_session() as db:
                svc = AutomationService(db)
                run = svc.claim_run(
                    automation_id=automation.id,
                    scheduled_at=automation.next_run_at or datetime.now(UTC),
                )

            if run is None:
                continue

            logger.info(
                "Claimed run %d for automation %d",
                run.id,
                automation.id,
            )
            self._dispatch_run(run.id)

    def _dispatch_run(self, run_id: int) -> None:
        """Spawn an executor task for one run."""
        self._active_runs.add(run_id)

        async def _run_and_cleanup() -> None:
            try:
                await execute_automation_run(run_id)
            except Exception:
                logger.exception("Run %d executor failed", run_id)
            finally:
                self._active_runs.discard(run_id)
                self._run_tasks.pop(run_id, None)

        task = asyncio.create_task(_run_and_cleanup())
        self._run_tasks[run_id] = task

    async def _reap_stale_runs(self) -> None:
        """Mark runs stuck in ``running`` beyond the timeout as ``timeout``."""
        settings = get_settings()
        timeout_seconds = settings.AUTOMATION_RUN_TIMEOUT_SECONDS
        cutoff = datetime.now(UTC).timestamp() - timeout_seconds * 2

        with managed_session() as db:
            statement = select(AutomationRun).where(
                AutomationRun.status == "running",
            )
            runs = list(db.exec(statement).all())

        for run in runs:
            if run.started_at is None:
                continue
            if run.started_at.timestamp() < cutoff:
                logger.warning(
                    "Reaping stale run %d (started %s)",
                    run.id,
                    run.started_at.isoformat(),
                )
                with managed_session() as db:
                    svc = AutomationService(db)
                    stale_run = svc.get_run(run.id)
                    if stale_run is not None and stale_run.status == "running":
                        svc.update_run_result(
                            stale_run,
                            status="timeout",
                            error_message="Reaped by stale-run watchdog",
                        )


# Module-level singleton, started/stopped from main.py.
automation_scheduler = AutomationScheduler()
