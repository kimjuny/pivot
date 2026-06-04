# Chat Session Store

## 背景

Chat 页面现在有两类状态混在 `ChatContainer` 里：

1. Sidebar navigation cache：有哪些 session、project，如何排序和展示。
2. 当前 conversation runtime：当前 session 的 messages、task summaries、已加载 task、older pagination cursor、loading/exhausted 状态、SSE live refs、scroll pin 状态。

其中 sidebar 的 session list 目前是：

```ts
const [sessions, setSessions] = useState<SessionListItem[]>(initialSessions ?? []);
```

它是一份 flat array，用来渲染左侧导航。渲染前派生：

```ts
standaloneSessions = sessions.filter((session) => !session.project_id)

sidebarProjects = projects.map((project) => ({
  ...project,
  sessions: sessions.filter((session) => session.project_id === project.project_id),
}))
```

这份 store 只应该表达「sidebar 上有哪些 session 以及轻量 metadata」。它不适合承载 chat message pagination，因为 pagination 是某个 session 的 conversation runtime 状态，生命周期和 sidebar list 不同。

## 当前问题

Chat message pagination 的状态目前散落为多个 ref/state：

```ts
taskSummaries
loadedTaskIds
loadedTaskIdsRef
oldestLoadedTaskIdRef
hasMoreOlderRef
isLoadingOlderRef
```

这些字段表达的是同一个概念：当前 session 的 older history loading state。但因为它们不是一个统一模型，容易出现半状态：

- 新建 session 后 `hasMoreOlderRef` 没有被明确设为 exhausted。
- top sentinel 持续可见时，observer 可以反复触发 preload。
- `loadOlderTasks()` 收到空 page 后如果没有进入 exhausted，下一轮还会继续请求。
- 切换 session 时，cursor / loaded ids / summaries 需要在多个位置手动 reset。
- anchor navigation、scroll preload、initial history load 都会读写同一组状态，但没有统一不变量。

这些 bug 不应该通过 scrollTop、message count、新 session 等特例修复。更优雅的修复是把 conversation history pagination 建模成一个明确的 session-scoped store。

## 目标

建立一份 active-session chat runtime store，至少管理：

- 当前 session 的 task summaries。
- 哪些 tasks 已加载 full message data。
- older history cursor。
- older pagination 状态：uninitialized / idle / loading / exhausted。
- 当前 page size。

目标不是替代 sidebar session list，而是把 conversation runtime 从 sidebar metadata 中分离出来。

## 非目标

- 不把 full messages 持久化到 localStorage。
- 不把 chat runtime state 写入服务端。
- 不在 `SessionListItem` 上增加 `exhausted` 之类字段。
- 不用 page index 替代 cursor pagination。
- 不为「新 session」「第一条消息」「pinned user bubble」「某个 scrollTop」写特例。

## 推荐数据模型

### Session list store

继续保持 sidebar store 简洁：

```ts
type SessionListStore = {
  sessions: SessionListItem[];
  projects: ProjectResponse[];
};
```

它的职责：

- list sessions
- insert / update / delete sidebar row
- title / pinned / runtime_status metadata
- project grouping

它不关心 chat history 是否 exhausted。

### Chat session runtime store

新增 active-session runtime store：

```ts
type OlderHistoryStatus =
  | "uninitialized"
  | "idle"
  | "loading"
  | "exhausted";

type ChatSessionRuntime = {
  sessionId: string;
  taskSummaries: TaskSummary[];
  loadedTaskIds: Set<string>;
  oldestLoadedTaskId: string | null;
  olderStatus: OlderHistoryStatus;
  pageSize: number;
};

type ActiveChatSessionRuntime = ChatSessionRuntime | null;
```

第一阶段只维护当前打开的 session。用户切换到其他 session，或者离开 chat 页面进入 automations、agents、studio 等其他界面时，当前 runtime 直接释放。下一次重新进入该 session 时，通过 `getFullSessionHistory(sessionId, { limit })` 重新 hydrate。

这比一开始维护 `Map<sessionId, ChatSessionRuntime>` 更干净：

- runtime 只是 viewport/pagination 状态，不是持久数据源。
- 服务端 history + event log 才是 source of truth。
- 不需要处理跨 tab、automation、channel webhook、后台 task 对缓存造成的 stale state。
- 不需要 TTL、updated_at invalidation、last_event_id 对比等额外机制。
- 切 session 时不会出现 A/B session pagination 状态互相污染。

如果未来明确需要“切回 session 时保留之前加载到第几页”，再升级为可失效的 `Map<sessionId, ChatSessionRuntime>`。

## 为什么不用 page_index

当前后端分页接口是 cursor-based：

```http
GET /sessions/{session_id}/full-history?limit=10&before_task_id={task_id}
```

所以前端也应该维护 cursor：

```ts
oldestLoadedTaskId
```

而不是：

```ts
page_index
```

原因：

- 新 task 会追加到末尾，page index 容易漂移。
- task 可能停止、失败、恢复、重放，cursor 更稳定。
- `before_task_id` 能直接表达「从当前已加载最老 task 之前继续加载」。
- cursor 和 scroll prepend 的 mental model 一致。

## 为什么不用 exhausted boolean

可以有 `exhausted: boolean`，但它不够表达完整状态。

`exhausted = false` 可能表示：

- 还没有初始化，不知道能不能加载。
- 已初始化，确认还有 older data。
- 正在 loading。
- 没有 cursor，但还没标记 exhausted。

这些状态对 observer 的行为不同。更稳的是：

```ts
olderStatus: "uninitialized" | "idle" | "loading" | "exhausted"
```

加载条件变成一个清晰不变量：

```ts
canLoadOlder =
  runtime.olderStatus === "idle" &&
  runtime.oldestLoadedTaskId !== null
```

这样 top observer 不需要知道任何场景细节。

## 状态机

```text
uninitialized
  -> idle       initial history loaded, has_more_older = true, oldestLoadedTaskId exists
  -> exhausted initial history loaded, has_more_older = false
  -> exhausted brand-new session created from composer

idle
  -> loading   loadOlderTasks starts

loading
  -> idle       older page returned tasks and has_more_older = true
  -> exhausted  older page returned no tasks
  -> exhausted  older page returned has_more_older = false
  -> idle       request failed, keep previous cursor and allow retry

exhausted
  -> exhausted observer ignored
  -> uninitialized session explicitly reloaded from server
```

Key rule:

```ts
empty page means exhausted
```

This should be true even if the backend accidentally returns `has_more_older: true` with an empty task list. Without a cursor and without tasks, the frontend has no meaningful next request.

## Runtime actions

Use reducer-style actions instead of ad-hoc ref assignments.

```ts
type ChatSessionRuntimeAction =
  | { type: "RESET_DRAFT" }
  | { type: "INIT_SESSION"; sessionId: string }
  | {
      type: "HYDRATE_HISTORY";
      sessionId: string;
      taskSummaries: TaskSummary[];
      loadedTaskIds: string[];
      oldestLoadedTaskId: string | null;
      hasMoreOlder: boolean;
      pageSize: number;
    }
  | { type: "START_LOAD_OLDER"; sessionId: string }
  | {
      type: "APPLY_OLDER_PAGE";
      sessionId: string;
      tasks: TaskMessage[];
      hasMoreOlder: boolean;
    }
  | {
      type: "REGISTER_NEW_TASK";
      sessionId: string;
      task: TaskSummary;
      isBrandNewSession: boolean;
      pageSize: number;
    }
  | { type: "FAIL_LOAD_OLDER"; sessionId: string };
```

The reducer owns these invariants:

```ts
oldestLoadedTaskId = first loaded task id or null
olderStatus = "idle" only when hasMoreOlder && oldestLoadedTaskId !== null
olderStatus = "exhausted" when no older page can be requested
loadedTaskIds contains every task currently rendered as full messages
```

## Action semantics

### RESET_DRAFT

Used when entering blank composer state.

```ts
currentSessionId = null
currentRuntime = null
```

No session id means no older pagination.

### INIT_SESSION

Used when selecting or creating a session before history is known.

```ts
{
  sessionId,
  taskSummaries: [],
  loadedTaskIds: new Set(),
  oldestLoadedTaskId: null,
  olderStatus: "uninitialized",
  pageSize: 10,
}
```

### HYDRATE_HISTORY

Used after:

```ts
getFullSessionHistory(sessionId, { limit })
```

Reducer logic:

```ts
const oldestLoadedTaskId = tasks[0]?.task_id ?? null;

olderStatus =
  hasMoreOlder && oldestLoadedTaskId !== null
    ? "idle"
    : "exhausted";
```

This handles:

- existing session with older pages
- existing session with no older pages
- empty session
- requested session after refresh

### START_LOAD_OLDER

Allowed only if:

```ts
olderStatus === "idle" && oldestLoadedTaskId !== null
```

Reducer:

```ts
olderStatus = "loading"
```

### APPLY_OLDER_PAGE

Used after:

```ts
getFullSessionHistory(sessionId, {
  limit,
  beforeTaskId: previous.oldestLoadedTaskId,
})
```

If response has no tasks:

```ts
olderStatus = "exhausted"
```

If response has tasks:

```ts
loadedTaskIds = union(response.tasks.map(task => task.task_id), loadedTaskIds)
oldestLoadedTaskId = response.tasks[0].task_id
olderStatus =
  response.has_more_older
    ? "idle"
    : "exhausted"
```

### REGISTER_NEW_TASK

Used after `startReactTask()` returns a real `task_id`.

For an existing loaded session:

```ts
taskSummaries = append summary
loadedTaskIds.add(task_id)
oldestLoadedTaskId stays unchanged
olderStatus stays unchanged
```

For a brand-new session created from composer:

```ts
taskSummaries = [summary]
loadedTaskIds = new Set([task_id])
oldestLoadedTaskId = task_id
olderStatus = "exhausted"
```

This is not a special visual case. It is a domain invariant: a just-created session cannot have older history before its first task.

### FAIL_LOAD_OLDER

Network/API failures should not mark exhausted. They should allow retry:

```ts
olderStatus = previous.oldestLoadedTaskId ? "idle" : "exhausted"
```

## Hook shape

Recommended extraction:

```ts
function useChatSessionRuntime() {
  const [runtime, dispatch] = useReducer(reducer, null);

  return {
    runtime,
    dispatch,
    canLoadOlder: runtime?.olderStatus === "idle" &&
      runtime.oldestLoadedTaskId !== null,
  };
}
```

The first implementation does not have to cache full `messages` per session. It can cache only pagination metadata:

```ts
taskSummaries
loadedTaskIds
oldestLoadedTaskId
olderStatus
pageSize
```

`messages` can remain current-session state until there is a product need to preserve loaded pages across session switches.

## Integration points

### Enter draft

Current:

```ts
setCurrentSessionId(null)
commitMessages([])
setTaskSummaries([])
setLoadedTaskIds(new Set())
oldestLoadedTaskIdRef.current = null
hasMoreOlderRef.current = false
```

Target:

```ts
runtimeStore.dispatch({ type: "RESET_DRAFT" })
setCurrentSessionId(null)
commitMessages([])
```

### Select existing session

Current:

```ts
setTaskSummaries([])
setLoadedTaskIds(new Set())
oldestLoadedTaskIdRef.current = null
hasMoreOlderRef.current = false
isLoadingOlderRef.current = false

const history = await getFullSessionHistory(sessionId, { limit: 10 })
loadHistoryResponse(history, true)
```

Target:

```ts
runtimeStore.dispatch({ type: "INIT_SESSION", sessionId })

const history = await getFullSessionHistory(sessionId, { limit: pageSize })

runtimeStore.dispatch({
  type: "HYDRATE_HISTORY",
  sessionId,
  taskSummaries: history.task_summaries,
  loadedTaskIds: history.tasks.map((task) => task.task_id),
  oldestLoadedTaskId: history.tasks[0]?.task_id ?? null,
  hasMoreOlder: history.has_more_older,
  pageSize,
})
```

### Create session from composer

Current flow:

```text
POST /sessions
openSessionStream(sessionId, 0)
optimistic messages
POST /react/tasks
canonicalize ids
append task summary
loadedTaskIds.add(task_id)
```

Target runtime updates:

```ts
dispatch({ type: "INIT_SESSION", sessionId })

// after startReactTask returns
dispatch({
  type: "REGISTER_NEW_TASK",
  sessionId,
  task: {
    task_id: launchResult.task_id,
    preview: pendingMessage.trim().slice(0, 100),
    status: "running",
    created_at: new Date().toISOString(),
  },
  isBrandNewSession: true,
  pageSize,
})
```

Result:

```ts
olderStatus = "exhausted"
oldestLoadedTaskId = launchResult.task_id
```

So top observer is harmless:

```ts
canLoadOlder === false
```

### Load older by scroll

Target:

```ts
if (!runtime || runtime.olderStatus !== "idle" || !runtime.oldestLoadedTaskId) {
  return [];
}

dispatch({ type: "START_LOAD_OLDER", sessionId })

try {
  const history = await getFullSessionHistory(sessionId, {
    limit: runtime.pageSize,
    beforeTaskId: runtime.oldestLoadedTaskId,
  })

  dispatch({
    type: "APPLY_OLDER_PAGE",
    sessionId,
    tasks: history.tasks,
    hasMoreOlder: history.has_more_older,
  })
} catch {
  dispatch({ type: "FAIL_LOAD_OLDER", sessionId })
}
```

### Round anchor

`useConversationRounds` should read:

```ts
useConversationRounds(
  activeRuntime.taskSummaries,
  activeRuntime.loadedTaskIds,
)
```

Unloaded rounds are normal:

```ts
round.isLoaded === false
```

The navigation path asks runtime to load until task:

```ts
loadUntilTask(round.taskId)
```

No special handling for skeletons, scroll, or new session is needed.

## Observer contract

`useScrollUpPagination` should not own domain state. It should only say:

```ts
top sentinel is visible
```

And call:

```ts
loadOlderTasks()
```

`loadOlderTasks()` then checks:

```ts
runtime.olderStatus === "idle"
runtime.oldestLoadedTaskId !== null
```

If not, it returns immediately without network.

This keeps observer generic and prevents UI mechanics from leaking into pagination semantics.

## Backend contract

The frontend state machine assumes:

```ts
FullSessionHistoryResponse = {
  task_summaries: TaskSummary[];
  tasks: TaskMessage[];
  has_more_older: boolean;
}
```

Frontend rule:

```ts
if (tasks.length === 0) olderStatus = "exhausted"
```

Backend rule:

```ts
has_more_older === true only when there exists at least one task older than the returned oldest task
```

Even if the backend has a bug or a race, empty page still wins on the frontend.

## Minimal implementation plan

### Phase 1: Introduce current-session runtime reducer

Create:

```ts
web/src/pages/chat/hooks/useChatSessionRuntime.ts
```

Start with current-session state, not cross-session Map:

```ts
ChatSessionRuntime | null
```

This removes scattered refs without adding cross-session cache complexity.

### Phase 2: Replace scattered pagination refs

Replace:

```ts
taskSummaries
loadedTaskIds
loadedTaskIdsRef
oldestLoadedTaskIdRef
hasMoreOlderRef
isLoadingOlderRef
```

with:

```ts
runtime.taskSummaries
runtime.loadedTaskIds
runtime.oldestLoadedTaskId
runtime.olderStatus
```

### Phase 3: Move loadOlderTasks onto runtime semantics

Update load guard:

```ts
if (runtime.olderStatus !== "idle" || !runtime.oldestLoadedTaskId) return [];
```

Update empty response:

```ts
dispatch({ type: "APPLY_OLDER_PAGE", tasks: [], hasMoreOlder: false })
```

### Phase 4: Register new task through runtime

After `startReactTask`, dispatch `REGISTER_NEW_TASK`.

For brand-new session, reducer sets:

```ts
olderStatus = "exhausted"
```

### Phase 5: Optional session-id keyed Map

Once current-session reducer is stable, upgrade to:

```ts
Map<string, ChatSessionRuntime>
```

Only do this if we want to preserve loaded pagination state across session switches. Otherwise active-session runtime is simpler and sufficient.

If this upgrade happens, it must include invalidation metadata:

```ts
cachedUpdatedAt
hydratedAt
lastEventId
```

Without invalidation, a `Map` would look elegant but silently preserve stale runtime state.

## Verification scenarios

1. New chat -> send first message.
   - Runtime becomes exhausted after task starts.
   - Top sentinel may intersect.
   - No older history request is sent.

2. Existing short session with fewer than page size tasks.
   - Initial history returns `has_more_older = false`.
   - Runtime becomes exhausted.
   - No repeated preload.

3. Existing long session.
   - Initial history returns latest N tasks and `has_more_older = true`.
   - Runtime is idle with `oldestLoadedTaskId`.
   - Scroll near top loads one older page.

4. Older page returns empty tasks.
   - Runtime becomes exhausted.
   - Observer stops causing network requests.

5. Older page returns non-empty tasks and no more older.
   - Messages prepend once.
   - Runtime becomes exhausted.

6. Older page request fails.
   - Runtime returns to idle if cursor still exists.
   - User can retry by scrolling / anchor navigation.

7. Anchor click to unloaded round.
   - Runtime loads older pages until target task is loaded or exhausted.
   - No scroll-specific pagination flags.

## Design conclusion

The elegant fix is not `setExhausted(true/false)` as a loose boolean, and not adding guards around scroll behavior.

The elegant fix is:

```text
Sidebar session list remains a sidebar metadata cache.
Chat history pagination becomes a session-scoped runtime state machine.
Observer only triggers intent.
Runtime state decides whether network is allowed.
Empty page and has_more_older=false both converge to exhausted.
Brand-new sessions start exhausted because no older history can exist.
```

This gives the code one durable invariant:

```ts
olderStatus === "idle" && oldestLoadedTaskId !== null
```

is the only state in which older history may be requested.
