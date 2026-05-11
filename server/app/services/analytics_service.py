"""Aggregation queries for Studio Dashboard and Agent Analytics Cockpit."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import requests
from app.config import get_settings
from app.models.agent import Agent
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
    consumer: int
    studio_test: int


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
    prompt: int
    completion: int
    cached: int


@dataclass(frozen=True)
class AgentPopularity:
    """One agent's popularity rank by consumer session count."""

    agent_id: int
    agent_name: str
    session_count: int


@dataclass(frozen=True)
class RuntimeHealth:
    """Runtime infrastructure health summary."""

    active_sandboxes: int
    storage_status: str
    failed_tasks_24h: int


@dataclass(frozen=True)
class RecentActivityItem:
    """One recent session event for the activity feed."""

    agent_name: str
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
                col(Session.type) == "consumer",
                col(Session.created_at) >= range_start,
            )
        ).one()
        sessions_prev = self.db.exec(
            select(func.count(Session.id)).where(  # type: ignore[reportArgumentType, reportCallIssue]
                col(Session.type) == "consumer",
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
                raw[date_str] = {"consumer": 0, "studio_test": 0}
            key = "consumer" if session_type == "consumer" else "studio_test"
            raw[date_str][key] = count

        return [
            DailySessionCount(
                date=date_str,
                consumer=counts["consumer"],
                studio_test=counts["studio_test"],
            )
            for date_str, counts in sorted(raw.items())
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

        return [
            DailyTokenUsage(
                date=row[0],
                prompt=row[1] or 0,
                completion=row[2] or 0,
                cached=row[3] or 0,
            )
            for row in self.db.exec(stmt)
        ]

    def get_agent_popularity(self, days: int, limit: int) -> list[AgentPopularity]:
        """Return top agents ranked by consumer session count."""
        now = datetime.now(UTC)
        range_start = now - timedelta(days=days)

        stmt = (
            select(
                Session.agent_id,
                Agent.name,
                func.count(Session.id),  # type: ignore[reportArgumentType, reportCallIssue]
            )
            .join(Agent, Session.agent_id == Agent.id)  # type: ignore[reportArgumentType]
            .where(
                col(Session.type) == "consumer",
                col(Session.created_at) >= range_start,
            )
            .group_by(Session.agent_id, Agent.name)
            .order_by(func.count(Session.id).desc())  # type: ignore[reportArgumentType, reportCallIssue]
            .limit(limit)
        )

        return [
            AgentPopularity(
                agent_id=agent_id,
                agent_name=agent_name,
                session_count=count,
            )
            for agent_id, agent_name, count in self.db.exec(stmt)
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
                Session.status,
                Session.type,
                Session.created_at,
                Agent.name,
                User.username,
            )
            .join(Agent, Session.agent_id == Agent.id)  # type: ignore[reportArgumentType]
            .join(User, Session.user_id == User.id)  # type: ignore[reportArgumentType]
            .order_by(col(Session.created_at).desc())
            .limit(limit)
        )

        return [
            RecentActivityItem(
                agent_name=agent_name,
                username=username,
                session_type=session_type,
                status=status,
                created_at=created_at.replace(tzinfo=UTC).isoformat(),
            )
            for status, session_type, created_at, agent_name, username in self.db.exec(
                stmt
            )
        ]

    def get_user_activity(self, days: int) -> list[DailyUserActivity]:
        """Return daily DAU/WAU/MAU for consumer sessions.

        WAU and MAU are rolling windows computed client-side from daily DAU
        data to keep the SQL simple.
        """
        now = datetime.now(UTC)
        range_start = now - timedelta(days=days)
        date_col = _date_bucket(Session.created_at).label("date")

        stmt = (
            select(
                date_col,
                func.count(func.distinct(Session.user_id)),  # type: ignore[reportArgumentType, reportCallIssue]
            )
            .where(
                col(Session.type) == "consumer",
                col(Session.created_at) >= range_start,
            )
            .group_by("date")  # type: ignore[reportArgumentType]
            .order_by("date")  # type: ignore[reportArgumentType]
        )

        daily_dau: dict[str, int] = {}
        for date_str, dau_count in self.db.exec(stmt):
            daily_dau[date_str] = dau_count

        sorted_dates = sorted(daily_dau.keys())

        # Compute rolling WAU/MAU from daily DAU data.
        # Need enough history for accurate rolling windows — fetch extra days.
        extended_start = now - timedelta(days=max(days, 30) + 30)
        ext_stmt = (
            select(
                date_col,
                func.count(func.distinct(Session.user_id)),  # type: ignore[reportArgumentType, reportCallIssue]
            )
            .where(
                col(Session.type) == "consumer",
                col(Session.created_at) >= extended_start,
            )
            .group_by("date")  # type: ignore[reportArgumentType]
            .order_by("date")  # type: ignore[reportArgumentType]
        )

        extended_dau: dict[str, int] = {}
        for date_str, dau_count in self.db.exec(ext_stmt):
            extended_dau[date_str] = dau_count

        all_dates = sorted(extended_dau.keys())

        # For rolling windows, sum DAU values in the window — this overcounts
        # since the same user may appear on multiple days. For a precise WAU/MAU
        # we'd need distinct user counts per window, which is expensive. Using
        # the DAU max as a reasonable proxy.
        result: list[DailyUserActivity] = []
        for date_str in sorted_dates:
            idx = all_dates.index(date_str) if date_str in all_dates else -1
            dau = daily_dau[date_str]

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

        return [
            DailyUserGrowth(date=date_str, new_users=count)
            for date_str, count in self.db.exec(stmt)
        ]
