# Session History — Studio Operations

## Problem

After an agent is published, administrators have zero visibility into how it
performs in production. They cannot answer basic questions:

- How many users are interacting with this agent?
- Are sessions succeeding or failing?
- What happened in a specific user's conversation that led to a complaint?

The Operations module currently redirects to the Dashboard placeholder. Session
History is the first concrete page to fill this gap.

## Core Use Case

> An administrator opens Studio → Operations → Session History.
> They see a table of all Consumer sessions, sorted by most recent activity.
> They filter by a specific agent and notice several sessions with `error` status.
> They click into one session and see the full read-only conversation.
> They discover the agent repeatedly failed on a specific tool call.
> They go back to the agent workspace to fix the tool configuration.

## Scope — First Version

### In scope

- A list page showing all Consumer sessions across all users and all agents
- Filtering by agent, status, and session type
- Client-side pagination
- A detail page rendering the full conversation history in read-only mode

### Explicitly out of scope

- Real-time monitoring or WebSocket push
- Token usage or cost analytics
- Independent tool execution log page
- Session tagging or categorization
- Assignment or audience targeting

## Data Model — What Already Exists

### Session table (`server/app/models/session.py`)

Key fields for the list page:

| Field | Type | Use |
|-------|------|-----|
| `session_id` | str (UUID) | Primary identifier |
| `agent_id` | int (FK) | Which agent |
| `type` | str | `consumer` or `studio_test` |
| `release_id` | int or None | Pinned release |
| `test_snapshot_id` | int or None | Studio test snapshot |
| `user` | str | Username |
| `status` | str | `active`, `waiting_input`, `closed` |
| `title` | str or None | Session display name |
| `created_at` | datetime | Session start |
| `updated_at` | datetime | Last activity |

### ReactTask table (`server/app/models/react.py`)

Key fields for the detail page:

| Field | Type | Use |
|-------|------|-----|
| `task_id` | str (UUID) | Task identifier |
| `session_id` | str (UUID) | Parent session |
| `user_message` | str | What the user asked |
| `status` | str | `pending`, `running`, `completed`, `failed`, `cancelled` |
| `iteration` | int | Recursion depth reached |
| `total_tokens` | int or None | Token cost |
| `created_at` | datetime | Task start |
| `updated_at` | datetime | Task end |

### ReactRecursion table

Contains per-step reasoning traces, tool calls, and their results. Already
serialized by the existing full-history endpoint.

## Existing Infrastructure to Reuse

### Backend

| What | Where | Status |
|------|-------|--------|
| Session CRUD | `server/app/crud/session.py` | Exists |
| Session service | `server/app/services/session_service.py` | Exists, but scoped to one user |
| Session API routes | `server/app/api/session.py` | Exists, but filters by `current_user` |
| Full-history endpoint | `GET /sessions/{id}/full-history` | Exists, returns tasks + recursions |
| History transformation | `server/app/schemas/session.py` | `FullSessionHistoryResponse`, `TaskMessage`, `RecursionDetail` |

### Frontend

| What | Where | Status |
|------|-------|--------|
| Session list API | `web/src/utils/api.ts` → `listSessions()` | Exists, user-scoped |
| Full-history API | `web/src/utils/api.ts` → `getFullSessionHistory()` | Exists, user-scoped |
| History → UI transform | `web/src/pages/chat/utils/chatData.ts` → `buildMessagesFromHistory()` | Exists |
| Conversation renderer | `web/src/pages/chat/components/ConversationView.tsx` | Exists |
| User message bubble | `web/src/pages/chat/components/` → `UserMessageBubble` | Exists |
| Assistant message block | `web/src/pages/chat/components/AssistantMessageBlock.tsx` | Exists |

## Implementation Plan

### Phase 1 — Backend: Studio Operations session list endpoint

**New file:** `server/app/api/operations.py`

**New endpoint:**

```
GET /api/studio/operations/sessions
```

Query parameters:

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `agent_id` | int or None | None | Filter by agent |
| `status` | str or None | None | Filter by status |
| `session_type` | str or None | None | `consumer` or `studio_test` |
| `page` | int | 1 | Page number |
| `page_size` | int | 20 | Items per page |

Response shape:

```json
{
  "sessions": [
    {
      "session_id": "uuid",
      "agent_id": 1,
      "agent_name": "Customer Bot",
      "release_id": 3,
      "release_version": 2,
      "type": "consumer",
      "user": "alice",
      "status": "closed",
      "title": "Help with refund",
      "task_count": 4,
      "created_at": "2026-03-28T10:00:00Z",
      "updated_at": "2026-03-28T10:12:00Z"
    }
  ],
  "total": 142,
  "page": 1,
  "page_size": 20
}
```

**Implementation notes:**

- The endpoint does NOT filter by `current_user`. It is admin-scoped.
- `agent_name` comes from a join or secondary lookup on the `agent` table.
- `release_version` comes from a join or secondary lookup on the
  `agent_release` table, matching the pattern already used in
  `_serialize_agent_response` in `agents.py`.
- `task_count` comes from counting `ReactTask` rows per session.
- Use server-side pagination (OFFSET/LIMIT) rather than loading all sessions.
- The service method should live in `session_service.py` as
  `list_sessions_for_operations()`.

**Service method:**

```python
def list_sessions_for_operations(
    self,
    *,
    agent_id: int | None = None,
    status: str | None = None,
    session_type: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Session], int]:
```

This returns `(sessions, total_count)` for pagination metadata.

### Phase 2 — Backend: Studio Operations session detail endpoint

**New endpoint:**

```
GET /api/studio/operations/sessions/{session_id}
```

Response shape:

```json
{
  "session": {
    "session_id": "uuid",
    "agent_id": 1,
    "agent_name": "Customer Bot",
    "release_version": 2,
    "type": "consumer",
    "user": "alice",
    "status": "closed",
    "title": "Help with refund",
    "created_at": "...",
    "updated_at": "..."
  },
  "tasks": [ ... same as FullSessionHistoryResponse.tasks ... ]
}
```

**Implementation notes:**

- This reuses the existing `get_full_session_history()` logic from
  `session_service.py` but removes the `current_user` ownership check.
- The admin endpoint should verify that the requesting user has Studio access
  but should NOT restrict by `session.user`.

### Phase 3 — Frontend: Session History list page

**New file:** `web/src/studio/operations/SessionHistoryPage.tsx`

**Route:** `/studio/operations/sessions`

**Update route in `main.tsx`:**

```tsx
// Change:
<Route path="/studio/operations" element={<Navigate to="/studio/dashboard" replace />} />
// To:
<Route path="/studio/operations" element={<Navigate to="/studio/operations/sessions" replace />} />
<Route path="/studio/operations/sessions" element={<SessionHistoryPage />} />
<Route path="/studio/operations/sessions/:sessionId" element={<SessionDetailPage />} />
```

**Page layout:**

```
┌──────────────────────────────────────────────────┐
│  Session History                                 │
│  All consumer and test session activity          │
│                                                  │
│  [Agent ▾]  [Status ▾]  [Type ▾]                │
│                                                  │
│  Agent        User    Title    Status   Version  │
│  ─────────────────────────────────────────────── │
│  Customer Bot alice   Refund..  closed   v2      │
│  Sales Bot    bob     Quoter..  active   v1      │
│  Customer Bot carol   How do..  error    v2      │
│  ...                                             │
│                                                  │
│  Showing 1-20 of 142        < 1 2 3 ... 8 >     │
└──────────────────────────────────────────────────┘
```

**Data fetching pattern:** Follow `AgentList.tsx` style:

- `useState` for `sessions`, `loading`, `error`, `page`, filters
- `useCallback` for `loadSessions()`
- Server-side pagination (page + page_size query params)

**API module:** `web/src/studio/operations/api.ts`

```typescript
interface OperationsSession {
  session_id: string;
  agent_id: number;
  agent_name: string;
  release_id: number | null;
  release_version: number | null;
  type: "consumer" | "studio_test";
  user: string;
  status: string;
  title: string | null;
  task_count: number;
  created_at: string;
  updated_at: string;
}

interface OperationsSessionListResponse {
  sessions: OperationsSession[];
  total: number;
  page: number;
  page_size: number;
}
```

**Filters:**

Three dropdown selects at the top of the page:

1. **Agent** — populated from the existing `getAgents()` API
2. **Status** — static list: `active`, `waiting_input`, `closed`
3. **Type** — static list: `consumer`, `studio_test`

No full-text search in the first version.

**Table component:** Use shadcn `Table` from `web/src/components/ui/table.tsx`.

### Phase 4 — Frontend: Session Detail page

**New file:** `web/src/studio/operations/SessionDetailPage.tsx`

**Route:** `/studio/operations/sessions/:sessionId`

**Page layout:**

```
┌──────────────────────────────────────────────────┐
│  ← Back to Session History                      │
│                                                  │
│  ┌─────────────────────────────────────────────┐ │
│  │ Customer Bot    alice    v2    closed        │ │
│  │ "Help with refund request"                   │ │
│  │ Mar 28 10:00 — Mar 28 10:12    4 tasks      │ │
│  └─────────────────────────────────────────────┘ │
│                                                  │
│  ┌─ Conversation ─────────────────────────────┐ │
│  │                                             │ │
│  │  👤 alice                                   │ │
│  │  I need help processing a refund for...     │ │
│  │                                             │ │
│  │  🤖 Customer Bot                           │ │
│  │  I'll help you with that refund. Let me...  │ │
│  │  [▶ Show reasoning trace]                  │ │
│  │                                             │ │
│  │  👤 alice                                   │ │
│  │  The order number is...                     │ │
│  │                                             │ │
│  │  🤖 Customer Bot                           │ │
│  │  ❌ Error: Tool call failed — timeout      │ │
│  │                                             │ │
│  └────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────┘
```

**Implementation approach:**

1. Fetch session detail from the new Operations endpoint
2. Transform the `tasks` array using the existing
   `buildMessagesFromHistory()` from `chatData.ts`
3. Render using `ConversationView` from the chat module
4. Disable all interactive elements:
   - No input box
   - No "reply" buttons
   - No "approve/reject" skill change buttons
   - Recursion expand/collapse should still work

**How to achieve read-only mode:**

The simplest approach is to pass `ConversationView` without connecting it to
a session controller. Since `ConversationView` is a pure presentational
component that takes `messages` as a prop, it will render without any
interactive capability as long as no `onReplyTask` or session actions are
wired up.

Specifically:

```tsx
<ConversationView
  messages={messages}
  agentName={session.agent_name}
  expandedRecursions={expandedRecursions}
  isStreaming={false}
  onToggleRecursion={toggleRecursion}
  onReplyTask={() => {}}
  onApproveSkillChange={() => {}}
  onRejectSkillChange={() => {}}
/>
```

The key point: do NOT wrap the detail page in any chat session context or
controller. It is a pure data-fetching page that renders pre-built messages.

### Phase 5 — Navigation update

**Update the sidebar navigation in the Studio layout** so that `Operations`
has a second-level entry for `Session History`.

The current navigation already has `Operations` as a top-level group. Add
`Session History` as a visible entry within it.

## File Change Summary

### New files

| File | Purpose |
|------|---------|
| `server/app/api/operations.py` | Studio Operations API endpoints |
| `web/src/studio/operations/SessionHistoryPage.tsx` | Session list page |
| `web/src/studio/operations/SessionDetailPage.tsx` | Session detail page |
| `web/src/studio/operations/api.ts` | Operations API module |

### Modified files

| File | Change |
|------|--------|
| `server/app/main.py` | Register `operations` router |
| `server/app/services/session_service.py` | Add `list_sessions_for_operations()` |
| `web/src/main.tsx` | Add Operations session routes |
| Studio navigation component | Add Session History entry |

## Implementation Order

1. Backend service method (`list_sessions_for_operations`)
2. Backend API endpoint (`/api/studio/operations/sessions`)
3. Backend detail endpoint (`/api/studio/operations/sessions/{id}`)
4. Frontend API module (`web/src/studio/operations/api.ts`)
5. Frontend list page (`SessionHistoryPage.tsx`)
6. Frontend detail page (`SessionDetailPage.tsx`)
7. Route and navigation wiring

## Verification

1. Backend type check: `podman compose exec backend poetry run pyright server`
2. Backend lint: `podman compose exec backend poetry run ruff check server --fix`
3. Frontend type check: `podman compose exec frontend npm run type-check`
4. Frontend lint: `podman compose exec frontend npm run lint`
5. Manual: open `/studio/operations/sessions`, verify list renders
6. Manual: click a session row, verify conversation renders in read-only mode
7. Manual: verify filters work (agent, status, type)
8. Manual: verify pagination works for datasets > 20 sessions
