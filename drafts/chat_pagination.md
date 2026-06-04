# Chat Messages Pagination

## Problem

Opening a Session loads ALL historical Messages at once. For long sessions this is slow and wasteful.

## Design

- Initial load: fetch only the last 5 Tasks (matches RoundAnchor `WINDOW_SIZE = 5`).
- Anchor user to the last Task (auto-scroll-to-bottom already does this; just stop loading everything above).
- Scroll up near top → load 5 more older Tasks.
- Click topmost anchor dot for an unloaded round → load 3 older Tasks (matches the anchor window shift-by-3 behavior).

## 1. Backend API

**Endpoint**: `GET /sessions/{session_id}/full-history` (modify existing)

**New query params**:
- `limit: int = 5` — number of full tasks to return
- `before_task_id: str | null = null` — cursor: load tasks older than this task

**New schema**:
```python
class TaskSummary(AppBaseModel):
    task_id: str
    preview: str       # user_message[:100]
    status: str
    created_at: str
```

**Modified response**:
```python
class FullSessionHistoryResponse(AppBaseModel):
    session_id: str
    total_task_count: int              # NEW
    has_more_older: bool               # NEW
    task_summaries: list[TaskSummary]  # NEW — always returned, lightweight
    tasks: list[TaskMessage]           # paginated, ASC order
    last_event_id: int = 0
    resume_from_event_id: int = 0
```

**Service query logic**:
- No cursor → `ORDER BY created_at DESC LIMIT N` → reverse to ASC
- With cursor → `WHERE created_at < cursor_task.created_at ORDER BY created_at DESC LIMIT N` → reverse to ASC
- `total_task_count`: `SELECT COUNT(*) WHERE session_id = ?`
- `task_summaries`: always query all tasks, but only `task_id, user_message, status, created_at` (no recursions / files / attachments)
- `has_more_older`: `SELECT 1 WHERE created_at < oldest_returned.created_at LIMIT 1`

## 2. Frontend

### 2.1 Types & API (`utils/api/react.ts`)

```typescript
export interface TaskSummary {
  task_id: string;
  preview: string;
  status: string;
  created_at: string;
}

export interface FullSessionHistoryResponse {
  session_id: string;
  total_task_count: number;
  has_more_older: boolean;
  task_summaries: TaskSummary[];
  tasks: TaskMessage[];
  last_event_id: number;
  resume_from_event_id: number;
}

export const getFullSessionHistory = async (
  sessionId: string,
  options?: { limit?: number; beforeTaskId?: string },
): Promise<FullSessionHistoryResponse> => {
  const params = new URLSearchParams();
  if (options?.limit) params.set("limit", String(options.limit));
  if (options?.beforeTaskId) params.set("before_task_id", options.beforeTaskId);
  const qs = params.toString();
  return apiRequest(`/sessions/${sessionId}/full-history${qs ? `?${qs}` : ""}`);
};
```

### 2.2 ChatContainer pagination state

```typescript
const [taskSummaries, setTaskSummaries] = useState<TaskSummary[]>([]);
const loadedTaskIdsRef = useRef<Set<string>>(new Set());
const oldestLoadedTaskIdRef = useRef<string | null>(null);
const hasMoreOlderRef = useRef(false);
const isLoadingOlderRef = useRef(false);
```

Refs (not state) for commandive pagination logic — no re-renders needed.

### 2.3 Init flow (initSessions / handleSelectSession)

All existing `getFullSessionHistory` calls unified to:

```typescript
const history = await getFullSessionHistory(sessionId, { limit: 5 });
setTaskSummaries(history.task_summaries);
loadedTaskIdsRef.current = new Set(history.tasks.map(t => t.task_id));
oldestLoadedTaskIdRef.current = history.tasks[0]?.task_id ?? null;
hasMoreOlderRef.current = history.has_more_older;
const nextMessages = buildMessagesFromHistory(history.tasks);
applyHistoryMessages(nextMessages);
```

Session switch resets all pagination state.

### 2.4 Scroll-up pagination

Detect `scrollTop < threshold` → load older tasks → prepend → compensate scroll position:

```
oldScrollHeight = container.scrollHeight
→ fetch tasks
→ prepend olderMsgs before existing messages
→ container.scrollTop += (newScrollHeight - oldScrollHeight)
```

### 2.5 useConversationRounds refactor

Derive from `taskSummaries` instead of loaded messages. Add `isLoaded` flag:

```typescript
interface ConversationRound {
  taskId: string;
  userMessageId: string;   // "user-{task_id}"
  preview: string;
  roundNumber: number;
  isLoaded: boolean;
}

function useConversationRounds(
  taskSummaries: TaskSummary[],
  loadedTaskIds: Set<string>,
): ConversationRound[]
```

### 2.6 RoundAnchor

`onNavigateToRound` passes the round object. ChatContainer checks `round.isLoaded`:
- `true` → `scrollToMessage(messageId)` (unchanged)
- `false` → load (limit=3) then scroll

### 2.7 SSE new task → update summaries

On `task_start` event in `applyStreamEvent`:
```typescript
setTaskSummaries(prev => [...prev, { task_id, preview, status: "running", created_at }]);
loadedTaskIdsRef.current.add(event.task_id);
```

## 3. Unchanged

- `buildMessagesFromHistory` — pure function
- `scrollToMessage` / `scrollToMessageTop`
- SSE stream connection (cursor / reconnect)
- `ConversationView` / `UserMessageBubble` / `AssistantMessageBlock`
- `CompactStatusPill` / `ChatComposer`

## 4. Implementation steps

1. Backend: `TaskSummary` schema + modify `FullSessionHistoryResponse` (`schemas/session.py`)
2. Backend: `SessionService` add summaries query + pagination (`services/session_service.py`)
3. Backend: API endpoint add `limit` / `before_task_id` params (`api/session.py`)
4. Frontend: API types + `getFullSessionHistory` params (`utils/api/react.ts`)
5. Frontend: `useConversationRounds` from summaries (`hooks/useConversationRounds.ts`)
6. Frontend: `ChatContainer` pagination state + init flow
7. Frontend: scroll-up detection + pagination loading + scroll compensation
8. Frontend: `RoundAnchor` round passing + unloaded round handling
