# Open Problems & Design Debt

## 1. Tool → Frontend Action Channel: Unified `pivot_action` Protocol

**Status**: Resolved (Phase 1 — dual-key coexistence)
**Discovered**: 2026-05-24
**Resolved**: 2026-05-24
**Context**: Automation feature design discussion

### Solution

Introduced a unified `pivot_action` envelope that tools include in their return dicts:

```python
"pivot_action": {
    "type": str,       # unique action identifier
    "category": str,   # "notify" (fire-and-forget) or "approval" (pause engine)
    "payload": { ... }, # action-type-specific data
}
```

**Engine**: `_extract_pivot_action_from_tool_results()` replaces `_extract_pending_user_action_from_tool_results()`. Checks `pivot_action` first, falls back to legacy `pending_user_action` for backward compat. The `category` field determines whether the engine pauses (`"approval"`) or continues (`"notify"`).

**Frontend**: Handler registry at `web/src/pages/chat/utils/actionHandlers.ts`. Built-in handlers for `open_workspace_web_preview` and `skill_change_approval`. Adding a new action type requires only: (a) tool constructing the payload, (b) calling `registerActionHandler()`.

**Migration**: Both tools (`create_preview_endpoint`, `submit_skill_change`) now emit both the legacy key and `pivot_action`. The supervisor dispatches by `type` field. Legacy keys can be removed in a future Phase 2.

### Remaining (Phase 2)

- Remove `ui_intent` from `create_preview_endpoint` once frontend fully uses `pivot_action`
- Remove `pending_user_action` from `skill_change_service` once engine no longer needs fallback
- Remove `extractWorkspacePreviewIntent` from `ChatContainer.tsx`
- Remove `_extract_pending_user_action_from_tool_results` legacy path from engine

### Affected Files

- `server/app/orchestration/react/engine.py` — `_extract_pivot_action_from_tool_results()`, updated clarify event, generic `_compact_result_for_llm` stripping
- `server/app/orchestration/tool/builtin/create_preview_endpoint.py` — emits `pivot_action` alongside `ui_intent`
- `server/app/services/skill_change_service.py` — emits `pivot_action` alongside `pending_user_action`
- `server/app/services/react_task_supervisor.py` — dispatches by `pivot_action.type`
- `web/src/pages/chat/utils/actionHandlers.ts` (new) — handler registry
- `web/src/pages/chat/ChatContainer.tsx` — integrated `dispatchPivotActionFromToolResult`
- `web/src/pages/chat/types.ts` — `ChatPendingUserAction.kind` expanded to union type
