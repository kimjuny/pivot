# Automations

## Problem

Client users can only interact with agents in real-time — they send a message, wait for the agent to respond, and the conversation ends. There is no way to schedule recurring agent tasks (e.g., daily report generation, weekly data analysis, periodic monitoring). This limits the agent platform to reactive use cases and misses the high-value scenario of proactive, scheduled automation.

## Design Principles

1. **Agent-centric**: An automation is "a scheduled conversation with an agent." It reuses the existing ReAct task execution engine — not a new execution paradigm.
2. **Client-first, Studio-observant**: The primary user is the Client end-user. Studio users can observe automations attached to their agents but do not create them.
3. **Simple by default**: MVP focuses on cron-triggered automations only. The schema is extensible for future event-based triggers.
4. **Database-claim scheduling**: Multi-instance safe via atomic DB inserts. No external dependencies (Redis, message broker). Works identically on SQLite (dev) and PostgreSQL (prod).
5. **User-controlled session strategy**: Let the user choose whether each automation reuses one session (context continuity) or creates a fresh session per run (isolation).
6. **Service-layer discipline**: All persistent-data interactions go through service layer. `automation_service.py` for CRUD, `automation_scheduler.py` for scheduling, `automation_executor.py` for execution.

## Typical Scenarios

| Scenario | Description | Trigger | Session Strategy |
|----------|-------------|---------|------------------|
| Daily briefing | Agent summarizes workspace file changes every morning | Cron daily 9:00 | Reuse (compare to yesterday) |
| Weekly data analysis | Agent analyzes project data and outputs a report | Cron weekly Monday | Reuse (trend tracking) |
| Competitor monitoring | Agent checks competitor websites and summarizes changes | Cron daily | Reuse (compare to previous) |
| Independent batch processing | Agent processes uploaded files on a schedule | Cron daily | Isolate (each run independent) |
| Conditional alert | Agent monitors data and alerts when thresholds are exceeded | Cron hourly | Reuse (cumulative context) |

## Core Concepts

```
Automation
  ├── owner (Client user who created it)
  ├── agent (which published agent to talk to)
  ├── release (pinned to a specific release, like client sessions)
  ├── trigger (cron expression + timezone)
  ├── prompt_template (message sent to agent, supports {{date}} etc.)
  ├── session_strategy ("reuse" | "isolate")
  ├── status ("active" | "paused" | "disabled")
  ├── execution_settings (timeout, max_iterations)
  └── AutomationRun[] (execution history)
        ├── session_id (the Session created/used for this run)
        ├── task_id (the ReactTask)
        ├── status ("pending" | "running" | "completed" | "failed" | "timeout" | "cancelled")
        ├── result_summary (agent's final answer)
        └── error_message (if failed)
```

## Data Model

### Automation

```python
class Automation(SQLModel, table=True):
    __tablename__ = "automation"

    id: int | None = Field(default=None, primary_key=True)
    automation_id: str = Field(default_factory=lambda: uuid4().hex)
    name: str
    description: str | None = None

    # Ownership
    owner_id: int = Field(foreign_key="user.id")
    agent_id: int = Field(foreign_key="agent.id")

    # Release binding (pin to a specific published release)
    release_id: int = Field(foreign_key="agentrelease.id")

    # Trigger (Phase 1: cron only)
    trigger_type: str = "cron"  # "cron" | future: "event"
    trigger_config: str  # JSON: {"cron": "0 9 * * 1-5", "timezone": "Asia/Shanghai"}

    # Task template
    prompt_template: str  # Supports {{date}}, {{time}}, {{agent_name}}

    # Session strategy
    session_strategy: str = "reuse"  # "reuse" | "isolate"

    # Status
    status: str = "active"  # "active" | "paused" | "disabled"

    # Execution settings
    max_iterations: int | None = None  # Override agent default
    timeout_seconds: int = 300  # Per-run timeout

    # Notification
    notify_on_completion: bool = False
    notify_on_failure: bool = True

    # Scheduling metadata
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None

    # Relations
    runs: list["AutomationRun"] = Relationship(back_populates="automation")
```

### AutomationRun

```python
class AutomationRun(SQLModel, table=True):
    __tablename__ = "automation_run"

    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(default_factory=lambda: uuid4().hex)
    automation_id: int = Field(foreign_key="automation.id")

    # Claim-based deduplication for multi-instance safety
    scheduled_at: datetime  # The time this run was *supposed* to fire

    # Execution context
    session_id: int = Field(foreign_key="session.id")
    task_id: str | None = None  # ReactTask.task_id

    # Status
    status: str = "pending"  # "pending" | "running" | "completed" | "failed" | "timeout" | "cancelled"
    started_at: datetime | None = None
    finished_at: datetime | None = None

    # Result
    result_summary: str | None = None
    error_message: str | None = None
    token_usage: str | None = None  # JSON: {"prompt": x, "completion": y}

    # Relations
    automation: Automation | None = Relationship(back_populates="runs")
```

### Unique Constraint (multi-instance dedup)

```python
# On AutomationRun table
__table_args__ = (
    UniqueConstraint("automation_id", "scheduled_at", name="uq_automation_run_claim"),
)
```

This ensures exactly one instance can successfully INSERT a run for a given `(automation_id, scheduled_at)` pair.

### Session type

Add `"automation"` as a new `Session.type` value alongside `"client"` and `"studio_test"`.

**Why a separate type is necessary**: Automation sessions must NOT appear in the Client sidebar's regular session list. A user with 3 daily automations would accumulate ~90 sessions per month, drowning out their manual conversations. With a distinct type, the sidebar query simply filters `WHERE type = 'client'`. Users access automation sessions through the Automations view → run history → click into a specific run's session.

| Session Type | Visibility |
|--------------|------------|
| `client` | Client sidebar session list (manual conversations) |
| `studio_test` | Studio session history (test conversations) |
| `automation` | Automations view only (scheduled run conversations) |

## Scheduler Architecture (Multi-Instance Safe)

### Design: Database Claim Pattern

Each backend instance runs its own `AutomationScheduler` background loop. Correctness is guaranteed by the database, not by coordination between instances.

```
┌────────────┐  ┌────────────┐  ┌────────────┐
│ Backend #1 │  │ Backend #2 │  │ Backend #3 │
│ Scheduler  │  │ Scheduler  │  │ Scheduler  │
└─────┬──────┘  └─────┬──────┘  └─────┬──────┘
      │               │               │
      └───────────────┼───────────────┘
                      │
              ┌───────▼────────┐
              │   PostgreSQL   │
              │  (or SQLite)   │
              │                │
              │  UNIQUE(       │
              │   automation_id│
              │   scheduled_at │
              │  )             │
              └────────────────┘
```

### Execution Flow

```
1. Scan: SELECT FROM automation WHERE status='active' AND next_run_at <= now()

2. Claim (for each due automation):
   try:
       INSERT INTO automation_run (automation_id, scheduled_at, status='pending')
       # UNIQUE constraint → only one instance succeeds
   except IntegrityError:
       continue  # Another instance already claimed this run

3. Execute (on the instance that claimed successfully):
   a. Resolve session (reuse or create new, based on session_strategy)
   b. Render prompt_template (replace {{date}}, {{time}}, etc.)
   c. Call ReactTaskSupervisor.start_task()
   d. Wait for completion (with timeout)
   e. Record result in AutomationRun
   f. Update automation.last_run_at and next_run_at (croniter)
```

### Why this works for Kubernetes

| Property | Guarantee |
|----------|-----------|
| **No duplicate execution** | UNIQUE constraint on (automation_id, scheduled_at) |
| **No single point of failure** | Any instance can claim and execute; if one dies mid-run, the run stays in "running" and can be detected by a watchdog later |
| **No external dependencies** | No Redis, no message broker, no leader election |
| **Linear scaling** | More instances = more capacity for concurrent runs; idle instances just skip claimed runs |
| **Dev/prod parity** | SQLite supports UNIQUE constraints too; behavior is identical |

### Stale run recovery

If an instance dies mid-execution, a run stays in `status="running"` forever. The scheduler should include a watchdog that detects runs stuck in "running" beyond `timeout_seconds` and marks them as "timeout" / "failed". This is a simple periodic scan:

```
SELECT FROM automation_run
WHERE status = 'running'
AND started_at < now() - INTERVAL 'timeout_seconds seconds'
```

## Configuration

```python
# server/app/config.py (Pydantic Settings)

AUTOMATION_SCHEDULER_ENABLED: bool = True
AUTOMATION_SCHEDULER_SCAN_INTERVAL_SECONDS: int = 30
AUTOMATION_SCHEDULER_MAX_CONCURRENT_RUNS: int = 5  # Per instance
AUTOMATION_RUN_TIMEOUT_SECONDS: int = 300
```

| Setting | Default | Purpose |
|---------|---------|---------|
| `AUTOMATION_SCHEDULER_ENABLED` | `True` | Can completely disable the scheduler (useful for worker-only instances) |
| `AUTOMATION_SCHEDULER_SCAN_INTERVAL_SECONDS` | `30` | How often each instance scans for due automations |
| `AUTOMATION_SCHEDULER_MAX_CONCURRENT_RUNS` | `5` | Max simultaneous automation tasks per backend instance |
| `AUTOMATION_RUN_TIMEOUT_SECONDS` | `300` | Default per-run timeout; can be overridden per automation |

In a Kubernetes deployment, you could set `AUTOMATION_SCHEDULER_ENABLED=false` on API-only instances and `true` on worker instances, or let all instances run the scheduler (the claim pattern handles deduplication).

## Session Strategy

Each automation has a `session_strategy` field chosen by the user at creation time.

### Reuse (default)

All runs share one long-lived Session (`type="automation"`). Each run creates a new ReactTask within that session.

```
Automation "Daily Report"
  └── Session #42 (type="automation", agent_id=7)
        ├── ReactTask (Monday)   → "Today's summary..."
        ├── ReactTask (Tuesday)  → "Compared to yesterday..."
        └── ReactTask (Wednesday)→ "Key changes since Monday..."
```

Agent has full context continuity — can reference previous run results, compare trends, build on prior work. Context compaction (`react_compact_service.py`) handles long-running sessions automatically.

### Isolate

Each run creates a brand-new Session. No context is shared between runs.

```
Automation "Batch Processing"
  ├── Session #51 (run 1, Monday) → ReactTask → result
  ├── Session #52 (run 2, Tuesday) → ReactTask → result
  └── Session #53 (run 3, Wednesday) → ReactTask → result
```

Each run is completely independent. Suitable for stateless, idempotent tasks.

### UI presentation

```
┌─────────────────────────────────────┐
│  Context Strategy                   │
│                                     │
│  ● Continuous (Recommended)         │
│    Agent remembers previous runs,   │
│    can compare and track changes.   │
│                                     │
│  ○ Independent                      │
│    Each run starts fresh, no memory │
│    of previous executions.          │
└─────────────────────────────────────┘
```

## Prompt Template

The `prompt_template` field supports simple variable interpolation:

| Variable | Example Value | Description |
|----------|---------------|-------------|
| `{{date}}` | `2026-05-24` | Current date (YYYY-MM-DD) |
| `{{time}}` | `09:00` | Current time (HH:MM) |
| `{{datetime}}` | `2026-05-24 09:00:00` | Current datetime |
| `{{agent_name}}` | `Data Analyst` | Bound agent's display name |
| `{{weekday}}` | `Monday` | Day of week |
| `{{run_number}}` | `42` | Sequential run count for this automation |

Rendering happens at execution time in `AutomationExecutor` before calling `start_task()`.

## API Design

### Client endpoints (end-user facing)

```
GET    /api/client/automations                 List user's automations
POST   /api/client/automations                 Create automation
GET    /api/client/automations/:automationId   Get automation detail
PUT    /api/client/automations/:automationId   Update automation (edit prompt, trigger, pause/resume)
DELETE /api/client/automations/:automationId   Delete automation
GET    /api/client/automations/:automationId/runs    List execution history
GET    /api/client/automations/:automationId/runs/:runId  Get single run detail
POST   /api/client/automations/:automationId/trigger   Manually trigger one run (for testing)
```

### Studio endpoints (admin/builder observation)

```
GET    /api/agents/:agentId/automations        List automations bound to an agent
GET    /api/automations/:automationId/runs     View execution history (admin)
```

## Frontend Design

### Client UI placement

The Automation feature lives inside the existing `ClientAgentsPage` sidebar. No new top-level routes.

`SessionSidebar` `navigationItems` expands from:

```
[Agents]
```

to:

```
[Agents]  [Automations]
```

Clicking "Automations" switches the right-side content area from the agent list to the automation list. This is a state-driven view switch within `ClientAgentsPage`, not a route change.

### Component structure

```
web/src/client/
  ClientAgentsPage.tsx        ← Modified: add navigationItems entry, view state toggle
  ClientAutomationsView.tsx   ← New: automation list + create/edit dialog
  api.ts                      ← Extended: add automation API functions

web/src/components/
  AutomationCreateDialog.tsx  ← New: create/edit automation modal
  TriggerConfigurator.tsx     ← New: cron schedule picker component
  PromptTemplateEditor.tsx    ← New: prompt editor with variable insertion
  AutomationRunHistory.tsx    ← New: execution history table
```

### Automation list

Follows the existing card-list pattern (similar to agent list in `AgentList.tsx`):

```
┌─────────────────────────────────────────────────────┐
│  Automations                          [+ New]       │
│                                                     │
│  [All]  [Active]  [Paused]                          │
│                                                     │
│  ┌─────────────────────────────────────────────┐    │
│  │ 📋 Daily Report                    ▸ Active │    │
│  │ Agent: Data Analyst                         │    │
│  │ Every weekday at 9:00 AM                   │    │
│  │ Last run: 2h ago ✓  │  Next: tomorrow 9:00 │    │
│  └─────────────────────────────────────────────┘    │
│                                                     │
│  ┌─────────────────────────────────────────────┐    │
│  │ 📋 Weekly Analysis               ▸ Paused  │    │
│  │ Agent: Report Bot                           │    │
│  │ Every Monday at 10:00 AM                   │    │
│  │ Last run: 3 days ago ✓                      │    │
│  └─────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────┘
```

Each card shows: name, bound agent, schedule summary, status badge, last run status + time, next run time. Actions: edit, pause/resume, delete, manual trigger.

### Create/Edit dialog

Uses the existing vertical-tab `Dialog` pattern from `AgentModal.tsx`:

```
┌─────────────────────────────────────────────────────────────┐
│  New Automation                                    [×]      │
│                                                             │
│  General  │  Name: [Daily Report                        ]   │
│  Schedule │  Description: [Summarize workspace changes  ]   │
│  Prompt   │                                                  │
│  Settings │  Agent: [Data Analyst          ▾]             │
│           │                                                  │
│           │  Context Strategy:                               │
│           │  ● Continuous (Recommended)                      │
│           │  ○ Independent                                   │
│           │                                                  │
│                                            [Cancel] [Create]│
└─────────────────────────────────────────────────────────────┘
```

Tabs:

- **General**: Name, description, agent selector, context strategy
- **Schedule**: Frequency picker (daily / weekly / monthly / custom cron), time picker, timezone
- **Prompt**: Prompt template editor with variable insertion ({{date}}, {{time}}, etc.)
- **Settings**: Timeout, max iterations, notification preferences

### Automation detail

Clicking an automation card opens a detail view (within the same right-side content area) showing:

1. **Run history table**: columns = scheduled time, status, duration, result summary, link to session
2. **Action buttons**: Edit, Pause/Resume, Delete, Trigger Now
3. Clicking a run links to the session page (`/app/agents/:agentId?session=:sessionId`) for full conversation view

### Studio integration

In `AgentDetailSidebar.tsx`, add a new collapsible section:

```
AUTOMATIONS  [3]
  ├ Daily Report       Active   9:00 AM weekdays
  ├ Weekly Analysis    Paused   Mondays 10:00 AM
  └ Competitor Check   Active   Daily 6:00 PM
```

This gives builders visibility into which automations are consuming their agents, without the ability to edit client-owned automations.

## Service Layer

### automation_service.py (CRUD)

Standard CRUD service following the project's service pattern:

- `list_automations(user_id, filters)` — list user's automations with optional status filter
- `get_automation(automation_id, user_id)` — get single automation with ownership check
- `create_automation(user_id, data)` — create automation, validate agent/release, compute initial `next_run_at`
- `update_automation(automation_id, user_id, data)` — update fields, recompute `next_run_at` if trigger changed
- `delete_automation(automation_id, user_id)` — delete automation and cascade runs
- `list_automation_runs(automation_id, user_id, pagination)` — list runs for an automation
- `get_automation_run(run_id, user_id)` — get single run detail
- `trigger_automation(automation_id, user_id)` — manually trigger an immediate run

### automation_scheduler.py (Background loop)

Background `asyncio.Task` started in `main.py` startup, following the `ChannelRuntimeManager` pattern:

```
loop:
    if not AUTOMATION_SCHEDULER_ENABLED: sleep and continue
    scan due automations
    for each due automation:
        if current_concurrent_runs >= MAX_CONCURRENT_RUNS: break
        try atomic claim (INSERT automation_run)
        if claimed: submit to executor pool
    sleep SCAN_INTERVAL
    periodically scan for stale runs (watchdog)
```

### automation_executor.py (Run execution)

Handles a single automation run:

1. Resolve session (reuse existing or create new based on `session_strategy`)
2. Render `prompt_template` with variable substitution
3. Call `ReactTaskSupervisor.start_task()` with the rendered prompt
4. Poll/wait for task completion with timeout
5. Extract result summary and token usage
6. Update `AutomationRun` with final status and result
7. Update `Automation.last_run_at` and compute `next_run_at`

## Implementation Phases

### Phase 1 — MVP (~1.5 days)

1. Data models (`automation.py`, `automation_run.py`) + Alembic migration
2. `automation_service.py` — full CRUD
3. `automation_scheduler.py` + `automation_executor.py` — background scheduling
4. Config settings in `config.py`
5. Client API routes (`api/client.py` extension or new `api/client_automations.py`)
6. Client frontend: sidebar navigation entry + automation list + create dialog (cron only)

### Phase 2 — Polish (~1 day)

7. Client frontend: detail view with run history table
8. Manual trigger functionality
9. Studio sidebar integration in `AgentDetailSidebar.tsx`
10. Prompt template variable system
11. Stale run watchdog

### Phase 3 — Enhancements

12. Click into run's session chat from Run History (navigate to the session conversation to view agent results)
13. Notification via sonner toast (enhance trigger toast with "View Chat" action; scheduled runs found via Run History)
14. Dashboard integration (Session Activity chart + KPI stats)
15. Extension hook support for automation lifecycle events
16. Automation run result delivery (email, channel push, etc.)

## Key Files to Create/Modify

### New files

| File | Purpose |
|------|---------|
| `server/app/models/automation.py` | Automation + AutomationRun models |
| `server/app/services/automation_service.py` | CRUD operations |
| `server/app/services/automation_scheduler.py` | Background scheduler loop |
| `server/app/services/automation_executor.py` | Single run execution |
| `server/app/api/client_automations.py` | Client-facing API routes |
| `web/src/client/ClientAutomationsView.tsx` | Automation list view |
| `web/src/components/AutomationCreateDialog.tsx` | Create/edit modal |
| `web/src/components/TriggerConfigurator.tsx` | Cron schedule picker |
| `web/src/components/PromptTemplateEditor.tsx` | Template editor |
| `web/src/components/AutomationRunHistory.tsx` | Run history table |

### Modified files

| File | Change |
|------|--------|
| `server/app/config.py` | Add automation scheduler settings |
| `server/app/main.py` | Start scheduler on startup, stop on shutdown |
| `web/src/client/ClientAgentsPage.tsx` | Add Automations nav item + view toggle |
| `web/src/client/api.ts` | Add automation API functions |
| `web/src/components/AgentDetailSidebar.tsx` | Add AUTOMATIONS section |

## Implementation Progress

### Phase 1 — MVP Status: **DONE** (2026-05-24)

All backend and core frontend pieces are implemented and passing lint/type checks. Backend starts successfully with scheduler running.

#### Completed items

| # | Item | Status | Notes |
|---|------|--------|-------|
| 1 | Data models | ✅ | `automation.py` with `Automation` + `AutomationRun`. No Alembic — tables auto-created via `SQLModel.metadata.create_all()`. |
| 2 | Service CRUD | ✅ | `automation_service.py` — full CRUD, cron validation, claim_run, session resolution |
| 3 | Scheduler + Executor | ✅ | `automation_scheduler.py` (background loop + stale watchdog) + `automation_executor.py` (render prompt → start_task → record result) |
| 4 | Config settings | ✅ | 4 settings in `config.py`: `AUTOMATION_SCHEDULER_ENABLED`, `AUTOMATION_SCHEDULER_SCAN_INTERVAL_SECONDS`, `AUTOMATION_SCHEDULER_MAX_CONCURRENT_RUNS`, `AUTOMATION_RUN_TIMEOUT_SECONDS` |
| 5 | Client API routes | ✅ | `api/client_automations.py` — 9 endpoints (list, create, get, update, delete, runs, run detail, trigger, session strategy) |
| 6 | Scheduler lifecycle | ✅ | Wired in `main.py` startup/shutdown, logs "Automation scheduler started" |
| 7 | Client frontend | ✅ | Sidebar "Automations" nav item + `ClientAutomationsView` (list, status filter, CRUD) + `AutomationCreateDialog` (agent select, cron picker, prompt template, session strategy radio) |
| 8 | API client | ✅ | `client/api.ts` extended with types + 7 API functions |
| 9 | Dependency | ✅ | `croniter` added to `pyproject.toml` |
| 10 | Session type | ✅ | `"automation"` added as third session type in `Session.type` |
| 11 | `propose_automation` tool | ✅ | Built-in tool that lets agents propose automations to users via chat. Returns `pivot_action` envelope → frontend opens pre-filled `AutomationCreateDialog`. Handler registered in `actionHandlers.ts`. |

#### Bugs fixed during Phase 1

| Issue | Root cause | Fix |
|-------|-----------|-----|
| `ModuleNotFoundError: No module named 'croniter'` | New dependency not in container venv | `pip install croniter` in container |
| `NoReferencedTableError: table 'agent_release'` | SQLModel default table name for `AgentRelease` is `agentrelease` (no underscore) | Changed FK to `foreign_key="agentrelease.id"` |
| `InvalidRequestError: generic class in relationship()` | `from __future__ import annotations` breaks SQLAlchemy runtime relationship resolution | Removed future import, used quoted string `list["AutomationRun"]` |
| `propose_automation` crashes: "got multiple values for argument 'name'" | `ToolManager.execute(name=...)` positional param collides with tool's own `name` kwarg in `**kwargs` | Renamed execute's param from `name` to `_tool_name` |
| `AutomationCreateDialog` opens empty (no pre-filled data) | `useState` initializer only runs once on mount, when `proposal` is still `null` | Added `useEffect` watching `open` + `proposal` to re-initialize form data |
| Agent selector empty in `AutomationCreateDialog` | Rendered with `agents={[]}` — no agent list fetched | Added `getAgents()` call when dialog opens, pass `automationAgents` state to dialog |

### Phase 2 — Polish Status: **DONE** (2026-05-24)

#### Completed items

| # | Item | Status | Notes |
|---|------|--------|-------|
| 7 | Detail view with Card layout | ✅ | `ClientAutomationDetailView.tsx` — Hero card (LLMBrandAvatar + title + description), Separator, info grid (Status badge, Schedule, Context Strategy, Timeout, Last/Next Run). Prompt Template card with `MarkdownRenderer`. Run History card with `Table`. |
| 8 | Manual trigger from UI | ✅ | "Trigger" button in detail header + "Trigger Now" in list card dropdown. End-to-end tested via Chrome DevTools. |
| 9 | Studio sidebar integration | ✅ | "Automations" nav item in `SessionSidebar` navigation items. |
| 10 | Template variable system | ✅ | All 6 variables working: `{{date}}`, `{{time}}`, `{{datetime}}`, `{{weekday}}`, `{{agent_name}}`, `{{run_number}}`. |
| 11 | Edit mode (via dialog) | ✅ | `AutomationCreateDialog` extended with `automation` prop for edit mode. Pre-fills form from existing automation data (including cron → frequency reverse-parse via `parseCronForForm`). Calls `updateClientAutomation` on save. |
| 12 | List layout overhaul | ✅ | 2-column responsive grid (`md:grid-cols-2`). Compact cards with Clock icon, name + agent name, status badge, dropdown menu (pause/resume/trigger/delete), schedule + timing info row. Click card → detail view. |
| 13 | Markdown rendering | ✅ | Prompt Template card uses `MarkdownRenderer` (shared component from chat). |
| 14 | Agent avatar in detail | ✅ | Hero card uses `LLMBrandAvatar` with agent's model, falling back to `Bot` icon. |

#### Bugs fixed during Phase 2

| Issue | Root cause | Fix |
|-------|-----------|-----|
| `WorkspaceService.create_workspace()` TypeError on trigger | `_create_automation_session` passed wrong params (`label=...`) | Fixed to pass `agent_id=automation.agent_id, user_id=automation.owner_id, scope="session_private", session_id=session_id` |
| `DetachedInstanceError` in `automation_executor.py` | ORM attributes accessed after `managed_session()` context closed | Extracted scalar values (`automation_id`, `agent_id`, `owner_id`, `timeout_seconds`, `prompt_template`, `session_id_str`) while DB session active, stored as local variables |
| Pyright: `automation.id` is `int | None` | SQLModel primary key is nullable in type stubs | Added `if automation.id is None` guard before assignment |
| Pyright: nullable `next_run_at` comparison | Direct column comparison not allowed | Changed to `col(Automation.next_run_at) <= datetime.now(UTC)` |

#### Design decisions during Phase 2

| Decision | Rationale |
|----------|-----------|
| Edit uses dialog (not inline editing) | User explicitly requested: "复用原来的Create Automation Dialog". Reusing the dialog keeps form logic (cron builder, validation) in one place. |
| Info fields as plain label/value pairs (not badges) | Only Status is naturally a badge. Schedule, Timeout, Context Strategy etc. are text values — badges looked forced. |
| Description as subtitle (fallback to agent name) | Hero card pattern from ExtensionDetailPage: avatar + title + description subtitle gives immediate context. |
| `MarkdownRenderer` for Prompt Template | Same rendering engine as chat ANSWER blocks ensures consistency and supports rich formatting in prompts. |
| `parseCronForForm` helper | Needed to reverse a cron expression back into the dialog's frequency/time fields when editing. |

#### Not yet implemented (Phase 3+)

- Stale run watchdog (scheduler code exists but not tested end-to-end)
- `TriggerConfigurator.tsx` as standalone component (currently inline in dialog)
- `PromptTemplateEditor.tsx` as standalone component (currently inline in dialog)
- `AutomationRunHistory.tsx` as standalone component (currently inline in detail view)
- Studio `AgentDetailSidebar.tsx` AUTOMATIONS section (read-only builder view)

### Phase 3 — Enhancements Status: **IN PROGRESS** (2026-05-25)

#### Completed items

| # | Item | Status | Notes |
|---|------|--------|-------|
| 12 | Click into run's session chat | ✅ | All run history rows (completed, failed, timeout) are clickable if they have a `session_uuid`. Navigates to the session's chat view via `onNavigateToSession`. |
| 13 | Custom toast notification | ✅ | `toast.custom()` with `LLMBrandAvatar` (agent icon), title + status/duration text, "View →" link. Polls run status until terminal state, shows success (green checkmark) or failure (red X) with duration. 10s display duration. |
| 14a | Session Activity chart integration | ✅ | Added "Automation" as third series in `SessionTrendChart` stacked area chart alongside "Client" and "Studio". Backend `analytics_service.py` returns `automation` count per day. Colors aligned with `TokenUsageChart` palette (`--chart-4`, `--chart-3`, `--chart-2`). Tooltip shows all 3 values + total. |
| — | Run status accuracy | ✅ | Executor now propagates actual `ReactTask.status` (not hardcoded "completed"), extracts error from `ReactRecursion.error_log`, and builds token usage JSON from `total_prompt_tokens`/`total_completion_tokens`/`total_tokens`. |
| — | Scheduler `claim_run` dedup | ✅ | Added SELECT-before-INSERT check for existing pending/running runs at the same slot. Eliminates noisy `IntegrityError` tracebacks on scheduler restart. UNIQUE constraint still acts as safety net. |

#### Bugs fixed during Phase 3

| Issue | Root cause | Fix |
|-------|-----------|-----|
| Runs always show "completed" regardless of actual result | `_wait_for_task_completion()` hardcoded status as "completed" | Refactored to return `tuple[str, str | None, str | None]` (status, error_message, token_usage) from actual `ReactTask` + `ReactRecursion` records |
| Token usage not recorded on runs | `ReactTask` model has `total_prompt_tokens`/`total_completion_tokens`/`total_tokens`, not `token_usage` | Build JSON manually: `{"prompt": N, "completion": N, "total": N}` |
| Error message missing on failed runs | `ReactTask` has no `error_message` field | Query last failed `ReactRecursion` (status="error") and extract `error_log` |
| Pyright: `desc()` not found on `int` | `ReactRecursion.iteration_index` typed as `int`, pyright can't resolve `.desc()` | Wrapped with `col(ReactRecursion.iteration_index).desc()` |
| Scheduler IntegrityError spam on restart | `claim_run` INSERT fails when run already exists | Added SELECT for existing pending/running runs before INSERT; UNIQUE constraint kept as safety net |
| API missing `automation` field in session-trends | `analytics.py` endpoints manually constructed dicts with only `date`, `client`, `studio_test` | Added `"automation": item.automation` to both studio and agent session-trends endpoints |
| Tooltip not showing Automation value | Same root cause as above — frontend receives no `automation` field from API | Fixed by backend API serialization fix above |

#### Not yet implemented (remaining Phase 3)

- Dashboard KPI cards for automation stats (runs count, success rate, token usage)
- Extension hook support for automation lifecycle events
- Automation run result delivery (email, channel push, etc.)

**New backend files:**
- `server/app/models/automation.py`
- `server/app/services/automation_service.py`
- `server/app/services/automation_scheduler.py`
- `server/app/services/automation_executor.py`
- `server/app/schemas/automation.py`
- `server/app/api/client_automations.py`
- `server/app/orchestration/tool/builtin/propose_automation.py`

**New frontend files:**
- `web/src/client/ClientAutomationsView.tsx`
- `web/src/client/ClientAutomationDetailView.tsx`
- `web/src/components/AutomationCreateDialog.tsx`

**Modified files:**
- `server/app/config.py` — 4 automation settings
- `server/app/main.py` — router + scheduler lifecycle
- `server/app/models/__init__.py` — export new models
- `server/app/models/session.py` — session type docstring
- `server/app/orchestration/tool/manager.py` — renamed execute param to avoid collision
- `server/app/services/automation_service.py` — claim_run SELECT-before-INSERT dedup
- `server/app/services/automation_executor.py` — accurate run status propagation, error/token extraction
- `server/app/services/analytics_service.py` — `DailySessionCount` dataclass + `get_session_trends()`/`get_agent_session_trends()` 3-bucket logic
- `server/app/api/analytics.py` — added `automation` field to session-trends API responses
- `pyproject.toml` — added `croniter` dependency
- `web/src/client/api.ts` — automation types + API functions + `DailySessionCount` with `automation` field
- `web/src/client/ClientAgentsPage.tsx` — nav items + view toggle
- `web/src/client/ClientAutomationDetailView.tsx` — custom toast, clickable all-status runs, poll-based trigger feedback
- `web/src/components/analytics/SessionTrendChart.tsx` — 3-series stacked area chart (Client/Studio/Automation)
- `web/src/utils/api.ts` — `DailySessionCount` interface updated with `automation` field
- `web/src/pages/chat/ChatContainer.tsx` — agent fetch for dialog, pass agents prop
- `web/src/pages/chat/utils/actionHandlers.ts` — propose_automation handler registration
