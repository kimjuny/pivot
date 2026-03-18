# Compact Mode

This document explains how Pivot compacts a session runtime window when the
prompt context gets too large.

The goal is simple:

- Keep the agent inside the LLM context limit.
- Preserve continuity for the current task.
- Preserve the user's full visible chat history.
- Keep the implementation understandable and easy to extend.

If you need to change compact behavior later, start from this document and then
open the files referenced in each section.

## 1. Mental Model

Pivot now keeps **two different histories** for one chat session:

1. **Full user-visible history**
   This is what the user reads in the UI. It is reconstructed from persisted
   tasks, recursions, and final outputs.

2. **Runtime LLM window**
   This is the serialized `role=user/assistant/system` message list that is
   actually sent back to the LLM across turns.

Compact only rewrites the **runtime LLM window**.

It does **not** delete or truncate the user-visible history.

This split is the most important design decision in the current implementation.

## 2. Why Compact Exists

The runtime LLM window grows across tasks because Pivot reuses session context.
That helps continuity, but eventually the prompt becomes too large.

Instead of injecting a separate `session_memory` block, Pivot now uses:

- `system prompt`
- `compact result`
- recent task-local messages

The compact result is the new canonical summarized session context.

In other words:

- Old design: `system + session_memory + messages`
- New design: `system + compact_result + messages`

## 3. Core Runtime State

The main persisted runtime fields live on [`Session`](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/server/app/models/session.py):

- `react_llm_messages`
  The exact serialized runtime prompt window.
- `react_compact_result`
  The latest compact result currently active in the runtime window.
- `react_pending_action_result`
  Task-local follow-up payload state.
- `react_llm_cache_state`
  Provider-specific cache linkage, such as `previous_response_id`.

Task-local compact bookkeeping lives on [`ReactTask`](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/server/app/models/react.py):

- `runtime_message_start_index`
  The index in the session runtime window where the current task started.
- `stashed_messages`
  Temporary serialized task-local messages removed during mid-task compact.

These fields are intentionally minimal. They are enough to support compaction
without recreating a second memory system.

## 4. High-Level Flow

The compact flow is implemented in
[`ReactEngine._maybe_compact_runtime_window()`](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/server/app/orchestration/react/engine.py#L199).

At a high level:

1. Estimate current runtime-window usage.
2. Compare `used_percent` against the agent's compact threshold.
3. If below threshold, do nothing.
4. If above threshold, run compact.
5. Rebuild the runtime window into a smaller canonical shape.

The agent-level threshold is stored in
[`Agent.compact_threshold_percent`](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/server/app/models/agent.py#L72)
and configured in the web UI from
[`AgentModal.tsx`](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/web/src/components/AgentModal.tsx#L358).

## 5. Trigger Points

Compact can start in two places.

### Case 1. Before a New Task Starts

This happens when the session runtime window is already too large before the new
task bootstrap is appended.

The engine does this:

1. Load the current runtime window.
2. Remove the `system` message from the compaction source list.
3. Append the compact prompt from
   [`compact_prompt.py`](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/server/app/orchestration/compact/compact_prompt.py).
4. Ask the LLM to summarize the historical `user/assistant` messages.
5. Rebuild the runtime window as:

```text
system_prompt -> compact_result
```

6. Continue normal task bootstrap:

```text
system_prompt -> compact_result -> task bootstrap user prompt
```

This is the simpler path because there is no in-flight task-local message slice
to preserve yet.

### Case 2. In the Middle of a Task

This is the more delicate path, and it is the one most developers should study
carefully before editing compact logic.

The requirement is:

- Do **not** compact the current task's in-flight messages.
- Only compact the session history that existed **before** the current task.
- Restore the current task messages after compaction so the agent does not redo
  work it has already done in the same task.

The engine does this:

1. Use `runtime_message_start_index` to split the runtime window into:
   - `prefix_messages`
     Everything before the current task started.
   - `stashed_messages`
     Everything belonging to the current task.
2. Remove any `system` message from `stashed_messages`.
3. Persist `stashed_messages` into `ReactTask.stashed_messages`.
4. **Temporarily rewrite the session runtime window** so it contains only:

```text
system_prompt -> pre-task history
```

5. Run compact on the pre-task `user/assistant` history only.
6. Rebuild the runtime window into:

```text
system_prompt -> compact_result -> stashed_messages
```

7. Clear `stashed_messages`.

This is why the current implementation does not just "remember" the task slice;
it **physically removes it from the runtime window before compacting**. That
behavior is important because otherwise the compaction input can still include
the current task and cause the agent to repeat itself.

The logic is covered by
[`test_engine_compaction.py`](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/server/tests/orchestration/react/test_engine_compaction.py).

## 6. Runtime Window Shapes

These are the canonical message layouts after each stage.

### Normal Session Before Compaction

```text
system_prompt
older user/assistant messages
current task bootstrap
current task payloads
current task assistant outputs
```

### After Task-Start Compact

```text
system_prompt
compact_result
task bootstrap
current task payloads...
```

### After Mid-Task Compact

```text
system_prompt
compact_result
stashed current-task messages
```

This shape keeps the current task alive while shrinking the older history.

## 7. Prompting Behavior

The compact prompt is stored in
[`compact_prompt.py`](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/server/app/orchestration/compact/compact_prompt.py).

The engine sends only:

- historical `role=user`
- historical `role=assistant`
- trailing compact instruction as one `role=user`

It does **not** include the system prompt in the compaction input.

That decision keeps compaction focused on conversation history instead of static
instructions.

## 8. Why Session Memory Was Removed

Previously, the system injected a separate `session_memory` structure into the
prompt. That created duplicated concepts:

- message history
- session memory
- subject/object metadata

The current design intentionally removes that duplication.

Now:

- `compact_result` is the summarized long-term context
- `react_llm_messages` is the exact runtime prompt window
- full task/recursion history remains available for UI reconstruction

This makes the system easier to reason about.

## 9. User-Facing Progress Signals

Compact can happen quickly, so if the UI clears the status immediately the user
may feel like the chat is frozen.

Current signals:

- Web composer shows a visible compact banner and a compacting pill:
  [`ChatComposer.tsx`](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/web/src/pages/chat/components/ChatComposer.tsx)
- The banner remains visible for a minimum duration so people notice it:
  [`ChatContainer.tsx`](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/web/src/pages/chat/ChatContainer.tsx)
- Channel integrations emit progress text:
  [`channel_service.py`](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/server/app/services/channel_service.py#L868)

The backend stream events are:

- `compact_start`
- `compact_complete`
- `compact_failed`

Their schema lives in
[`schemas/react.py`](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/server/app/schemas/react.py).

## 10. Debug Inspector

The floating compact debug button lives in
[`ReactChatInterface.tsx`](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/web/src/components/ReactChatInterface.tsx).

It opens a hover card showing:

- current session ID
- compact progress status
- runtime message count
- runtime message role sequence
- latest compact result

The frontend reads this from:

- [`GET /react/sessions/{session_id}/runtime-debug`](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/server/app/api/react.py)

That endpoint is powered by:

- [`ReactRuntimeService.build_runtime_debug_payload()`](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/server/app/services/react_runtime_service.py)

This inspector is intentionally debug-only. It should help developers inspect
compact output without polluting normal chat history.

## 11. Full History vs Runtime Window

If you are debugging "why the user still sees old messages after compact", this
is usually not a bug.

Remember:

- user-visible history comes from task and recursion persistence
- runtime LLM messages come from `Session.react_llm_messages`

Compact rewrites the second one, not the first one.

Relevant files:

- Full history API:
  [`session.py`](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/server/app/api/session.py)
- Runtime state service:
  [`react_runtime_service.py`](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/server/app/services/react_runtime_service.py)
- Full-history to UI transformation:
  [`chatData.ts`](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/web/src/pages/chat/utils/chatData.ts)

## 12. Where to Modify What

### If you want to change when compact triggers

Start here:

- [`engine.py`](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/server/app/orchestration/react/engine.py)
- [`agent.py`](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/server/app/models/agent.py)
- [`AgentModal.tsx`](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/web/src/components/AgentModal.tsx)

### If you want to change what the compacted summary contains

Start here:

- [`compact_prompt.py`](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/server/app/orchestration/compact/compact_prompt.py)

### If you want to change how the runtime window is rebuilt

Start here:

- [`ReactRuntimeService`](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/server/app/services/react_runtime_service.py)
- [`engine.py`](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/server/app/orchestration/react/engine.py)

### If you want to change user-facing compact feedback

Start here:

- [`ChatContainer.tsx`](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/web/src/pages/chat/ChatContainer.tsx)
- [`ChatComposer.tsx`](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/web/src/pages/chat/components/ChatComposer.tsx)
- [`channel_service.py`](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/server/app/services/channel_service.py)

### If you want to inspect or extend compact debug information

Start here:

- [`ReactChatInterface.tsx`](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/web/src/components/ReactChatInterface.tsx)
- [`GET /react/sessions/{session_id}/runtime-debug`](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/server/app/api/react.py)
- [`ReactRuntimeService.build_runtime_debug_payload()`](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/server/app/services/react_runtime_service.py)

## 13. Important Invariants

When editing compact logic, preserve these invariants:

1. Never include the system prompt in the compaction source messages.
2. Mid-task compact must compact only pre-task history.
3. Mid-task compact must restore task-local messages after compaction.
4. Compact must not delete the user's full visible history.
5. If compact rebuilds the runtime base, provider cache linkage must be reset.
6. If compact fails mid-task, restore the original runtime window.

If any of these invariants are broken, the most common symptoms are:

- the agent repeats work inside the same task
- the agent loses context after compact
- compact appears to work but the LLM still sees too many messages
- the UI history looks inconsistent with the runtime prompt state

## 14. Recommended Debugging Sequence

If compact behavior looks wrong, inspect in this order:

1. Open the floating compact debug button and confirm the latest compact result.
2. Confirm `runtime_message_start_index` on the active task.
3. Check the `compact_start` and `compact_complete` stream events.
4. Verify whether `stashed_messages` were created and then cleared.
5. Confirm the final runtime role sequence after compact.
6. Compare that runtime window with the user's visible history.

That sequence usually tells you whether the bug is:

- trigger logic
- message slicing
- compaction prompt output
- runtime rebuild
- frontend visualization only

## 15. Summary

Compact mode is now a **runtime-window rewrite mechanism**, not a separate
memory subsystem.

The key ideas are:

- compact the runtime window, not the visible history
- compact pre-task history only during an active task
- restore task-local messages after compact
- keep the result inspectable through a dedicated debug surface

If future work remains aligned with those principles, the system should stay
clean, understandable, and extensible.
