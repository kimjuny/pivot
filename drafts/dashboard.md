# Dashboard & Agent Analytics

## Problem

After agents are built and published, administrators lack a consolidated view to answer critical questions:

- Is the platform healthy? Are tasks succeeding or failing?
- How much are we spending on tokens? Which agents consume the most?
- Who is using the platform? Are users returning? How active are they?
- Is a specific agent performing well? Where does it fail?
- Which agents are popular among consumers? Which are idle?

The Studio Dashboard currently shows an "Under Construction" placeholder. The Agent detail page has no analytics tab. There is no visibility into client-side user engagement.

This implementation also serves a second purpose: **unifying the user dimension across all tables**. Historically, models like Session, ReactTask, FileAsset store `user` as a username string instead of a proper foreign key. This migration cleans up that technical debt and establishes a clean foundation for analytics queries.

## Design Principles

1. **Two-level analytics**: Studio-level (global) for platform health, Agent-level (per-agent) for individual performance.
2. **Data from existing models**: No new tables needed for analytics. All analytics derive from Session, ReactTask, ReactRecursion, AgentRelease, ChannelEventLog, and User.
3. **Service-layer aggregation**: All statistical queries go through a new `AnalyticsService` in the service layer. API routes never query raw data directly.
4. **shadcn Charts**: Use shadcn/ui Charts (Recharts underneath) for consistency with the existing UI system. Chart component already installed at `web/src/components/ui/chart.tsx`.
5. **Client-side user dimension**: First-class analytics for consumer user activity, retention, and growth — not just system-level metrics.
6. **Time-range aware**: All trend charts support a time-range selector (7d / 30d / 90d). Default to 30d.
7. **Load on demand**: Analytics data is fetched when the page loads. No real-time push in the initial version.
8. **Enterprise-scale indexing**: Design indexes upfront for growing data volumes. The platform is an enterprise Agent Framework — consumer usage data grows continuously.
9. **Summary → Detail navigation**: Dashboard charts show aggregated summaries. Each chart area can have a "See more" link pointing to a dedicated detail page (e.g. "Tool and Sandbox Logs", "Release Audit", "Usage and Cost") for drill-down. Detail pages are not implemented in this phase.

## User FK Migration (Phase 0)

### Background

6 core tables store `user` as a username string (`str`). This causes:

- Ownership checks require string comparison instead of efficient integer FK joins.
- Services like `project_service` and `access_service` do reverse lookups (`select(User).where(User.username == model.user)`) to resolve the FK.
- Filesystem paths use `users/{username}/...` which couples storage layout to a display attribute.
- User dimension analytics cannot efficiently JOIN on user attributes (role, status, email).

### Decision: Keep User.id as int auto-increment

`User.id` remains an auto-increment integer primary key. This is the standard pattern in virtually all modern systems (GitHub, Slack, Stripe): an internal `id` for FK references + a unique `username` for human identification.

Why both are necessary:

| Scenario | Using username as FK | Using user_id as FK |
|----------|---------------------|---------------------|
| User renames themselves | Cascade updates across all tables | No impact |
| JOIN performance | String comparison, slow | Integer comparison, 10-100x faster |
| Index size | VARCHAR index, large | INT index, 4 bytes |
| Coupling | Internal references bound to display attribute | Fully decoupled |

If a non-enumerable external identifier is needed in the future, add a `uid: str` UUID field to User (same pattern as Session's `session_id`), but do not change `User.id` itself.

### Migration Scope

#### Core tables — replace `user: str` with `user_id: int FK`

| Table | Current Field | New Field | Notes |
|-------|--------------|-----------|-------|
| `Session` | `user: str` (indexed) | `user_id: int = Field(foreign_key="user.id", index=True)` | Ownership checks in session.py, react.py |
| `ReactTask` | `user: str` (indexed) | `user_id: int = Field(foreign_key="user.id", index=True)` | Runtime ownership, analytics |
| `FileAsset` | `user: str` (indexed) | `user_id: int = Field(foreign_key="user.id", index=True)` | Upload ownership |
| `Project` | `user: str` (indexed) | `user_id: int = Field(foreign_key="user.id", index=True)` | Project ownership |
| `Workspace` | `user: str` (indexed) | `user_id: int = Field(foreign_key="user.id", index=True)` | Workspace ownership |
| `TaskAttachment` | `user: str` (indexed) | `user_id: int = Field(foreign_key="user.id", index=True)` | Attachment ownership |

#### Secondary tables — replace username-like string fields with user_id FK

| Table | Current Field | New Field | Notes |
|-------|--------------|-----------|-------|
| `MediaGenerationUsageLog` | `username: str` (indexed) | `user_id: int = Field(foreign_key="user.id", index=True)` | Usage tracking |
| `ExtensionInstallation` | `installed_by: str \| None` | `installed_by_user_id: int \| None = Field(foreign_key="user.id")` | Install audit |
| `ExtensionPendingUpgrade` | `created_by: str \| None` | `created_by_user_id: int \| None = Field(foreign_key="user.id")` | Upgrade audit |
| `AgentSavedDraft` | `saved_by: str \| None` | `saved_by_user_id: int \| None = Field(foreign_key="user.id")` | Draft audit |
| `AgentTestSnapshot` | `created_by: str \| None` | `created_by_user_id: int \| None = Field(foreign_key="user.id")` | Test audit |
| `ExternalIdentityBinding` | `workspace_owner: str` | `workspace_owner_user_id: int = Field(foreign_key="user.id")` | Channel ownership |

#### Filesystem path migration

Change storage paths from `users/{username}/...` to `users/{user_id}/...`:

- `file_service.py`: `_object_key_original()`, `_object_key_markdown()` — `users/{user_id}/uploads/...`
- `workspace_service.py`: `_user_tools_dir()` — `users/{user_id}/tools/`
- `workspace_service.py`: `ensure_agent_workspace()` — `users/{user_id}/agents/{agent_id}/`
- All path-building helpers that currently use `workspace.user` or `file_asset.user` must resolve user_id instead.

#### Services requiring changes (12 files)

| Service | Impact | Key Changes |
|---------|--------|-------------|
| `session_service.py` | HIGH | create_session receives user_id; ownership checks use user_id |
| `react_runtime_service.py` | MEDIUM | Receives user_id instead of username |
| `react_context_service.py` | MEDIUM | Ownership check changes |
| `react_task_supervisor.py` | MEDIUM | Task creation uses user_id |
| `file_service.py` | HIGH | Path building uses user_id; upload/delete queries use user_id |
| `workspace_service.py` | HIGH | Path building uses user_id; workspace creation uses user_id |
| `workspace_file_service.py` | LOW-MEDIUM | Workspace creation uses user_id |
| `project_service.py` | HIGH | Eliminates reverse User lookup; uses user_id directly |
| `task_attachment_service.py` | MEDIUM | Creation and queries use user_id |
| `access_service.py` | HIGH | Eliminates `_workspace_owner_user_id()` reverse lookup |
| `surface_session_service.py` | MEDIUM | Ownership checks use user_id |
| `media_generation_service.py` | MEDIUM | Usage log creation uses user_id |

#### API routes requiring changes (7 files)

| Route File | Key Changes |
|-----------|-------------|
| `api/session.py` | All ownership checks: `session.user_id != current_user.id` |
| `api/react.py` | Ownership gates: `task.user_id != current_user.id`, `session.user_id != current_user.id` |
| `api/files.py` | Upload/delete with user_id |
| `api/projects.py` | Pass user_id to services |
| `api/operations.py` | Serialize `user_id` instead of `user` in responses |
| `api/extensions.py` | `installed_by_user_id = current_user.id` |
| `api/media_generation.py` | Usage log with user_id |

#### Schema changes (3 files)

| Schema File | Changes |
|------------|---------|
| `schemas/session.py` | `SessionCreate.user_id: int`, `SessionResponse.user_id: int` |
| `schemas/react.py` | `ReactChatRequest.user_id: int`, `ReactStreamEvent.user_id: int` |
| `schemas/schemas.py` | `AgentSavedDraftResponse.saved_by_user_id: int \| None` |

#### Orchestration changes (1 file)

| File | Changes |
|------|---------|
| `orchestration/react/engine.py` | Pass user_id to sandbox/workspace resolution |

### Index Strategy for Analytics

Add composite indexes optimized for analytics query patterns:

```python
# Session — agent + time range queries
Index("ix_session_agent_created", Session.agent_id, Session.created_at)
Index("ix_session_user_created", Session.user_id, Session.created_at)
Index("ix_session_type_created", Session.type, Session.created_at)

# ReactTask — agent + time + status queries
Index("ix_reacttask_agent_created", ReactTask.agent_id, ReactTask.created_at)
Index("ix_reacttask_user_created", ReactTask.user_id, ReactTask.created_at)
Index("ix_reacttask_status_created", ReactTask.status, ReactTask.created_at)

# ReactTask — agent + status composite
Index("ix_reacttask_agent_status", ReactTask.agent_id, ReactTask.status)

# FileAsset — user + time
Index("ix_fileasset_user_created", FileAsset.user_id, FileAsset.created_at)
```

These indexes support the most common analytics query patterns: filtering by agent, filtering by user, time-range slicing, and status breakdowns.

---

## Page 1: Studio Dashboard (`/studio/dashboard`)

**Permission**: `studio.access`

**Purpose**: Platform-level overview for admins and builders to monitor health, usage, cost, and user engagement at a glance.

### Layout

```
┌─────────────────────────────────────────────────────────────────┐
│ Studio Dashboard                                [7d|30d|90d]    │
├──────────┬──────────┬──────────┬──────────┬─────────────────────┤
│ Agents   │ Sessions │ Users    │ Tasks    │ Success Rate        │
│   12     │   342    │    8     │  1,204   │   94.2%             │
│ (+2 new) │ (+47 7d) │ (+1 new) │(+210 7d) │                     │
├──────────┴──────────┴──────────┴──────────┴─────────────────────┤
│                                                                  │
│  ┌──────────────────────────┐  ┌──────────────────────────────┐  │
│  │ Session Activity          │  │ Task Status Breakdown        │  │
│  │ (Area Chart)              │  │ (Donut Chart)                │  │
│  │ X: date  Y: session count │  │ completed / failed /         │  │
│  │ Stacked by type       [→] │  │ cancelled / pending      [→] │  │
│  └──────────────────────────┘  └──────────────────────────────┘  │
│                                                                  │
│  ┌──────────────────────────┐  ┌──────────────────────────────┐  │
│  │ Token Usage Trend         │  │ Agent Popularity             │  │
│  │ (Stacked Bar Chart)       │  │ (Horizontal Bar Chart)       │  │
│  │ X: date                   │  │ Top 10 agents by             │  │
│  │ Y: prompt + completion [→]│  │ consumer session count   [→] │  │
│  └──────────────────────────┘  └──────────────────────────────┘  │
│                                                                  │
│  ┌──────────────────────────┐  ┌──────────────────────────────┐  │
│  │ User Activity             │  │ New User Trend               │  │
│  │ (Line Chart)              │  │ (Bar Chart)                  │  │
│  │ DAU / WAU / MAU           │  │ User.created_at by day       │  │
│  │ toggle lines              │  │                              │  │
│  └──────────────────────────┘  └──────────────────────────────┘  │
│                                                                  │
│  ┌──────────────────────────┐  ┌──────────────────────────────┐  │
│  │ Runtime Health            │  │ Recent Activity              │  │
│  │ Active Sandboxes: 3       │  │ (Feed List)                  │  │
│  │ Storage: local_fs OK      │  │ Latest sessions/events       │  │
│  │ Failed Tasks (24h): 7 [→] │  │ with agent name + user   [→] │  │
│  └──────────────────────────┘  └──────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘

[→] = "See more" link to dedicated detail page (not implemented in this phase)
```

### Modules

#### 1. KPI Cards

Row of 5 stat cards at the top.

| Card | Data Source | Calculation | Subtitle |
|------|------------|-------------|----------|
| Agents | Agent table | Total count | "+N new" in selected range |
| Sessions | Session table (type=consumer) | Count in range | Daily average |
| Users | User table | Total active users | "+N new" in selected range |
| Tasks | ReactTask table | Count in range | Daily average |
| Success Rate | ReactTask table | completed / total × 100% | Trend vs previous period |

#### 2. Session Activity (Area Chart)

- **X-axis**: Date (daily buckets)
- **Y-axis**: Session count
- **Stacked**: `consumer` vs `studio_test`
- **Interaction**: Hover shows tooltip with exact counts
- **See more**: Links to future Session History detail page

#### 3. Task Status Breakdown (Donut Chart)

- **Segments**: completed, failed, cancelled, running, pending
- **Center label**: Total task count
- **Interaction**: Click segment filters to that status
- **See more**: Links to future Tool/Sandbox Logs page

#### 4. Token Usage Trend (Stacked Bar Chart)

- **X-axis**: Date (daily buckets)
- **Y-axis**: Token count
- **Stacked**: `prompt_tokens` + `completion_tokens` + `cached_input_tokens`
- **Derived from**: ReactTask.total_prompt_tokens, ReactTask.total_completion_tokens, ReactTask.total_cached_input_tokens
- **See more**: Links to future Usage/Cost page

#### 5. Agent Popularity (Horizontal Bar Chart)

- **Top 10** agents ranked by consumer session count in range
- **Bar label**: Agent name
- **Bar value**: Session count
- **See more**: Links to future agent analytics detail

#### 6. User Activity (Line Chart)

- **X-axis**: Date (daily buckets)
- **Lines**:
  - DAU: Distinct users with at least 1 consumer session on that day
  - WAU: 7-day rolling distinct users
  - MAU: 30-day rolling distinct users
- **Toggle**: Show/hide each line via legend click

#### 7. New User Trend (Bar Chart)

- **X-axis**: Date (daily buckets)
- **Y-axis**: Count of new users registered that day (User.created_at)
- **Derived from**: User table

#### 8. Runtime Health (Status Card)

- Active sandboxes count (from SandboxManager)
- Storage backend status (from existing `/api/system/storage-status`)
- Failed tasks in last 24h count
- **See more**: Links to future Tool/Sandbox Logs page

#### 9. Recent Activity (Feed List)

- Last 20 events sorted by created_at desc
- Each item shows: agent name, user, session type, status, relative time
- Derived from Session table
- **See more**: Links to future Session History page

---

## Page 2: Agent Analytics Tab (`/studio/agents/:agentId`)

**Permission**: `agents.manage`

**Purpose**: Per-agent cockpit showing how a single agent is performing, who is using it, and where it fails.

**Integration**: The Analytics tab is a regular tab in the existing AgentDetail tab system (same level as tool/skill/function tabs). When a user opens an Agent detail page and no other tabs are open, the Analytics tab is **auto-opened** as the default view, replacing the current "No Tab Open" empty state.

**Tab type**: `'analytics'` (added to agentTabStore alongside `'tool'`, `'skill'`, `'function'`)

**Auto-open behavior**: In `AgentDetail.tsx`, when `tabs.length === 0` and the agent data has loaded, call `openTab({ type: 'analytics', ... })` automatically.

### Layout

```
┌─────────────────────────────────────────────────────────────────┐
│ Agent: My Agent  [Analytics] [Tool: web_search] [Skill: ...]   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────┬──────────┬──────────┬──────────┬─────────────────┐│
│  │ Sessions │ Tasks    │ Success  │ Avg Token│ Avg Iterations  ││
│  │    89    │   312    │  94.2%   │  2,340   │     4.7         ││
│  └──────────┴──────────┴──────────┴──────────┴─────────────────┘│
│                                                                  │
│  ┌──────────────────────────┐  ┌──────────────────────────────┐  │
│  │ Session Timeline          │  │ Task Status Breakdown        │  │
│  │ (Area Chart)              │  │ (Donut Chart)                │  │
│  │ X: date  Y: session count │  │ Same logic as dashboard      │  │
│  │ Filtered to this agent    │  │ but scoped to this agent     │  │
│  └──────────────────────────┘  └──────────────────────────────┘  │
│                                                                  │
│  ┌──────────────────────────┐  ┌──────────────────────────────┐  │
│  │ Token Consumption         │  │ Iteration Distribution       │  │
│  │ (Area Chart)              │  │ (Bar Chart)                  │  │
│  │ Prompt vs Completion      │  │ X: iteration range (0-5,     │  │
│  │ over time                 │  │   6-10, 11-20, 21+)          │  │
│  └──────────────────────────┘  └──────────────────────────────┘  │
│                                                                  │
│  ┌──────────────────────────┐  ┌──────────────────────────────┐  │
│  │ Consumer Usage            │  │ Channel Activity             │  │
│  │ (Line Chart)              │  │ (Stats Cards)                │  │
│  │ DAU for this agent        │  │ Per-channel session/event    │  │
│  │ + consumer message trend  │  │ counts for this agent        │  │
│  └──────────────────────────┘  └──────────────────────────────┘  │
│                                                                  │
│  ┌──────────────────────────┐  ┌──────────────────────────────┐  │
│  │ Top Users (Table)         │  │ Release Timeline             │  │
│  │ User | Sessions | Tokens  │  │ (Vertical Timeline)          │  │
│  │      | Last Active        │  │ Version history with dates   │  │
│  │ Sorted by session count   │  │ and release notes            │  │
│  └──────────────────────────┘  └──────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### Modules

#### 1. KPI Cards

| Card | Data Source | Calculation |
|------|------------|-------------|
| Sessions | Session (agent_id scoped) | Count in range |
| Tasks | ReactTask (agent_id scoped) | Count in range |
| Success Rate | ReactTask | completed / total × 100% |
| Avg Tokens | ReactTask | mean(total_tokens) |
| Avg Iterations | ReactTask | mean(iteration) |

#### 2. Session Timeline (Area Chart)

- Same as dashboard Session Activity, but filtered to `agent_id`
- Stacked by type: `consumer` vs `studio_test`

#### 3. Task Status Breakdown (Donut Chart)

- Same as dashboard, scoped to this agent

#### 4. Token Consumption (Area Chart)

- **X-axis**: Date (daily)
- **Y-axis**: Token count
- **Two areas**: prompt_tokens and completion_tokens
- Scoped to this agent

#### 5. Iteration Distribution (Bar Chart)

- **X-axis**: Iteration ranges (0-5, 6-10, 11-20, 21-30, 31+)
- **Y-axis**: Task count
- Shows how many ReAct cycles tasks typically need

#### 6. Consumer Usage (Line Chart)

- **X-axis**: Date (daily)
- **Lines**:
  - Consumer session count
  - Distinct consumer users (DAU for this agent)
- Helps understand per-agent user engagement

#### 7. Channel Activity (Stats Cards)

- Per-channel breakdown for this agent
- Each channel shows: inbound events, active sessions, last event time
- Only shown if agent has channel bindings

#### 8. Top Users (Table)

- **Columns**: Username, Sessions, Tasks, Total Tokens, Last Active
- **Sorted by**: Session count desc
- **Pagination**: Client-side, 10 per page
- **Derived from**: Session + ReactTask grouped by `user_id`, JOIN User for username display

#### 9. Release Timeline (Vertical Timeline)

- Chronological list of AgentRelease entries
- Each entry shows: version, release_note, published_by, created_at
- change_summary_json rendered as bullet points

---

## Data Sources

All analytics derive from existing models (after user_id migration). No new tables.

### Primary Tables

| Table | Key Fields for Analytics |
|-------|------------------------|
| `Session` | agent_id, user_id, type, status, created_at, updated_at |
| `ReactTask` | task_id, session_id, agent_id, user_id, status, iteration, total_prompt_tokens, total_completion_tokens, total_tokens, total_cached_input_tokens, created_at |
| `ReactRecursion` | react_task_id, action_type, status, prompt_tokens, completion_tokens, total_tokens, created_at |
| `Agent` | id, name, client_state, created_at |
| `AgentRelease` | agent_id, version, release_note, change_summary_json, published_by, created_at |
| `User` | id, username, status, created_at |
| `ChannelEventLog` | channel_binding_id, direction, event_type, created_at |
| `AgentChannelBinding` | agent_id, channel_key, status |

### Aggregation Strategy

All time-series aggregations use **daily buckets** (group by DATE(created_at)).

For SQLite: `strftime('%Y-%m-%d', created_at)`
For PostgreSQL: `DATE(created_at)`

The AnalyticsService should abstract this via a helper method so the SQL dialect difference is encapsulated in one place.

---

## API Design

### New Router: `server/app/api/analytics.py`

**Permission**: All endpoints require `studio.access`.

```
GET /api/analytics/studio/overview?range=30d
  → KPI counts (agents, sessions, users, tasks, success_rate)
  → Period comparison deltas

GET /api/analytics/studio/session-trends?range=30d
  → Array of { date, consumer, studio_test }

GET /api/analytics/studio/task-stats?range=30d
  → { completed, failed, cancelled, running, pending }
  → Array of { date, completed, failed, cancelled } for trend

GET /api/analytics/studio/token-usage?range=30d
  → Array of { date, prompt, completion, cached }

GET /api/analytics/studio/agent-popularity?range=30d&limit=10
  → Array of { agent_id, agent_name, session_count }
  → Sorted by session_count desc

GET /api/analytics/studio/user-activity?range=30d
  → Array of { date, dau, wau, mau }

GET /api/analytics/studio/user-growth?range=30d
  → Array of { date, new_users }

GET /api/analytics/studio/runtime-health
  → { active_sandboxes, storage_status, failed_tasks_24h }

GET /api/analytics/studio/recent-activity?limit=20
  → Array of { agent_name, username, session_type, status, created_at }

GET /api/analytics/agents/{agent_id}/overview?range=30d
  → Agent-scoped KPIs (sessions, tasks, success_rate, avg_tokens, avg_iterations)

GET /api/analytics/agents/{agent_id}/session-trends?range=30d
  → Array of { date, consumer, studio_test }

GET /api/analytics/agents/{agent_id}/token-usage?range=30d
  → Array of { date, prompt, completion }

GET /api/analytics/agents/{agent_id}/iteration-distribution?range=30d
  → Array of { range, count }

GET /api/analytics/agents/{agent_id}/consumer-usage?range=30d
  → Array of { date, sessions, dau }

GET /api/analytics/agents/{agent_id}/channel-activity?range=30d
  → Array of { channel_key, inbound_events, active_sessions, last_event_at }

GET /api/analytics/agents/{agent_id}/top-users?range=30d&limit=20
  → Array of { user_id, username, sessions, tasks, total_tokens, last_active }

GET /api/analytics/agents/{agent_id}/releases
  → Array of { version, release_note, change_summary, published_by, created_at }
```

### Query Parameter: `range`

- `7d` — last 7 days
- `30d` — last 30 days (default)
- `90d` — last 90 days

Implemented as `datetime.now(timezone.utc) - timedelta(days=N)`.

---

## Service Layer

### New Service: `server/app/services/analytics_service.py`

Single service class receiving a `DBSession` via constructor, same pattern as all other services.

```python
class AnalyticsService:
    def __init__(self, db: DBSession): ...

    # Studio-level
    def get_studio_overview(self, days: int) -> StudioOverview: ...
    def get_session_trends(self, days: int) -> list[DailySessionCount]: ...
    def get_task_stats(self, days: int) -> TaskStats: ...
    def get_token_usage(self, days: int) -> list[DailyTokenUsage]: ...
    def get_agent_popularity(self, days: int, limit: int) -> list[AgentPopularity]: ...
    def get_user_activity(self, days: int) -> list[DailyUserActivity]: ...
    def get_user_growth(self, days: int) -> list[DailyUserGrowth]: ...
    def get_runtime_health(self) -> RuntimeHealth: ...
    def get_recent_activity(self, limit: int) -> list[RecentActivityItem]: ...

    # Agent-level
    def get_agent_overview(self, agent_id: int, days: int) -> AgentOverview: ...
    def get_agent_session_trends(self, agent_id: int, days: int) -> list[DailySessionCount]: ...
    def get_agent_token_usage(self, agent_id: int, days: int) -> list[DailyTokenUsage]: ...
    def get_agent_iteration_distribution(self, agent_id: int, days: int) -> list[IterationBucket]: ...
    def get_agent_consumer_usage(self, agent_id: int, days: int) -> list[DailyConsumerUsage]: ...
    def get_agent_channel_activity(self, agent_id: int, days: int) -> list[ChannelActivityItem]: ...
    def get_agent_top_users(self, agent_id: int, days: int, limit: int) -> list[AgentUserStats]: ...
    def get_agent_releases(self, agent_id: int) -> list[AgentReleaseItem]: ...
```

### Database Dialect Abstraction

```python
def _date_trunc(self, column) -> str:
    """Return SQL expression for grouping by date, dialect-aware."""
    # SQLite: strftime('%Y-%m-%d', column)
    # PostgreSQL: DATE(column)
    # Selected via config.DATABASE_URL check
```

---

## Frontend Architecture

### New Components

```
web/src/components/analytics/
  KpiCard.tsx                 → Stat card with value, label, subtitle, trend indicator
  DateRangeSelector.tsx       → 7d / 30d / 90d toggle button group
  SessionTrendChart.tsx       → Area chart for session activity
  TaskStatusChart.tsx         → Donut chart for task status breakdown
  TokenUsageChart.tsx         → Stacked bar chart for token usage
  AgentPopularityChart.tsx    → Horizontal bar chart for top agents
  UserActivityChart.tsx       → Line chart for DAU/WAU/MAU
  UserGrowthChart.tsx         → Bar chart for new user registrations
  RuntimeHealthCard.tsx       → Status card for sandbox/storage/failures
  ActivityFeed.tsx            → List of recent sessions/events
  IterationDistributionChart.tsx → Bar chart for iteration ranges
  ConsumerUsageChart.tsx      → Line chart for per-agent consumer usage
  ChannelActivityCard.tsx     → Per-channel stats cards
  TopUsersTable.tsx           → Table of top users for an agent
  ReleaseTimeline.tsx         → Vertical release history timeline
```

### New API Client Functions

Add to `web/src/utils/api.ts`:

```typescript
// Studio analytics
getStudioOverview(range: string): Promise<StudioOverview>
getStudioSessionTrends(range: string): Promise<DailySessionCount[]>
getStudioTaskStats(range: string): Promise<TaskStats>
getStudioTokenUsage(range: string): Promise<DailyTokenUsage[]>
getStudioAgentPopularity(range: string, limit: number): Promise<AgentPopularity[]>
getStudioUserActivity(range: string): Promise<DailyUserActivity[]>
getStudioUserGrowth(range: string): Promise<DailyUserGrowth[]>
getStudioRuntimeHealth(): Promise<RuntimeHealth>
getStudioRecentActivity(limit: number): Promise<RecentActivityItem[]>

// Agent analytics
getAgentAnalyticsOverview(agentId: number, range: string): Promise<AgentOverview>
getAgentSessionTrends(agentId: number, range: string): Promise<DailySessionCount[]>
getAgentTokenUsage(agentId: number, range: string): Promise<DailyTokenUsage[]>
getAgentIterationDistribution(agentId: number, range: string): Promise<IterationBucket[]>
getAgentConsumerUsage(agentId: number, range: string): Promise<DailyConsumerUsage[]>
getAgentChannelActivity(agentId: number, range: string): Promise<ChannelActivityItem[]>
getAgentTopUsers(agentId: number, range: string, limit: number): Promise<AgentUserStats[]>
getAgentReleases(agentId: number): Promise<AgentReleaseItem[]>
```

### Chart Library

shadcn/ui Charts already installed. Component at `web/src/components/ui/chart.tsx` with ChartContainer, ChartTooltip, ChartTooltipContent, ChartLegend, ChartLegendContent primitives. Recharts (`^2.15.4`) is the underlying dependency.

### Page Components

**StudioDashboardPage** (`web/src/components/StudioDashboardPage.tsx`):
- Replace current placeholder with full dashboard layout
- Uses a grid layout (CSS Grid or shadcn/ui ResizablePanels)
- Manages `dateRange` state (default "30d")
- Fetches all studio analytics data on mount + range change
- Renders all dashboard chart components

**AgentDetail** (`web/src/components/AgentDetail.tsx`):
- Add `'analytics'` tab type to `agentTabStore`
- When `tabs.length === 0` and agent data loaded, auto-open the Analytics tab
- Analytics tab renders agent-specific chart components
- Shares the same `dateRange` state within the tab
- Fetches agent analytics data when tab is active

---

## Phased Implementation Plan

### Phase 0: User FK Migration — COMPLETED (2025-05-11)

**Goal**: Replace all `user: str` fields with `user_id: int` FK across the entire codebase.

**This phase must be completed before any analytics work begins.**

**Models**:
- Replace `user: str` with `user_id: int = Field(foreign_key="user.id", index=True)` in 6 core tables
- Replace username-like string fields with user_id FK in 6 secondary tables
- Remove old `user` / `username` / `installed_by` / `saved_by` / `created_by` / `workspace_owner` string columns

**Filesystem paths**:
- Change `file_service.py` path scheme from `users/{username}/...` to `users/{user_id}/...`
- Change `workspace_service.py` path scheme from `users/{username}/...` to `users/{user_id}/...`

**Services** (12 files):
- Update all ownership checks from `.user == username` to `.user_id == user.id`
- Eliminate reverse User lookups (`select(User).where(User.username == model.user)`)
- Pass `current_user.id` instead of `current_user.username` throughout

**API routes** (7 files):
- All auth-dependent endpoints pass `current_user.id` to services
- Ownership gates compare against `user_id` instead of `username`

**Schemas** (3 files):
- Update request/response schemas to use `user_id: int`

**Orchestration** (1 file):
- Update `react/engine.py` to pass user_id

**Indexes**:
- Add composite indexes for analytics query patterns (see Index Strategy section above)

**Deliverable**: Clean codebase where all user references are via `user_id` FK. Database can be recreated from scratch (user deletes `pivot.db`).

**Completion summary**:
- 12 model tables migrated (`user: str` / `username: str` → `user_id: int FK`)
- 20+ service files updated (eliminated all reverse User lookups)
- 12+ API route files updated (all pass `current_user.id`)
- 5 schema files, 5+ orchestration files updated
- Sandbox manager (`sandbox_manager/main.py`) migrated (`username: str` → `user_id: int`)
- Filesystem paths: `users/{username}/` → `users/{user_id}/`
- Composite indexes added for analytics query patterns
- Frontend types, components, and test mocks updated to match API changes
- Ruff lint + Pyright type-check: 0 errors

---

### Phase 1: Foundation — Studio Dashboard Skeleton — COMPLETED (2025-05-11)

**Goal**: Replace the placeholder with a working dashboard showing KPI cards and one chart.

**Backend**:
- Create `AnalyticsService` with `get_studio_overview()` and `get_session_trends()`
- Create `analytics.py` router with 2 endpoints
- Register router in `main.py`

**Frontend**:
- Create `KpiCard.tsx`, `DateRangeSelector.tsx`, `SessionTrendChart.tsx`
- Replace `StudioDashboardPage.tsx` placeholder with dashboard layout
- Add API client functions for the 2 endpoints

**Deliverable**: A live dashboard with 5 KPI cards and a session activity area chart.

**Completion summary**:
- `server/app/services/analytics_service.py` — AnalyticsService with overview (agents/sessions/users/tasks/success_rate + period-over-period deltas) and session trends (daily buckets by type, SQLite/PostgreSQL dialect-aware)
- `server/app/api/analytics.py` — 2 GET endpoints (`/analytics/studio/overview`, `/analytics/studio/session-trends`) gated by `studio.access` permission
- `web/src/components/analytics/` — 3 reusable components (KpiCard with trend arrows, DateRangeSelector 7d/30d/90d, SessionTrendChart stacked area chart)
- `web/src/components/StudioDashboardPage.tsx` — replaced placeholder with live dashboard grid
- `web/src/utils/api.ts` — added StudioOverview + DailySessionCount types and 2 API client functions
- Ruff lint + Pyright + Frontend type-check: 0 new errors

---

### Phase 2: Studio Dashboard — Core Charts — COMPLETED (2025-05-11)

**Goal**: Complete all dashboard chart modules.

**Backend**:
- Add to `AnalyticsService`: `get_task_stats()`, `get_token_usage()`, `get_agent_popularity()`, `get_runtime_health()`, `get_recent_activity()`
- Add corresponding router endpoints

**Frontend**:
- Create: `TaskStatusChart.tsx`, `TokenUsageChart.tsx`, `AgentPopularityChart.tsx`, `RuntimeHealthCard.tsx`, `ActivityFeed.tsx`
- Add API client functions
- Assemble into dashboard page grid

**Deliverable**: Full studio dashboard with 9 modules (KPI cards + 5 charts + runtime health + activity feed).

**Completion summary**:
- `AnalyticsService` — 5 new methods: `get_task_stats()` (status group-by), `get_token_usage()` (daily prompt/completion/cached sums), `get_agent_popularity()` (top N agents by consumer sessions with JOIN), `get_runtime_health()` (sandbox count via HTTP + storage profile + failed tasks 24h), `get_recent_activity()` (latest sessions with agent/user JOINs)
- `analytics.py` router — 5 new GET endpoints (`task-stats`, `token-usage`, `agent-popularity`, `runtime-health`, `recent-activity`)
- `web/src/components/analytics/` — 5 new components: `TaskStatusChart` (PieChart donut with center label), `TokenUsageChart` (stacked BarChart), `AgentPopularityChart` (horizontal BarChart), `RuntimeHealthCard` (status card), `ActivityFeed` (feed list with status dots and timestamps)
- `StudioDashboardPage.tsx` — expanded to 3 chart rows (Session+TaskStatus, TokenUsage+AgentPopularity, RuntimeHealth+ActivityFeed) with loading skeletons
- `api.ts` — added 5 types (TaskStats, DailyTokenUsage, AgentPopularity, RuntimeHealth, RecentActivityItem) and 5 API client functions
- Ruff lint + Pyright + Frontend type-check: 0 new errors

---

### Phase 3: Studio Dashboard — User Analytics — COMPLETED (2025-05-11)

**Goal**: Add client-side user dimension analytics.

**Backend**:
- Add to `AnalyticsService`: `get_user_activity()`, `get_user_growth()`
- Add corresponding router endpoints

**Frontend**:
- Create: `UserActivityChart.tsx`, `UserGrowthChart.tsx`
- Add to dashboard page layout

**Deliverable**: Dashboard now shows DAU/WAU/MAU trend and new user registration chart.

**Completion summary**:
- `AnalyticsService` — 2 new methods: `get_user_activity()` (daily distinct consumer users with rolling WAU/MAU from extended query window), `get_user_growth()` (daily new user registration counts via User.created_at bucketing)
- `analytics.py` router — 2 new GET endpoints (`user-activity`, `user-growth`)
- `web/src/components/analytics/` — 2 new components: `UserActivityChart` (LineChart with DAU/WAU/MAU lines + legend), `UserGrowthChart` (BarChart for new users/day)
- `StudioDashboardPage.tsx` — added 4th chart row (UserActivity + UserGrowth)
- `api.ts` — added DailyUserActivity, DailyUserGrowth types and 2 API client functions
- Ruff lint + Pyright + Frontend type-check: 0 new errors

---

### Phase 4: Agent Analytics Tab — Core Metrics

**Goal**: Add analytics tab to agent detail page with agent-scoped metrics.

**Backend**:
- Add to `AnalyticsService`: `get_agent_overview()`, `get_agent_session_trends()`, `get_agent_token_usage()`, `get_agent_iteration_distribution()`, `get_agent_top_users()`, `get_agent_releases()`
- Add `/api/analytics/agents/{agent_id}/*` endpoints

**Frontend**:
- Add `'analytics'` tab type to `agentTabStore`
- Auto-open Analytics tab when agent detail page loads with no other tabs
- Create: `IterationDistributionChart.tsx`, `ConsumerUsageChart.tsx`, `TopUsersTable.tsx`, `ReleaseTimeline.tsx`
- Reuse: `SessionTrendChart.tsx`, `TaskStatusChart.tsx`, `TokenUsageChart.tsx` with agent-scoped data
- Add API client functions

**Deliverable**: Agent detail page auto-opens an Analytics tab with KPI cards, charts, top users table, and release timeline.

---

### Phase 5: Agent Analytics — Channel & Consumer Deep Dive

**Goal**: Add channel activity and consumer usage analytics to the agent cockpit.

**Backend**:
- Add to `AnalyticsService`: `get_agent_consumer_usage()`, `get_agent_channel_activity()`
- Add corresponding endpoints

**Frontend**:
- Create: `ChannelActivityCard.tsx`, `ConsumerUsageChart.tsx`
- Add to Analytics tab layout

**Deliverable**: Agent analytics shows per-channel activity cards and consumer DAU/message trend for the specific agent.

---

### Phase 6: Polish & Optimization

**Goal**: Performance tuning and UX refinement.

**Tasks**:
- Add loading skeletons for all chart areas
- Add error states for failed analytics fetches
- Verify composite indexes are used by EXPLAIN ANALYZE on representative queries
- Add empty states for agents with no analytics data
- Ensure responsive layout for smaller screens
- Run lint and type-check passes
