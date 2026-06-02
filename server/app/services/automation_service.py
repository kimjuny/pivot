"""CRUD operations for automation entities."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from app.models.automation import Automation, AutomationRun
from app.models.session import Session
from app.services.agent_service import AgentService
from app.services.provider_registry_service import ProviderRegistryService
from app.utils.logging_config import get_logger
from croniter import croniter
from sqlmodel import col, select

logger = get_logger("automation.service")

if TYPE_CHECKING:
    from sqlmodel import Session as DBSession


_VALID_STATUSES = {"active", "paused", "disabled"}
_VALID_SESSION_STRATEGIES = {"reuse", "isolate", "this_session"}


class AutomationService:
    """Provide CRUD operations for automation and automation run rows."""

    def __init__(self, db: DBSession) -> None:
        self.db = db

    # ── Automation CRUD ───────────────────────────────────────────

    def list_automations(
        self,
        user_id: int,
        *,
        status: str | None = None,
    ) -> list[Automation]:
        """List automations owned by a user, optionally filtered by status.

        Args:
            user_id: Owner user identifier.
            status: Optional status filter.

        Returns:
            Matching automation rows ordered by creation time descending.
        """
        statement = (
            select(Automation)
            .where(Automation.owner_id == user_id)
            .order_by(col(Automation.created_at).desc())
        )
        if status is not None:
            statement = statement.where(Automation.status == status)
        return list(self.db.exec(statement).all())

    def get_automation(self, automation_id: int) -> Automation | None:
        """Return one automation row or None."""
        return self.db.get(Automation, automation_id)

    def get_automation_by_uuid(self, automation_id_str: str) -> Automation | None:
        """Return one automation by its UUID string."""
        statement = select(Automation).where(
            Automation.automation_id == automation_id_str,
        )
        return self.db.exec(statement).first()

    def get_required_automation(self, automation_id: int) -> Automation:
        """Return one automation or raise.

        Raises:
            ValueError: If the automation does not exist.
        """
        automation = self.get_automation(automation_id)
        if automation is None:
            raise ValueError(f"Automation {automation_id} not found")
        return automation

    def get_channel_info_by_session_ids(
        self,
        channel_session_ids: list[int],
    ) -> dict[int, dict[str, str | None]]:
        """Return channel display metadata keyed by ChannelSession id."""
        if not channel_session_ids:
            return {}

        from app.models.channel import AgentChannelBinding, ChannelSession

        channel_sessions = list(
            self.db.exec(
                select(ChannelSession).where(
                    col(ChannelSession.id).in_(channel_session_ids)
                )
            ).all()
        )
        if not channel_sessions:
            return {}

        binding_ids = list({row.channel_binding_id for row in channel_sessions})
        bindings = list(
            self.db.exec(
                select(AgentChannelBinding).where(
                    col(AgentChannelBinding.id).in_(binding_ids)
                )
            ).all()
        )
        binding_map = {binding.id: binding for binding in bindings}

        provider_map = {
            provider.manifest.key: provider.manifest
            for provider in ProviderRegistryService(self.db).list_channel_providers()
        }

        result: dict[int, dict[str, str | None]] = {}
        for channel_session in channel_sessions:
            if channel_session.id is None:
                continue
            binding = binding_map.get(channel_session.channel_binding_id)
            if binding is None:
                continue
            manifest = provider_map.get(binding.channel_key)
            result[channel_session.id] = {
                "channel_key": binding.channel_key,
                "channel_name": manifest.name if manifest else binding.name,
                "channel_logo_url": manifest.logo_url if manifest else None,
            }
        return result

    def get_agent_info_by_ids(
        self, agent_ids: list[int]
    ) -> dict[int, dict[str, str | None]]:
        """Return agent display metadata keyed by Agent id."""
        if not agent_ids:
            return {}

        from app.models.agent import Agent
        from app.models.llm import LLM

        agents = list(
            self.db.exec(select(Agent).where(col(Agent.id).in_(agent_ids))).all()
        )
        llm_ids = [agent.llm_id for agent in agents if agent.llm_id is not None]
        llms = (
            {
                llm.id: llm
                for llm in self.db.exec(
                    select(LLM).where(col(LLM.id).in_(llm_ids))
                ).all()
                if llm.id is not None
            }
            if llm_ids
            else {}
        )
        result: dict[int, dict[str, str | None]] = {}
        for agent in agents:
            if agent.id is None:
                continue
            model_display = agent.model_name
            if agent.llm_id is not None:
                llm = llms.get(agent.llm_id)
                if llm is not None:
                    model_display = f"{llm.name} ({llm.model})"
            result[agent.id] = {
                "agent_name": agent.name,
                "agent_description": agent.description,
                "agent_model_name": model_display,
            }
        return result

    def require_automation_ownership(
        self, automation_id: int, user_id: int
    ) -> Automation:
        """Return one automation owned by the given user or raise.

        Raises:
            ValueError: If not found or not owned.
        """
        automation = self.get_required_automation(automation_id)
        if automation.owner_id != user_id:
            raise ValueError("Not authorized to access this automation")
        return automation

    def create_automation(
        self,
        *,
        owner_id: int,
        agent_id: int,
        name: str,
        prompt_template: str,
        trigger_config: str,
        session_strategy: str = "reuse",
        max_iterations: int | None = None,
        timeout_seconds: int = 300,
        notify_on_completion: bool = False,
        notify_on_failure: bool = True,
        channel_session_id: int | None = None,
    ) -> Automation:
        """Create a new automation.

        Args:
            owner_id: User who will own the automation.
            agent_id: Published agent to run tasks against.
            name: Human-readable name.
            prompt_template: Message template with optional {{variables}}.
            trigger_config: JSON trigger configuration.
            session_strategy: "reuse", "isolate", or "this_session".
            max_iterations: Optional override for agent max_iteration.
            timeout_seconds: Per-run timeout.
            notify_on_completion: Notify user on success.
            notify_on_failure: Notify user on failure.
            channel_session_id: Bound ChannelSession for "this_session" strategy.

        Returns:
            The created automation row.

        Raises:
            ValueError: If the agent is not published/open or validation fails.
        """
        if session_strategy not in _VALID_SESSION_STRATEGIES:
            raise ValueError(f"Invalid session_strategy: {session_strategy}")
        if session_strategy == "this_session" and channel_session_id is None:
            raise ValueError("channel_session_id is required for this_session strategy")
        _validate_trigger_config(trigger_config)

        agent = AgentService(self.db).require_session_creation_ready(agent_id)
        release_id = agent.active_release_id
        if release_id is None:
            raise ValueError("Agent has no active release")

        next_run_at = _compute_next_run(trigger_config)

        automation = Automation(
            owner_id=owner_id,
            agent_id=agent_id,
            release_id=release_id,
            name=name,
            trigger_type="cron",
            trigger_config=trigger_config,
            prompt_template=prompt_template,
            session_strategy=session_strategy,
            max_iterations=max_iterations,
            timeout_seconds=timeout_seconds,
            notify_on_completion=notify_on_completion,
            notify_on_failure=notify_on_failure,
            channel_session_id=channel_session_id,
            next_run_at=next_run_at,
        )
        self.db.add(automation)
        self.db.commit()
        self.db.refresh(automation)
        return automation

    def update_automation(
        self,
        automation_id: int,
        *,
        user_id: int,
        **fields: object,
    ) -> Automation:
        """Update fields on an automation owned by the given user.

        If the trigger_config changes, next_run_at is recomputed.

        Raises:
            ValueError: If not found, not owned, or validation fails.
        """
        automation = self.require_automation_ownership(automation_id, user_id)

        if "status" in fields:
            status = fields["status"]
            if status not in _VALID_STATUSES:
                raise ValueError(f"Invalid status: {status}")

        if "session_strategy" in fields:
            strategy = fields["session_strategy"]
            if strategy not in _VALID_SESSION_STRATEGIES:
                raise ValueError(f"Invalid session_strategy: {strategy}")

        if "trigger_config" in fields:
            _validate_trigger_config(str(fields["trigger_config"]))

        for key, value in fields.items():
            setattr(automation, key, value)

        automation.updated_at = datetime.now(UTC)

        if "trigger_config" in fields or "status" in fields:
            if automation.status == "active":
                automation.next_run_at = _compute_next_run(
                    automation.trigger_config,
                )
            else:
                automation.next_run_at = None

        self.db.add(automation)
        self.db.commit()
        self.db.refresh(automation)
        return automation

    def delete_automation(self, automation_id: int, user_id: int) -> None:
        """Delete an automation and all its runs.

        Raises:
            ValueError: If not found or not owned.
        """
        automation = self.require_automation_ownership(automation_id, user_id)

        run_statement = select(AutomationRun).where(
            AutomationRun.automation_id == automation.id,
        )
        for run in self.db.exec(run_statement).all():
            self.db.delete(run)

        self.db.delete(automation)
        self.db.commit()

    # ── AutomationRun CRUD ────────────────────────────────────────

    def list_runs(
        self,
        automation_id: int,
        *,
        user_id: int,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AutomationRun], int]:
        """List runs for an automation with total count.

        Returns:
            (runs, total_count) tuple.
        """
        self.require_automation_ownership(automation_id, user_id)

        base = select(AutomationRun).where(
            AutomationRun.automation_id == automation_id,
        )
        total = len(self.db.exec(base).all())
        runs = list(
            self.db.exec(
                base.order_by(col(AutomationRun.scheduled_at).desc())
                .offset(offset)
                .limit(limit)
            ).all()
        )
        return runs, total

    def count_runs(self, automation_id: int) -> int:
        """Return total run count for an automation without loading rows."""
        base = select(AutomationRun).where(
            AutomationRun.automation_id == automation_id,
        )
        return len(self.db.exec(base).all())

    def get_user_stats(self, user_id: int) -> dict[str, int | float]:
        """Aggregate automation and run statistics for a user.

        Returns:
            Dict with total, active, paused counts plus 7-day run metrics.
        """

        automations = self.list_automations(user_id)
        total = len(automations)
        active = sum(1 for a in automations if a.status == "active")
        paused = sum(1 for a in automations if a.status == "paused")

        seven_days_ago = datetime.now(UTC) - timedelta(days=7)
        automation_ids = [a.id for a in automations if a.id is not None]

        runs_7d: int = 0
        success_7d: int = 0
        tokens_7d: int = 0

        if automation_ids:
            run_statement = (
                select(AutomationRun)
                .where(col(AutomationRun.automation_id).in_(automation_ids))
                .where(col(AutomationRun.scheduled_at) >= seven_days_ago)
            )
            for run in self.db.exec(run_statement).all():
                runs_7d += 1
                if run.status in ("completed",):
                    success_7d += 1
                if run.token_usage:
                    try:
                        usage = json.loads(run.token_usage)
                        tokens_7d += (usage.get("prompt", 0) or 0) + (
                            usage.get("completion", 0) or 0
                        )
                    except (json.JSONDecodeError, TypeError):
                        pass

        success_rate = round(success_7d / runs_7d * 100, 1) if runs_7d > 0 else 0.0

        return {
            "total_automations": total,
            "active_count": active,
            "paused_count": paused,
            "runs_last_7_days": runs_7d,
            "success_rate": success_rate,
            "total_tokens_last_7_days": tokens_7d,
        }

    def get_run(self, run_id: int) -> AutomationRun | None:
        """Return one run or None."""
        return self.db.get(AutomationRun, run_id)

    def get_run_by_uuid(self, run_id_str: str) -> AutomationRun | None:
        """Return one run by its UUID string."""
        statement = select(AutomationRun).where(AutomationRun.run_id == run_id_str)
        return self.db.exec(statement).first()

    # ── Scheduler helpers ─────────────────────────────────────────

    def claim_run(
        self, automation_id: int, scheduled_at: datetime
    ) -> AutomationRun | None:
        """Atomically claim a run slot for the given automation and time.

        Checks for any existing run at this slot:
        - Pending/running: slot is already claimed, return None.
        - Terminal (completed/failed/timeout/cancelled): advance the
          automation's next_run_at past this slot and return None so
          the next scheduler scan uses the updated time.
        """
        existing = self.db.exec(
            select(AutomationRun).where(
                AutomationRun.automation_id == automation_id,
                AutomationRun.scheduled_at == scheduled_at,
            )
        ).first()
        if existing is not None:
            if existing.status in ("pending", "running"):
                logger.debug(
                    "Slot already claimed: automation_id=%d scheduled_at=%s",
                    automation_id,
                    scheduled_at.isoformat(),
                )
                return None

            # Terminal run blocks this slot — advance automation past it.
            logger.info(
                "Slot has terminal run (status=%s), advancing automation_id=%d",
                existing.status,
                automation_id,
            )
            self.advance_stuck_automation(automation_id)
            return None

        run = AutomationRun(
            automation_id=automation_id,
            scheduled_at=scheduled_at,
            status="pending",
        )
        self.db.add(run)
        try:
            self.db.commit()
            self.db.refresh(run)
            return run
        except Exception:
            self.db.rollback()
            logger.warning(
                "claim_run failed for automation_id=%d scheduled_at=%s",
                automation_id,
                scheduled_at.isoformat(),
            )
            return None

    def get_due_automations(self) -> list[Automation]:
        """Return active automations whose next_run_at has passed."""
        statement = (
            select(Automation)
            .where(Automation.status == "active")
            .where(col(Automation.next_run_at).is_not(None))
            .where(col(Automation.next_run_at) <= datetime.now(UTC))
        )
        return list(self.db.exec(statement).all())

    def advance_stuck_automation(self, automation_id: int) -> None:
        """Advance next_run_at past the current stuck slot.

        Recomputes from trigger_config until the next fire time is in
        the future, then persists it.
        """
        automation = self.db.get(Automation, automation_id)
        if automation is None or automation.status != "active":
            return
        next_at = _compute_next_run(automation.trigger_config)
        # Guard against cron expressions that still resolve to the past.
        now = datetime.now(UTC)
        for _ in range(100):
            if next_at > now:
                break
            next_at = croniter(
                json.loads(automation.trigger_config)["cron"], next_at
            ).get_next(datetime)
        automation.next_run_at = next_at
        automation.updated_at = now
        self.db.add(automation)
        self.db.commit()
        logger.info(
            "Advanced automation_id=%d next_run_at to %s",
            automation_id,
            next_at.isoformat(),
        )

    def get_or_create_automation_session(
        self,
        automation: Automation,
    ) -> Session:
        """Return the existing automation session or create a new one.

        For "reuse" strategy, finds the existing session for this automation.
        For "isolate" strategy, always creates a new one.
        For "this_session" strategy, returns the bound ChannelSession's
        Pivot session.
        """
        if automation.session_strategy == "this_session":
            return self._resolve_channel_session(automation)

        if automation.session_strategy == "reuse":
            existing = list(
                self.db.exec(
                    select(Session)
                    .where(Session.type == "automation")
                    .where(Session.agent_id == automation.agent_id)
                    .where(Session.user_id == automation.owner_id)
                    .where(Session.title == f"automation:{automation.automation_id}")
                    .order_by(col(Session.created_at).desc())
                    .limit(1)
                ).all()
            )
            if existing:
                return existing[0]

        return self._create_automation_session(automation)

    def _resolve_channel_session(self, automation: Automation) -> Session:
        """Return the Pivot session backing the bound ChannelSession."""
        from app.models.channel import ChannelSession as ChannelSessionModel

        if automation.channel_session_id is None:
            raise ValueError("this_session strategy requires channel_session_id")
        cs = self.db.get(ChannelSessionModel, automation.channel_session_id)
        if cs is None:
            raise ValueError(
                f"ChannelSession {automation.channel_session_id} not found"
            )
        session = self.db.exec(
            select(Session).where(Session.session_id == cs.pivot_session_id)
        ).first()
        if session is None:
            raise ValueError(
                f"Pivot session {cs.pivot_session_id} behind ChannelSession "
                f"{cs.id} not found"
            )
        return session

    def _create_automation_session(self, automation: Automation) -> Session:
        """Create a new session for an automation run."""
        from uuid import uuid4

        from app.services.workspace_service import WorkspaceService

        session_id = uuid4().hex

        workspace = WorkspaceService(self.db).create_workspace(
            agent_id=automation.agent_id,
            user_id=automation.owner_id,
            scope="session_private",
            session_id=session_id,
        )

        session = Session(
            session_id=session_id,
            agent_id=automation.agent_id,
            type="automation",
            release_id=automation.release_id,
            user_id=automation.owner_id,
            status="active",
            runtime_status="idle",
            workspace_id=workspace.workspace_id,
            title=f"automation:{automation.automation_id}",
            chat_history=json.dumps({"version": 1, "messages": []}),
            react_llm_messages="[]",
            react_llm_cache_state="{}",
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def update_run_result(
        self,
        run: AutomationRun,
        *,
        status: str,
        result_summary: str | None = None,
        error_message: str | None = None,
        token_usage: str | None = None,
    ) -> None:
        """Update a run with final status and result."""
        run.status = status
        run.result_summary = result_summary
        run.error_message = error_message
        run.token_usage = token_usage
        run.finished_at = datetime.now(UTC)
        self.db.add(run)
        self.db.commit()

    def update_automation_after_run(
        self,
        automation: Automation,
    ) -> None:
        """Update last_run_at and compute next_run_at after a run completes."""
        automation.last_run_at = datetime.now(UTC)
        automation.next_run_at = _compute_next_run(automation.trigger_config)
        automation.updated_at = datetime.now(UTC)
        self.db.add(automation)
        self.db.commit()


# ── Module-level helpers ──────────────────────────────────────────


def _validate_trigger_config(trigger_config: str) -> None:
    """Ensure trigger_config contains a valid cron expression.

    Raises:
        ValueError: If the cron expression is missing or invalid.
    """
    try:
        config = json.loads(trigger_config)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"Invalid trigger_config JSON: {exc}") from exc

    cron_expr = config.get("cron", "").strip()
    if not cron_expr:
        raise ValueError("trigger_config must contain a 'cron' expression")

    try:
        croniter(cron_expr)
    except (ValueError, KeyError) as exc:
        raise ValueError(f"Invalid cron expression: {exc}") from exc


def _compute_next_run(trigger_config: str) -> datetime:
    """Compute the next fire time from a trigger config JSON string."""
    config = json.loads(trigger_config)
    cron_expr = config["cron"]
    return croniter(cron_expr, datetime.now(UTC)).get_next(datetime)
