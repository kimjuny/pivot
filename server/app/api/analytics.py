"""Analytics API endpoints for Studio Dashboard and Agent Cockpit."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.api.dependencies import get_db
from app.api.permissions import permissions
from app.security.permission_catalog import Permission
from app.services.analytics_service import (
    AnalyticsService,
    _parse_range,
)
from fastapi import APIRouter, Depends

if TYPE_CHECKING:
    from app.models.user import User
    from sqlmodel import Session as DBSession

router = APIRouter()


@router.get("/analytics/studio/overview")
def get_studio_overview(
    range: str = "30d",
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.STUDIO_ACCESS)),
) -> dict[str, Any]:
    """Return KPI card summaries for the studio dashboard."""
    days = _parse_range(range)
    service = AnalyticsService(db)
    overview = service.get_studio_overview(days)
    return {
        "agents_total": overview.agents_total,
        "agents_new": overview.agents_new,
        "sessions_total": overview.sessions_total,
        "sessions_delta": overview.sessions_delta,
        "users_total": overview.users_total,
        "users_new": overview.users_new,
        "tasks_total": overview.tasks_total,
        "tasks_daily_avg": overview.tasks_daily_avg,
        "success_rate": overview.success_rate,
        "success_rate_delta": overview.success_rate_delta,
    }


@router.get("/analytics/studio/session-trends")
def get_session_trends(
    range: str = "30d",
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.STUDIO_ACCESS)),
) -> list[dict[str, Any]]:
    """Return daily session counts by type for the selected range."""
    days = _parse_range(range)
    service = AnalyticsService(db)
    return [
        {
            "date": item.date,
            "consumer": item.consumer,
            "studio_test": item.studio_test,
        }
        for item in service.get_session_trends(days)
    ]


@router.get("/analytics/studio/task-stats")
def get_task_stats(
    range: str = "30d",
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.STUDIO_ACCESS)),
) -> dict[str, Any]:
    """Return task status counts for the donut chart."""
    days = _parse_range(range)
    service = AnalyticsService(db)
    stats = service.get_task_stats(days)
    return {
        "completed": stats.completed,
        "failed": stats.failed,
        "cancelled": stats.cancelled,
        "running": stats.running,
        "pending": stats.pending,
    }


@router.get("/analytics/studio/token-usage")
def get_token_usage(
    range: str = "30d",
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.STUDIO_ACCESS)),
) -> list[dict[str, Any]]:
    """Return daily token usage broken down by prompt/completion/cached."""
    days = _parse_range(range)
    service = AnalyticsService(db)
    return [
        {
            "date": item.date,
            "uncached_input": item.uncached_input,
            "cached_input": item.cached_input,
            "output": item.output,
        }
        for item in service.get_token_usage(days)
    ]


@router.get("/analytics/studio/agent-popularity")
def get_agent_popularity(
    range: str = "30d",
    limit: int = 10,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.STUDIO_ACCESS)),
) -> list[dict[str, Any]]:
    """Return top agents ranked by consumer session count."""
    days = _parse_range(range)
    service = AnalyticsService(db)
    return [
        {
            "agent_id": item.agent_id,
            "agent_name": item.agent_name,
            "model_name": item.model_name,
            "session_count": item.session_count,
        }
        for item in service.get_agent_popularity(days, limit)
    ]


@router.get("/analytics/studio/runtime-health")
async def get_runtime_health(
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.STUDIO_ACCESS)),
) -> dict[str, Any]:
    """Return runtime infrastructure health summary."""
    service = AnalyticsService(db)
    health = await service.get_runtime_health()
    return {
        "active_sandboxes": health.active_sandboxes,
        "storage_status": health.storage_status,
        "failed_tasks_24h": health.failed_tasks_24h,
    }


@router.get("/analytics/studio/recent-activity")
def get_recent_activity(
    limit: int = 5,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.STUDIO_ACCESS)),
) -> list[dict[str, Any]]:
    """Return recent session events for the activity feed."""
    service = AnalyticsService(db)
    return [
        {
            "session_id": item.session_id,
            "agent_name": item.agent_name,
            "model_name": item.model_name,
            "username": item.username,
            "session_type": item.session_type,
            "status": item.status,
            "created_at": item.created_at,
        }
        for item in service.get_recent_activity(limit)
    ]


@router.get("/analytics/studio/user-activity")
def get_user_activity(
    range: str = "30d",
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.STUDIO_ACCESS)),
) -> list[dict[str, Any]]:
    """Return daily DAU/WAU/MAU for consumer sessions."""
    days = _parse_range(range)
    service = AnalyticsService(db)
    return [
        {
            "date": item.date,
            "dau": item.dau,
            "wau": item.wau,
            "mau": item.mau,
        }
        for item in service.get_user_activity(days)
    ]


@router.get("/analytics/studio/user-growth")
def get_user_growth(
    range: str = "30d",
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.STUDIO_ACCESS)),
) -> list[dict[str, Any]]:
    """Return daily new user registration counts."""
    days = _parse_range(range)
    service = AnalyticsService(db)
    return [
        {
            "date": item.date,
            "new_users": item.new_users,
        }
        for item in service.get_user_growth(days)
    ]


# ---------------------------------------------------------------------------
# Agent-level analytics
# ---------------------------------------------------------------------------


@router.get("/analytics/agents/{agent_id}/overview")
def get_agent_overview(
    agent_id: int,
    range: str = "30d",
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.AGENTS_MANAGE)),
) -> dict[str, Any]:
    """Return KPI card summaries scoped to a single agent."""
    days = _parse_range(range)
    service = AnalyticsService(db)
    overview = service.get_agent_overview(agent_id, days)
    return {
        "sessions": overview.sessions,
        "tasks": overview.tasks,
        "success_rate": overview.success_rate,
        "avg_tokens": overview.avg_tokens,
        "avg_iterations": overview.avg_iterations,
    }


@router.get("/analytics/agents/{agent_id}/session-trends")
def get_agent_session_trends(
    agent_id: int,
    range: str = "30d",
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.AGENTS_MANAGE)),
) -> list[dict[str, Any]]:
    """Return daily session counts by type scoped to a single agent."""
    days = _parse_range(range)
    service = AnalyticsService(db)
    return [
        {
            "date": item.date,
            "consumer": item.consumer,
            "studio_test": item.studio_test,
        }
        for item in service.get_agent_session_trends(agent_id, days)
    ]


@router.get("/analytics/agents/{agent_id}/task-stats")
def get_agent_task_stats(
    agent_id: int,
    range: str = "30d",
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.AGENTS_MANAGE)),
) -> dict[str, Any]:
    """Return task status counts scoped to a single agent."""
    days = _parse_range(range)
    service = AnalyticsService(db)
    stats = service.get_agent_task_stats(agent_id, days)
    return {
        "completed": stats.completed,
        "failed": stats.failed,
        "cancelled": stats.cancelled,
        "running": stats.running,
        "pending": stats.pending,
    }


@router.get("/analytics/agents/{agent_id}/token-usage")
def get_agent_token_usage(
    agent_id: int,
    range: str = "30d",
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.AGENTS_MANAGE)),
) -> list[dict[str, Any]]:
    """Return daily token usage scoped to a single agent."""
    days = _parse_range(range)
    service = AnalyticsService(db)
    return [
        {
            "date": item.date,
            "uncached_input": item.uncached_input,
            "cached_input": item.cached_input,
            "output": item.output,
        }
        for item in service.get_agent_token_usage(agent_id, days)
    ]


@router.get("/analytics/agents/{agent_id}/iteration-distribution")
def get_agent_iteration_distribution(
    agent_id: int,
    range: str = "30d",
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.AGENTS_MANAGE)),
) -> list[dict[str, Any]]:
    """Return task counts grouped by iteration ranges."""
    days = _parse_range(range)
    service = AnalyticsService(db)
    return [
        {"range": item.range, "count": item.count}
        for item in service.get_agent_iteration_distribution(agent_id, days)
    ]


@router.get("/analytics/agents/{agent_id}/top-users")
def get_agent_top_users(
    agent_id: int,
    range: str = "30d",
    limit: int = 20,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.AGENTS_MANAGE)),
) -> list[dict[str, Any]]:
    """Return top users for a specific agent by session count."""
    days = _parse_range(range)
    service = AnalyticsService(db)
    return [
        {
            "user_id": item.user_id,
            "username": item.username,
            "sessions": item.sessions,
            "tasks": item.tasks,
            "total_tokens": item.total_tokens,
            "last_active": item.last_active,
        }
        for item in service.get_agent_top_users(agent_id, days, limit)
    ]


@router.get("/analytics/agents/{agent_id}/releases")
def get_agent_releases(
    agent_id: int,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.AGENTS_MANAGE)),
) -> list[dict[str, Any]]:
    """Return release timeline for a specific agent."""
    service = AnalyticsService(db)
    return [
        {
            "version": item.version,
            "release_note": item.release_note,
            "change_summary": item.change_summary,
            "published_by": item.published_by,
            "created_at": item.created_at,
        }
        for item in service.get_agent_releases(agent_id)
    ]


@router.get("/analytics/agents/{agent_id}/consumer-usage")
def get_agent_consumer_usage(
    agent_id: int,
    range: str = "30d",
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.AGENTS_MANAGE)),
) -> list[dict[str, Any]]:
    """Return daily consumer sessions and distinct users for this agent."""
    days = _parse_range(range)
    service = AnalyticsService(db)
    return [
        {
            "date": item.date,
            "sessions": item.sessions,
            "dau": item.dau,
        }
        for item in service.get_agent_consumer_usage(agent_id, days)
    ]


@router.get("/analytics/agents/{agent_id}/channel-activity")
def get_agent_channel_activity(
    agent_id: int,
    range: str = "30d",
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.AGENTS_MANAGE)),
) -> list[dict[str, Any]]:
    """Return per-channel activity stats for this agent."""
    days = _parse_range(range)
    service = AnalyticsService(db)
    return [
        {
            "channel_key": item.channel_key,
            "channel_name": item.channel_name,
            "inbound_events": item.inbound_events,
            "active_sessions": item.active_sessions,
            "last_event_at": item.last_event_at,
        }
        for item in service.get_agent_channel_activity(agent_id, days)
    ]
