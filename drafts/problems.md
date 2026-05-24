# Open Problems & Design Debt

## 1. Tool → Frontend Action Channel: No Shared Abstraction

**Status**: Open
**Discovered**: 2026-05-24
**Context**: Automation feature design discussion

### Problem

Tools that need to control or influence the frontend UI currently use ad-hoc, hardcoded conventions. There is no unified framework for "tool X wants the frontend to do Y."

Two existing mechanisms:

| Mechanism | Tool | Key | Frontend Detection |
|---|---|---|---|
| `ui_intent` | `create_preview_endpoint` | `result.ui_intent.type === "open_workspace_web_preview"` | `ChatContainer.extractWorkspacePreviewIntent()` |
| `pending_user_action` | `submit_skill_change` | `result.pending_user_action.kind === "skill_change_approval"` | Engine wraps in `clarify` event → `ChatContainer` checks `kind` |

Both work by embedding special keys in tool return dicts, which get serialized into SSE `tool_result` events. The frontend scans events with hardcoded string matching.

### Why This Matters

- **`ui_intent`**: TypeScript types are not extensible — one `type` literal, one handler function, no registry.
- **`pending_user_action`**: The `kind` field is a literal `"skill_change_approval"`, not a union type. Engine-level extraction exists but frontend handling is hardcoded.
- **New features blocked**: Automation's "agent proposes → user confirms via pre-filled dialog" pattern needs a third ad-hoc convention. Future features will face the same problem.

### Open Questions

1. **Should there be a unified `ui_action` protocol?** A standardized envelope in tool results that the frontend dispatches through a registry (action type → handler).
2. **What are the distinct action categories?** Candidates:
   - `open_surface` — open a dock/panel (current `ui_intent`)
   - `request_approval` — pause for user confirmation (current `pending_user_action`)
   - `open_dialog` — open a pre-filled creation/edit dialog (Automation proposal)
   - `navigate` — navigate to a specific page/route
   - `notify` — show a toast/notification
3. **Should the engine be aware of these, or stay agnostic?** `pending_user_action` goes through engine-level extraction (`_extract_pending_user_action_from_tool_results`). `ui_intent` is purely frontend-scanned. Which model is correct?
4. **Frontend action registry design**: Should this be a context-based registry (`ActionRegistryProvider`) where tools register handlers, or a simpler switch/dispatch in `ChatContainer`?

### Affected Files

- `server/app/orchestration/tool/builtin/create_preview_endpoint.py` — `ui_intent` emitter
- `server/app/orchestration/tool/builtin/submit_skill_change.py` — `pending_user_action` emitter
- `server/app/orchestration/react/engine.py` — `_extract_pending_user_action_from_tool_results()`
- `web/src/pages/chat/ChatContainer.tsx` — `extractWorkspacePreviewIntent()`, clarify event handling
- `web/src/pages/chat/types.ts` — `ChatPendingUserAction` type with literal `kind`
