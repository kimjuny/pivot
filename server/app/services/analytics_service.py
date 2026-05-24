"""Aggregation queries for Studio Dashboard and Agent Analytics Cockpit."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import requests
from app.config import get_settings
from app.models.agent import Agent
from app.models.agent_release import AgentRelease
from app.models.channel import AgentChannelBinding, ChannelEventLog, ChannelSession
from app.models.llm import LLM
from app.models.react import ReactTask
from app.models.session import Session
from app.models.user import User
from sqlalchemy import func
from sqlmodel import col, select

if TYPE_CHECKING:
    from sqlmodel import Session as DBSession


@dataclass(frozen=True)
class StudioOverview:
    """Aggregated KPI counts for the studio dashboard header."""

    agents_total: int
    agents_new: int
    sessions_total: int
    sessions_delta: int
    users_total: int
    users_new: int
    tasks_total: int
    tasks_daily_avg: float
    success_rate: float
    success_rate_delta: float


@dataclass(frozen=True)
class DailySessionCount:
    """One day's session counts broken down by type."""

    date: str
    client: int
    studio_test: int
    automation: int


@dataclass(frozen=True)
class TaskStats:
    """Task status counts for the donut chart."""

    completed: int
    failed: int
    cancelled: int
    running: int
    pending: int


@dataclass(frozen=True)
class DailyTokenUsage:
    """One day's token usage broken down by type."""

    date: str
    uncached_input: int
    cached_input: int
    output: int


@dataclass(frozen=True)
class AgentPopularity:
    """One agent's popularity rank by sessions and tasks."""

    agent_id: int
    agent_name: str
    model_name: str
    session_count: int
    task_count: int


@dataclass(frozen=True)
class RuntimeHealth:
    """Runtime infrastructure health summary."""

    active_sandboxes: int
    storage_status: str
    failed_tasks_24h: int


@dataclass(frozen=True)
class RecentActivityItem:
    """One recent session event for the activity feed."""

    session_id: str
    title: str
    agent_name: str
    model_name: str
    username: str
    session_type: str
    status: str
    created_at: str


@dataclass(frozen=True)
class DailyUserActivity:
    """One day's user activity metrics."""

    date: str
    dau: int
    wau: int
    mau: int


@dataclass(frozen=True)
class DailyUserGrowth:
    """One day's new user registrations."""

    date: str
    new_users: int


@dataclass(frozen=True)
class AgentOverview:
    """Aggregated KPI counts for a single agent."""

    sessions: int
    tasks: int
    success_rate: float
    avg_tokens: float
    avg_iterations: float


@dataclass(frozen=True)
class IterationBucket:
    """One iteration range bucket and its task count."""

    range: str
    count: int


@dataclass(frozen=True)
class AgentUserStats:
    """One user's usage stats for a specific agent."""

    user_id: int
    username: str
    sessions: int
    tasks: int
    total_tokens: int
    last_active: str


@dataclass(frozen=True)
class AgentReleaseItem:
    """One release entry for the release timeline."""

    version: int
    release_note: str | None
    change_summary: list[str]
    published_by: str | None
    created_at: str


@dataclass(frozen=True)
class DailyClientUsage:
    """One day's client usage for a specific agent."""

    date: str
    sessions: int
    dau: int


@dataclass(frozen=True)
class ChannelActivityItem:
    """Per-channel activity stats for a specific agent."""

    channel_key: str
    channel_name: str
    inbound_events: int
    active_sessions: int
    last_event_at: str


def _date_bucket(column: Any) -> Any:
    """Return a SQL expression that truncates *column* to a date string."""
    if get_settings().DATABASE_URL.startswith("sqlite"):
        return func.strftime("%Y-%m-%d", column)
    return func.date(column)


def _parse_range(range_str: str) -> int:
    """Convert a range parameter like ``'30d'`` into an integer day count."""
    default = 30
    if not isinstance(range_str, str) or not range_str.endswith("d"):
        return default
    try:
        days = int(range_str[:-1])
    except (ValueError, TypeError):
        return default
    return days if days in (7, 30, 90) else default


def _fill_date_range(
    data: dict[str, Any],
    days: int,
    zero_factory: Any,
) -> dict[str, Any]:
    """Pad *data* with zero entries for every day in the last *days* days.

    Args:
        data: Mapping of ``{date_str: row_dict}``.
        days: Number of days to fill (including today).
        zero_factory: Callable returning a zero-filled row dict for a date.

    Returns:
        Ordered dict with one entry per day, oldest first.
    """
    now = datetime.now(UTC)
    filled: dict[str, Any] = {}
    for i in range(days - 1, -1, -1):
        d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        filled[d] = data.get(d, zero_factory(d))
    return filled


class AnalyticsService:
    """Aggregate queries for analytics dashboards."""

    def __init__(self, db: DBSession) -> None:
        self.db = db

    def get_studio_overview(self, days: int) -> StudioOverview:
        """Return KPI card summaries for the studio dashboard."""
        now = datetime.now(UTC)
        range_start = now - timedelta(days=days)
        prev_start = range_start - timedelta(days=days)

        agents_total = self.db.exec(
            select(func.count(Agent.id))  # type: ignore[reportArgumentType, reportCallIssue]
        ).one()
        agents_new = self.db.exec(
            select(func.count(Agent.id)).where(col(Agent.created_at) >= range_start)  # type: ignore[reportArgumentType, reportCallIssue]
        ).one()

        sessions_in_range = self.db.exec(
            select(func.count(Session.id)).where(  # type: ignore[reportArgumentType, reportCallIssue]
                col(Session.type) == "client",
                col(Session.created_at) >= range_start,
            )
        ).one()
        sessions_prev = self.db.exec(
            select(func.count(Session.id)).where(  # type: ignore[reportArgumentType, reportCallIssue]
                col(Session.type) == "client",
                col(Session.created_at) >= prev_start,
                col(Session.created_at) < range_start,
            )
        ).one()

        users_total = self.db.exec(
            select(func.count(User.id))  # type: ignore[reportArgumentType, reportCallIssue]
        ).one()
        users_new = self.db.exec(
            select(func.count(User.id)).where(col(User.created_at) >= range_start)  # type: ignore[reportArgumentType, reportCallIssue]
        ).one()

        tasks_total = self.db.exec(
            select(func.count(ReactTask.id)).where(  # type: ignore[reportArgumentType, reportCallIssue]
                col(ReactTask.created_at) >= range_start
            )
        ).one()
        tasks_daily_avg = round(tasks_total / max(days, 1), 1)

        completed = self.db.exec(
            select(func.count(ReactTask.id)).where(  # type: ignore[reportArgumentType, reportCallIssue]
                col(ReactTask.status) == "completed",
                col(ReactTask.created_at) >= range_start,
            )
        ).one()
        success_rate = round(
            (completed / tasks_total * 100) if tasks_total > 0 else 0, 1
        )

        prev_tasks = self.db.exec(
            select(func.count(ReactTask.id)).where(  # type: ignore[reportArgumentType, reportCallIssue]
                col(ReactTask.created_at) >= prev_start,
                col(ReactTask.created_at) < range_start,
            )
        ).one()
        prev_completed = self.db.exec(
            select(func.count(ReactTask.id)).where(  # type: ignore[reportArgumentType, reportCallIssue]
                col(ReactTask.status) == "completed",
                col(ReactTask.created_at) >= prev_start,
                col(ReactTask.created_at) < range_start,
            )
        ).one()
        prev_success_rate = (prev_completed / prev_tasks * 100) if prev_tasks > 0 else 0
        success_rate_delta = round(success_rate - prev_success_rate, 1)

        return StudioOverview(
            agents_total=agents_total,
            agents_new=agents_new,
            sessions_total=sessions_in_range,
            sessions_delta=sessions_in_range - sessions_prev,
            users_total=users_total,
            users_new=users_new,
            tasks_total=tasks_total,
            tasks_daily_avg=tasks_daily_avg,
            success_rate=success_rate,
            success_rate_delta=success_rate_delta,
        )

    def get_session_trends(self, days: int) -> list[DailySessionCount]:
        """Return daily session counts by type for the selected range."""
        now = datetime.now(UTC)
        range_start = now - timedelta(days=days)
        date_col = _date_bucket(Session.created_at).label("date")

        stmt = (
            select(date_col, Session.type, func.count(Session.id))  # type: ignore[reportArgumentType, reportCallIssue]
            .where(col(Session.created_at) >= range_start)
            .group_by("date", Session.type)  # type: ignore[reportArgumentType]
            .order_by("date")  # type: ignore[reportArgumentType]
        )
        raw: dict[str, dict[str, int]] = {}
        for row in self.db.exec(stmt):
            date_str, session_type, count = row
            if date_str not in raw:
                raw[date_str] = {"client": 0, "studio_test": 0, "automation": 0}
            key = (
                session_type
                if session_type in ("client", "automation")
                else "studio_test"
            )
            raw[date_str][key] = count

        filled = _fill_date_range(
            raw,
            days,
            lambda d: {"client": 0, "studio_test": 0, "automation": 0},
        )
        return [
            DailySessionCount(
                date=date_str,
                client=counts["client"],
                studio_test=counts["studio_test"],
                automation=counts["automation"],
            )
            for date_str, counts in filled.items()
        ]

    def get_task_stats(self, days: int) -> TaskStats:
        """Return task status counts for the donut chart."""
        now = datetime.now(UTC)
        range_start = now - timedelta(days=days)

        status_counts: dict[str, int] = {}
        rows = self.db.exec(
            select(ReactTask.status, func.count(ReactTask.id))  # type: ignore[reportArgumentType, reportCallIssue]
            .where(col(ReactTask.created_at) >= range_start)
            .group_by(ReactTask.status)
        )
        for status, count in rows:
            status_counts[status] = count

        return TaskStats(
            completed=status_counts.get("completed", 0),
            failed=status_counts.get("failed", 0),
            cancelled=status_counts.get("cancelled", 0),
            running=status_counts.get("running", 0),
            pending=status_counts.get("pending", 0),
        )

    def get_token_usage(self, days: int) -> list[DailyTokenUsage]:
        """Return daily token usage broken down by prompt/completion/cached."""
        now = datetime.now(UTC)
        range_start = now - timedelta(days=days)
        date_col = _date_bucket(ReactTask.created_at).label("date")

        stmt = (
            select(
                date_col,
                func.sum(ReactTask.total_prompt_tokens),  # type: ignore[reportArgumentType, reportCallIssue]
                func.sum(ReactTask.total_completion_tokens),  # type: ignore[reportArgumentType, reportCallIssue]
                func.sum(ReactTask.total_cached_input_tokens),  # type: ignore[reportArgumentType, reportCallIssue]
            )
            .where(col(ReactTask.created_at) >= range_start)
            .group_by("date")  # type: ignore[reportArgumentType]
            .order_by("date")  # type: ignore[reportArgumentType]
        )

        raw: dict[str, dict[str, int]] = {}
        for row in self.db.exec(stmt):
            prompt = row[1] or 0
            cached = row[3] or 0
            raw[row[0]] = {
                "uncached_input": max(prompt - cached, 0),
                "cached_input": cached,
                "output": row[2] or 0,
            }

        filled = _fill_date_range(
            raw,
            days,
            lambda d: {"uncached_input": 0, "cached_input": 0, "output": 0},
        )
        return [
            DailyTokenUsage(
                date=date_str,
                uncached_input=vals["uncached_input"],
                cached_input=vals["cached_input"],
                output=vals["output"],
            )
            for date_str, vals in filled.items()
        ]

    def get_agent_popularity(self, days: int, limit: int) -> list[AgentPopularity]:
        """Return top agents with both session and task counts.

        Results are ordered by session count descending so the default
        view (Sessions tab) shows the most relevant agents first.
        """
        now = datetime.now(UTC)
        range_start = now - timedelta(days=days)

        session_cte = (
            select(  # type: ignore[reportArgumentType]
                col(Session.agent_id),
                func.count(col(Session.id)).label("session_count"),
            )
            .where(
                col(Session.type) == "client",
                col(Session.created_at) >= range_start,
            )
            .group_by(col(Session.agent_id))
            .subquery()
        )

        task_cte = (
            select(  # type: ignore[reportArgumentType]
                col(ReactTask.agent_id),
                func.count(col(ReactTask.id)).label("task_count"),
            )
            .where(col(ReactTask.created_at) >= range_start)
            .group_by(col(ReactTask.agent_id))
            .subquery()
        )

        stmt = (
            select(  # type: ignore[reportArgumentType]
                col(Agent.id),
                col(Agent.name),
                col(LLM.model),
                func.coalesce(session_cte.c.session_count, 0),
                func.coalesce(task_cte.c.task_count, 0),
            )
            .join(session_cte, col(Agent.id) == session_cte.c.agent_id, isouter=True)
            .join(task_cte, col(Agent.id) == task_cte.c.agent_id, isouter=True)
            .join(LLM, Agent.llm_id == LLM.id, isouter=True)
            .order_by(func.coalesce(session_cte.c.session_count, 0).desc())
            .limit(limit)
        )

        return [
            AgentPopularity(
                agent_id=agent_id,
                agent_name=agent_name,
                model_name=model or "",
                session_count=session_count,
                task_count=task_count,
            )
            for agent_id, agent_name, model, session_count, task_count in self.db.exec(
                stmt
            )
        ]

    async def get_runtime_health(self) -> RuntimeHealth:
        """Return runtime infrastructure health summary."""
        now = datetime.now(UTC)
        yesterday = now - timedelta(hours=24)

        failed_tasks_24h = self.db.exec(
            select(func.count(ReactTask.id)).where(  # type: ignore[reportArgumentType, reportCallIssue]
                col(ReactTask.status) == "failed",
                col(ReactTask.created_at) >= yesterday,
            )
        ).one()

        active_sandboxes = 0
        settings = get_settings()
        sandbox_url = settings.SANDBOX_MANAGER_URL

        try:
            sb_resp = requests.get(f"{sandbox_url}/sandboxes", timeout=5.0)
            if sb_resp.status_code == 200:
                active_sandboxes = len(sb_resp.json())
        except Exception:
            active_sandboxes = -1

        storage_status = settings.STORAGE_PROFILE

        return RuntimeHealth(
            active_sandboxes=active_sandboxes,
            storage_status=storage_status,
            failed_tasks_24h=failed_tasks_24h,
        )

    def get_recent_activity(self, limit: int) -> list[RecentActivityItem]:
        """Return recent session events for the activity feed."""
        stmt = (
            select(  # type: ignore[reportCallIssue]
                Session.session_id,
                Session.title,
                Session.status,
                Session.type,
                Session.created_at,
                Agent.name,
                LLM.model,
                User.username,
            )
            .join(Agent, Session.agent_id == Agent.id)  # type: ignore[reportArgumentType]
            .join(LLM, Agent.llm_id == LLM.id, isouter=True)  # type: ignore[reportArgumentType]
            .join(User, Session.user_id == User.id)  # type: ignore[reportArgumentType]
            .order_by(col(Session.created_at).desc())
            .limit(limit)
        )

        return [
            RecentActivityItem(
                session_id=session_id,
                title=title or "",
                agent_name=agent_name,
                model_name=model_name or "",
                username=username,
                session_type=session_type,
                status=status,
                created_at=created_at.replace(tzinfo=UTC).isoformat(),
            )
            for (
                session_id,
                title,
                status,
                session_type,
                created_at,
                agent_name,
                model_name,
                username,
            ) in self.db.exec(stmt)
        ]

    def get_user_activity(self, days: int) -> list[DailyUserActivity]:
        """Return daily DAU/WAU/MAU for client sessions.

        WAU and MAU are rolling windows computed from an extended DAU query.
        """
        now = datetime.now(UTC)
        date_col = _date_bucket(Session.created_at).label("date")

        # Need extra history for rolling windows.
        extended_start = now - timedelta(days=max(days, 30) + 30)
        ext_stmt = (
            select(
                date_col,
                func.count(func.distinct(Session.user_id)),  # type: ignore[reportArgumentType, reportCallIssue]
            )
            .where(
                col(Session.type) == "client",
                col(Session.created_at) >= extended_start,
            )
            .group_by("date")  # type: ignore[reportArgumentType]
            .order_by("date")  # type: ignore[reportArgumentType]
        )

        extended_dau: dict[str, int] = {}
        for date_str, dau_count in self.db.exec(ext_stmt):
            extended_dau[date_str] = dau_count

        all_dates = sorted(extended_dau.keys())

        # Fill the requested range with zero-DAU days included.
        filled_dates: list[str] = []
        for i in range(days - 1, -1, -1):
            filled_dates.append((now - timedelta(days=i)).strftime("%Y-%m-%d"))

        result: list[DailyUserActivity] = []
        for date_str in filled_dates:
            dau = extended_dau.get(date_str, 0)
            idx = all_dates.index(date_str) if date_str in all_dates else -1

            wau = 0
            if idx >= 0:
                wau_dates = all_dates[max(0, idx - 6) : idx + 1]
                wau = max(extended_dau.get(d, 0) for d in wau_dates) if wau_dates else 0

            mau = 0
            if idx >= 0:
                mau_dates = all_dates[max(0, idx - 29) : idx + 1]
                mau = max(extended_dau.get(d, 0) for d in mau_dates) if mau_dates else 0

            result.append(DailyUserActivity(date=date_str, dau=dau, wau=wau, mau=mau))

        return result

    def get_user_growth(self, days: int) -> list[DailyUserGrowth]:
        """Return daily new user registration counts."""
        now = datetime.now(UTC)
        range_start = now - timedelta(days=days)
        date_col = _date_bucket(User.created_at).label("date")

        stmt = (
            select(date_col, func.count(User.id))  # type: ignore[reportArgumentType, reportCallIssue]
            .where(col(User.created_at) >= range_start)
            .group_by("date")  # type: ignore[reportArgumentType]
            .order_by("date")  # type: ignore[reportArgumentType]
        )

        raw: dict[str, int] = {}
        for date_str, count in self.db.exec(stmt):
            raw[date_str] = count

        filled = _fill_date_range(raw, days, lambda _d: 0)
        return [
            DailyUserGrowth(date=date_str, new_users=count)
            for date_str, count in filled.items()
        ]

    # ------------------------------------------------------------------
    # Agent-level analytics
    # ------------------------------------------------------------------

    def get_agent_overview(self, agent_id: int, days: int) -> AgentOverview:
        """Return KPI card summaries scoped to a single agent."""
        now = datetime.now(UTC)
        range_start = now - timedelta(days=days)

        sessions = self.db.exec(
            select(func.count(Session.id)).where(  # type: ignore[reportArgumentType, reportCallIssue]
                col(Session.agent_id) == agent_id,
                col(Session.created_at) >= range_start,
            )
        ).one()

        tasks = self.db.exec(
            select(func.count(ReactTask.id)).where(  # type: ignore[reportArgumentType, reportCallIssue]
                col(ReactTask.agent_id) == agent_id,
                col(ReactTask.created_at) >= range_start,
            )
        ).one()

        completed = self.db.exec(
            select(func.count(ReactTask.id)).where(  # type: ignore[reportArgumentType, reportCallIssue]
                col(ReactTask.agent_id) == agent_id,
                col(ReactTask.status) == "completed",
                col(ReactTask.created_at) >= range_start,
            )
        ).one()
        success_rate = round((completed / tasks * 100) if tasks > 0 else 0, 1)

        avg_tokens_result = self.db.exec(
            select(func.avg(ReactTask.total_tokens)).where(  # type: ignore[reportArgumentType, reportCallIssue]
                col(ReactTask.agent_id) == agent_id,
                col(ReactTask.created_at) >= range_start,
            )
        ).one()
        avg_tokens = round(float(avg_tokens_result or 0), 1)

        avg_iter_result = self.db.exec(
            select(func.avg(ReactTask.iteration)).where(  # type: ignore[reportArgumentType, reportCallIssue]
                col(ReactTask.agent_id) == agent_id,
                col(ReactTask.created_at) >= range_start,
            )
        ).one()
        avg_iterations = round(float(avg_iter_result or 0), 1)

        return AgentOverview(
            sessions=sessions,
            tasks=tasks,
            success_rate=success_rate,
            avg_tokens=avg_tokens,
            avg_iterations=avg_iterations,
        )

    def get_agent_session_trends(
        self, agent_id: int, days: int
    ) -> list[DailySessionCount]:
        """Return daily session counts by type scoped to a single agent."""
        now = datetime.now(UTC)
        range_start = now - timedelta(days=days)
        date_col = _date_bucket(Session.created_at).label("date")

        stmt = (
            select(date_col, Session.type, func.count(Session.id))  # type: ignore[reportArgumentType, reportCallIssue]
            .where(
                col(Session.agent_id) == agent_id,
                col(Session.created_at) >= range_start,
            )
            .group_by("date", Session.type)  # type: ignore[reportArgumentType]
            .order_by("date")  # type: ignore[reportArgumentType]
        )
        raw: dict[str, dict[str, int]] = {}
        for row in self.db.exec(stmt):
            date_str, session_type, count = row
            if date_str not in raw:
                raw[date_str] = {"client": 0, "studio_test": 0, "automation": 0}
            key = (
                session_type
                if session_type in ("client", "automation")
                else "studio_test"
            )
            raw[date_str][key] = count

        filled = _fill_date_range(
            raw,
            days,
            lambda d: {"client": 0, "studio_test": 0, "automation": 0},
        )
        return [
            DailySessionCount(
                date=date_str,
                client=counts["client"],
                studio_test=counts["studio_test"],
                automation=counts["automation"],
            )
            for date_str, counts in filled.items()
        ]

    def get_agent_task_stats(self, agent_id: int, days: int) -> TaskStats:
        """Return task status counts scoped to a single agent."""
        now = datetime.now(UTC)
        range_start = now - timedelta(days=days)

        status_counts: dict[str, int] = {}
        rows = self.db.exec(
            select(ReactTask.status, func.count(ReactTask.id))  # type: ignore[reportArgumentType, reportCallIssue]
            .where(
                col(ReactTask.agent_id) == agent_id,
                col(ReactTask.created_at) >= range_start,
            )
            .group_by(ReactTask.status)
        )
        for status, count in rows:
            status_counts[status] = count

        return TaskStats(
            completed=status_counts.get("completed", 0),
            failed=status_counts.get("failed", 0),
            cancelled=status_counts.get("cancelled", 0),
            running=status_counts.get("running", 0),
            pending=status_counts.get("pending", 0),
        )

    def get_agent_token_usage(self, agent_id: int, days: int) -> list[DailyTokenUsage]:
        """Return daily token usage scoped to a single agent."""
        now = datetime.now(UTC)
        range_start = now - timedelta(days=days)
        date_col = _date_bucket(ReactTask.created_at).label("date")

        stmt = (
            select(
                date_col,
                func.sum(ReactTask.total_prompt_tokens),  # type: ignore[reportArgumentType, reportCallIssue]
                func.sum(ReactTask.total_completion_tokens),  # type: ignore[reportArgumentType, reportCallIssue]
                func.sum(ReactTask.total_cached_input_tokens),  # type: ignore[reportArgumentType, reportCallIssue]
            )
            .where(
                col(ReactTask.agent_id) == agent_id,
                col(ReactTask.created_at) >= range_start,
            )
            .group_by("date")  # type: ignore[reportArgumentType]
            .order_by("date")  # type: ignore[reportArgumentType]
        )

        raw: dict[str, dict[str, int]] = {}
        for row in self.db.exec(stmt):
            prompt = row[1] or 0
            cached = row[3] or 0
            raw[row[0]] = {
                "uncached_input": max(prompt - cached, 0),
                "cached_input": cached,
                "output": row[2] or 0,
            }

        filled = _fill_date_range(
            raw,
            days,
            lambda d: {"uncached_input": 0, "cached_input": 0, "output": 0},
        )
        return [
            DailyTokenUsage(
                date=date_str,
                uncached_input=vals["uncached_input"],
                cached_input=vals["cached_input"],
                output=vals["output"],
            )
            for date_str, vals in filled.items()
        ]

    def get_agent_iteration_distribution(
        self, agent_id: int, days: int
    ) -> list[IterationBucket]:
        """Return task counts grouped by iteration ranges."""
        now = datetime.now(UTC)
        range_start = now - timedelta(days=days)

        iterations = self.db.exec(
            select(ReactTask.iteration).where(  # type: ignore[reportArgumentType, reportCallIssue]
                col(ReactTask.agent_id) == agent_id,
                col(ReactTask.created_at) >= range_start,
            )
        )

        buckets: dict[str, int] = {
            "0-5": 0,
            "6-10": 0,
            "11-20": 0,
            "21-30": 0,
            "31+": 0,
        }
        for iteration in iterations:
            if iteration <= 5:
                buckets["0-5"] += 1
            elif iteration <= 10:
                buckets["6-10"] += 1
            elif iteration <= 20:
                buckets["11-20"] += 1
            elif iteration <= 30:
                buckets["21-30"] += 1
            else:
                buckets["31+"] += 1

        return [IterationBucket(range=k, count=v) for k, v in buckets.items()]

    def get_agent_top_users(
        self, agent_id: int, days: int, limit: int
    ) -> list[AgentUserStats]:
        """Return top users for a specific agent by session count."""
        now = datetime.now(UTC)
        range_start = now - timedelta(days=days)

        stmt = (
            select(  # type: ignore[reportCallIssue]
                Session.user_id,
                User.username,
                func.count(Session.id),  # type: ignore[reportArgumentType, reportCallIssue]
            )
            .join(User, Session.user_id == User.id)  # type: ignore[reportArgumentType]
            .where(
                col(Session.agent_id) == agent_id,
                col(Session.created_at) >= range_start,
            )
            .group_by(Session.user_id, User.username)
            .order_by(func.count(Session.id).desc())  # type: ignore[reportArgumentType, reportCallIssue]
            .limit(limit)
        )

        user_sessions: dict[int, int] = {}
        user_names: dict[int, str] = {}
        for user_id, username, session_count in self.db.exec(stmt):
            user_sessions[user_id] = session_count
            user_names[user_id] = username

        if not user_sessions:
            return []

        user_ids = list(user_sessions.keys())

        task_stmt = (
            select(
                ReactTask.user_id,
                func.count(ReactTask.id),  # type: ignore[reportArgumentType, reportCallIssue]
                func.sum(ReactTask.total_tokens),  # type: ignore[reportArgumentType, reportCallIssue]
            )
            .where(
                col(ReactTask.agent_id) == agent_id,
                col(ReactTask.created_at) >= range_start,
                col(ReactTask.user_id).in_(user_ids),  # type: ignore[reportArgumentType]
            )
            .group_by(ReactTask.user_id)
        )
        user_tasks: dict[int, int] = {}
        user_tokens: dict[int, int] = {}
        for uid, task_count, token_sum in self.db.exec(task_stmt):
            user_tasks[uid] = task_count
            user_tokens[uid] = token_sum or 0

        last_active_stmt = (
            select(
                Session.user_id,
                func.max(Session.created_at),  # type: ignore[reportArgumentType, reportCallIssue]
            )
            .where(
                col(Session.agent_id) == agent_id,
                col(Session.user_id).in_(user_ids),  # type: ignore[reportArgumentType]
            )
            .group_by(Session.user_id)  # type: ignore[reportArgumentType]
        )
        user_last_active: dict[int, datetime] = {}
        for uid, last_at in self.db.exec(last_active_stmt):
            user_last_active[uid] = last_at

        result = []
        for uid in user_ids:
            result.append(
                AgentUserStats(
                    user_id=uid,
                    username=user_names[uid],
                    sessions=user_sessions[uid],
                    tasks=user_tasks.get(uid, 0),
                    total_tokens=user_tokens.get(uid, 0),
                    last_active=user_last_active[uid].replace(tzinfo=UTC).isoformat()
                    if uid in user_last_active
                    else "",
                )
            )
        return result

    def get_agent_releases(self, agent_id: int) -> list[AgentReleaseItem]:
        """Return release timeline for a specific agent."""
        stmt = (
            select(  # type: ignore[reportCallIssue]
                AgentRelease.version,
                AgentRelease.release_note,
                AgentRelease.change_summary_json,
                User.username,
                AgentRelease.created_at,
            )
            .join(  # type: ignore[reportArgumentType]
                User,
                AgentRelease.published_by_user_id == User.id,  # type: ignore[reportArgumentType]
            )
            .where(col(AgentRelease.agent_id) == agent_id)
            .order_by(col(AgentRelease.version).desc())
        )

        results: list[AgentReleaseItem] = []
        for version, note, summary_json, username, created_at in self.db.exec(stmt):
            try:
                summary = json.loads(summary_json) if summary_json else []
            except (json.JSONDecodeError, TypeError):
                summary = []
            if not isinstance(summary, list):
                summary = [str(summary)]
            results.append(
                AgentReleaseItem(
                    version=version,
                    release_note=note,
                    change_summary=summary,
                    published_by=username,
                    created_at=created_at.replace(tzinfo=UTC).isoformat(),
                )
            )
        return results

    def get_agent_client_usage(
        self, agent_id: int, days: int
    ) -> list[DailyClientUsage]:
        """Return daily client sessions and distinct users for this agent."""
        now = datetime.now(UTC)
        range_start = now - timedelta(days=days)
        date_col = _date_bucket(Session.created_at).label("date")

        session_stmt = (
            select(date_col, func.count(Session.id))  # type: ignore[reportArgumentType, reportCallIssue]
            .where(
                col(Session.agent_id) == agent_id,
                col(Session.type) == "client",
                col(Session.created_at) >= range_start,
            )
            .group_by("date")  # type: ignore[reportArgumentType]
            .order_by("date")  # type: ignore[reportArgumentType]
        )
        daily_sessions: dict[str, int] = {}
        for date_str, count in self.db.exec(session_stmt):
            daily_sessions[date_str] = count

        dau_stmt = (
            select(
                date_col,
                func.count(func.distinct(Session.user_id)),  # type: ignore[reportArgumentType, reportCallIssue]
            )
            .where(
                col(Session.agent_id) == agent_id,
                col(Session.type) == "client",
                col(Session.created_at) >= range_start,
            )
            .group_by("date")  # type: ignore[reportArgumentType]
            .order_by("date")  # type: ignore[reportArgumentType]
        )
        daily_dau: dict[str, int] = {}
        for date_str, count in self.db.exec(dau_stmt):
            daily_dau[date_str] = count

        merged: dict[str, dict[str, int]] = {}
        for d, s in daily_sessions.items():
            merged.setdefault(d, {"sessions": 0, "dau": 0})["sessions"] = s
        for d, u in daily_dau.items():
            merged.setdefault(d, {"sessions": 0, "dau": 0})["dau"] = u

        filled = _fill_date_range(
            merged,
            days,
            lambda d: {"sessions": 0, "dau": 0},
        )
        return [
            DailyClientUsage(
                date=date_str,
                sessions=vals["sessions"],
                dau=vals["dau"],
            )
            for date_str, vals in filled.items()
        ]

    def get_agent_channel_activity(
        self, agent_id: int, days: int
    ) -> list[ChannelActivityItem]:
        """Return per-channel activity stats for this agent."""
        now = datetime.now(UTC)
        range_start = now - timedelta(days=days)

        bindings = self.db.exec(
            select(AgentChannelBinding).where(
                col(AgentChannelBinding.agent_id) == agent_id
            )
        ).all()

        if not bindings:
            return []

        result: list[ChannelActivityItem] = []
        for binding in bindings:
            inbound_events = self.db.exec(
                select(func.count(ChannelEventLog.id)).where(  # type: ignore[reportArgumentType, reportCallIssue]
                    col(ChannelEventLog.channel_binding_id) == binding.id,
                    col(ChannelEventLog.direction) == "inbound",
                    col(ChannelEventLog.created_at) >= range_start,
                )
            ).one()

            active_sessions = self.db.exec(
                select(func.count(ChannelSession.id)).where(  # type: ignore[reportArgumentType, reportCallIssue]
                    col(ChannelSession.channel_binding_id) == binding.id,
                )
            ).one()

            last_event = self.db.exec(
                select(func.max(ChannelEventLog.created_at)).where(  # type: ignore[reportArgumentType, reportCallIssue]
                    col(ChannelEventLog.channel_binding_id) == binding.id,
                )
            ).one()

            result.append(
                ChannelActivityItem(
                    channel_key=binding.channel_key,
                    channel_name=binding.name,
                    inbound_events=inbound_events,
                    active_sessions=active_sessions,
                    last_event_at=last_event.replace(tzinfo=UTC).isoformat()
                    if last_event is not None
                    else "",
                )
            )
        return result
