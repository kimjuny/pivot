# Frontend State Management Design

## Agent Detail Page Data Flow

The Agent Detail page implements a sophisticated three-state data management system to support viewing, editing, and previewing agent configurations.

### Three Core States

#### 1. Server State (`originalAgent` in `agentWorkStore`)

**Purpose**: Represents the source of truth from the backend database.

**Lifecycle**:
- **Initialization**: Loaded when the user navigates to the agent detail page via API call
- **Updates**: Only updated after successful submission to the server
- **Immutability**: Should be treated as read-only in the UI; serves as the baseline for comparison

**Usage**:
- Compare with `workspaceAgent` to detect unsaved changes
- Restore point when user discards changes

---

#### 2. Editing State (`workspaceAgent` in `agentWorkStore`)

**Purpose**: User's working copy for editing the agent configuration.

**Lifecycle**:
- **Initialization**: Deep copy of `originalAgent` when page loads
- **Updates**: Modified when user:
  - Manually edits the graph (add/remove/update subscenes, connections)
  - Adds/removes scenes
  - Applies changes from Build Mode
- **Persistence**: Changes remain local until user submits or discards

**Change Detection**:
- Triggers `hasUnsavedChanges` flag when `workspaceAgent !== originalAgent`
- Shows Submit Area at the bottom of the page

**User Actions**:
- **Submit**: Send changes to server → Update both `originalAgent` and `workspaceAgent` with server response
- **Discard**: Reset `workspaceAgent` to match `originalAgent`

---

#### 3. Preview State (`previewAgent` in `agentWorkStore`)

**Purpose**: Snapshot for simulating conversations and observing state flow evolution.

**Lifecycle**:
- **Initialization**: Deep copy of `workspaceAgent` when user enters Preview Mode
- **Updates**: 
  - **During chat**: Backend SSE events (`UPDATED_SCENES`) update `previewAgent.scenes` to reflect subscene state changes (active/inactive)
  - **Important**: These updates are preview-only and do NOT affect `workspaceAgent`
- **Cleanup**: Discarded when user exits Preview Mode

**Rendering**:
- When in Preview Mode, the graph visualization reads from `previewAgent` (not `workspaceAgent`)
- This allows real-time state updates during conversation simulation
- Graph should instantly revert to `workspaceAgent` when exiting Preview Mode

---

## Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        Agent Detail Page                         │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │   Load from Server     │
                    │   (API: GET /agent/6)  │
                    └────────────┬───────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │   originalAgent ← DATA │  (State A: Server State)
                    │   workspaceAgent ← deepCopy(originalAgent)
                    └────────────┬───────────┘
                                 │
                                 │
                    ┌────────────▼───────────────────────────┐
                    │         User Editing Mode              │
                    │                                        │
                    │  ┌──────────────────────────────────┐ │
                    │  │  workspaceAgent (State B: Edit)  │ │
                    │  │                                  │ │
                    │  │  - Add/Remove Scenes            │ │
                    │  │  - Edit Subscenes/Connections   │ │
                    │  │  - Apply from Build Mode        │ │
                    │  └──────────────────────────────────┘ │
                    │                                        │
                    │  Compare: workspaceAgent vs originalAgent
                    │  ↓                                     │
                    │  hasUnsavedChanges = true/false       │
                    │                                        │
                    │  Actions:                              │
                    │  ┌─────────────┐  ┌──────────────┐   │
                    │  │   Submit    │  │   Discard    │   │
                    │  └──────┬──────┘  └──────┬───────┘   │
                    │         │                 │            │
                    │         ▼                 ▼            │
                    │  Update Server    workspaceAgent ← originalAgent
                    │         │                              │
                    │         ▼                              │
                    │  originalAgent ← Server Response       │
                    │  workspaceAgent ← originalAgent        │
                    └────────────────────────────────────────┘
                                 │
                                 │ User clicks "Preview"
                                 ▼
                    ┌────────────────────────────────────────┐
                    │         Preview Mode                   │
                    │                                        │
                    │  ┌──────────────────────────────────┐ │
                    │  │ previewAgent ← deepCopy(workspaceAgent)
                    │  │          (State C: Preview)      │ │
                    │  └──────────────────────────────────┘ │
                    │                                        │
                    │  Graph renders from: previewAgent     │
                    │                                        │
                    │  ┌───────────────────────────────┐   │
                    │  │   User Chats with Agent       │   │
                    │  │   ↓                           │   │
                    │  │   Backend SSE: UPDATED_SCENES │   │
                    │  │   ↓                           │   │
                    │  │   Update previewAgent.scenes  │   │
                    │  │   (subscene states change)    │   │
                    │  │   ↓                           │   │
                    │  │   Graph re-renders with       │   │
                    │  │   active/inactive states      │   │
                    │  └───────────────────────────────┘   │
                    │                                        │
                    │  Exit Preview:                        │
                    │  - Graph instantly reverts to         │
                    │    rendering workspaceAgent           │
                    │  - previewAgent is cleared            │
                    └────────────────────────────────────────┘
```

---

## Key Implementation Rules

### Rule 1: State Isolation
- Each state (A/B/C) must be independent
- Modifications to one state should NEVER directly affect others
- Use deep copy when creating new states

### Rule 2: Preview Mode Rendering
- **In Preview Mode**: Graph reads from `previewAgent`
- **In Edit Mode**: Graph reads from `workspaceAgent`
- State updates during preview (SSE events) only modify `previewAgent`, not `workspaceAgent`

### Rule 3: Change Detection
```typescript
hasUnsavedChanges = compareAgents(originalAgent, workspaceAgent)
```
- Only compare A (originalAgent) vs B (workspaceAgent)
- C (previewAgent) is irrelevant for change detection

### Rule 4: Server Sync
- After successful submission:
  ```typescript
  originalAgent = serverResponse
  workspaceAgent = deepCopy(originalAgent)
  hasUnsavedChanges = false
  ```

### Rule 5: Preview Updates
- When receiving `UPDATED_SCENES` SSE event:
  ```typescript
  previewAgent.scenes = event.updated_scenes
  ```
- This triggers graph re-render in preview mode
- Does NOT affect `workspaceAgent` or `originalAgent`

---

## Common Pitfalls to Avoid

❌ **Wrong**: Updating `workspaceAgent` during preview chat
```typescript
// DON'T DO THIS
case StreamEventType.UPDATED_SCENES:
  workspaceAgent.scenes = event.updated_scenes // ❌ Wrong!
```

✅ **Correct**: Update `previewAgent` only
```typescript
// DO THIS
case StreamEventType.UPDATED_SCENES:
  previewAgent.scenes = event.updated_scenes // ✅ Correct!
```

---

❌ **Wrong**: Reading from local component state in Preview Mode
```typescript
// DON'T DO THIS
const currentGraph = mode === 'preview' ? localStateGraph : workspaceGraph
```

✅ **Correct**: Read from store's `previewAgent`
```typescript
// DO THIS
const currentGraph = mode === 'preview' 
  ? previewAgent?.scenes?.find(s => s.id === currentSceneId)
  : workspaceAgent?.scenes?.find(s => s.id === currentSceneId)
```

---

## Related Files

- **Store**: `web/src/store/agentWorkStore.ts`
- **Component**: `web/src/components/AgentDetail.tsx`
- **Chat Store** (Preview): `web/src/store/previewChatStore.ts`
- **Utilities**: `web/src/utils/compare.ts`

---

## Maintenance Notes

When modifying agent detail page functionality, always ask:
1. Which state (A/B/C) should this change affect?
2. Am I maintaining proper isolation between states?
3. Does the graph render the correct state based on current mode?
4. Are SSE updates only affecting preview state?

Following these principles ensures a clean, predictable user experience.
