# Chat Iteration Display Refactor Plan

## Goal

Refactor the ReAct chat display so each iteration is easier to follow while it is still running.

The current UI frames every iteration inside one collapsible card. This makes users wait too long before they can understand what is happening, especially when the model is thinking or tools are running.

The target experience splits each iteration into three visible parts:

1. Thinking: provider-level LLM thinking or reasoning content.
2. Summary: the assistant's user-facing progress message for this iteration.
3. Tool calling: tool invocation details and returned results.

The summary should be clickable. Expanding it should reveal the lower-level execution details that are currently shown inside the iteration collapse, such as observe, reason, action, errors, and state inspection.

## Current Findings

`ReactChatInterface.tsx` is not the main implementation surface. It mainly provides the chat shell and compact debug floating panel.

The primary frontend files are:

- `pivot/web/src/pages/chat/components/RecursionCard.tsx`
- `pivot/web/src/pages/chat/components/AssistantMessageBlock.tsx`
- `pivot/web/src/pages/chat/ChatContainer.tsx`
- `pivot/web/src/pages/chat/types.ts`
- `pivot/web/src/pages/chat/utils/chatData.ts`

The backend already models the needed iteration fields:

- `thinking`
- `observe`
- `reason`
- `summary`
- `action_type`
- `action_output`
- `tool_call_results`

The persisted model is `ReactRecursion` in:

- `pivot/server/app/models/react.py`

The stream event model already includes:

- `reasoning`
- `observe`
- `reason`
- `summary`
- `action`
- `tool_call`
- `tool_result`

So the display refactor does not require a database schema change.

## Current Streaming Behavior

Only Thinking is truly streamed today.

Backend flow:

- `engine.py` calls `llm.chat_stream`.
- Provider `reasoning_content` deltas are forwarded through the token meter queue.
- The outer loop emits those deltas as `reasoning` stream events.
- `ChatContainer.tsx` appends `reasoning` deltas into `recursion.thinking`.

`observe`, `reason`, `summary`, and `action` are not token-level streamed today.

Reason:

- The LLM content is required to be one complete parseable JSON object.
- The backend waits for the full assistant content.
- It then calls `parse_react_output()`.
- Only after successful parsing does it emit `observe`, `reason`, `summary`, and `action` events.

Tool events are also not emitted before execution today.

Current tool flow:

- The backend parses `CALL_TOOL`.
- It executes all requested tools inside `execute_recursion()`.
- Only after the tools finish does the outer loop emit `tool_call` and `tool_result`.
- In practice, the frontend receives the call and result as an already-completed snapshot.

## Product Direction

Prefer a two-phase implementation.

Phase 1 should be frontend-only and should not modify `system_prompt.md`.

Phase 2 can improve backend streaming once the UI shape is settled.

This keeps the first change surgical and gives users a better experience quickly without destabilizing the ReAct protocol.

## Product Decisions

These decisions are locked for the first implementation pass.

1. Phase 1 is frontend-only.
   - Do not change the ReAct prompt, parser, backend stream contract, or database schema.
   - First goal is to see the redesigned chat presentation with existing events.

2. Summary is fully visible by default.
   - Use option A: show the full summary directly.
   - Do not clamp summary to a fixed number of lines in Phase 1.
   - The summary remains the primary user-facing part of each iteration.

3. Thinking is visible while running and collapses after completion.
   - Use option C: show thinking during the active running state.
   - After the iteration completes, collapse thinking by default while keeping it available.
   - Do not fabricate thinking when the provider does not expose reasoning content.

4. Observe and reason remain available.
   - Keep `observe`, `reason`, and related execution details accessible from the summary details area.
   - Do not remove internal fields in this pass.

5. Tool details use option C.
   - Tool timeline is visible.
   - Tool names and statuses are visible by default.
   - Arguments are collapsed by default.
   - Successful results are collapsed by default.
   - Failed results are expanded by default.

6. Backend tool streaming is deferred.
   - Phase 1 should be tried in real usage before deciding how much backend streaming work is needed.

7. Summary token streaming is deferred to Phase 2 discussion.
   - JSON likely limits the desired streaming behavior.
   - Revisit the protocol shape after the frontend refactor is evaluated.

8. Visual shape should be a lightweight timeline.
   - Avoid a stack of heavy bordered cards.
   - The iteration should feel like progress in a chat flow, not a debugger-only accordion.

## Phase 1: Frontend Display Refactor

### Objective

Replace the single iteration collapse with a visible three-part iteration layout.

This phase should make existing data easier to consume, but it should not claim token-level streaming where the backend does not yet provide it.

### Proposed UI Structure

For each recursion:

1. Thinking section
   - Render `recursion.thinking` when present.
   - Keep the existing running ticker while a recursion is running and no stable label exists yet.
   - Do not fabricate thinking when the provider does not expose reasoning content.
   - Keep thinking visible while the iteration is running.
   - Collapse thinking by default after the iteration completes.

2. Summary section
   - Render `recursion.summary` as the main user-facing text.
   - Make this section directly visible, not hidden inside a full iteration accordion.
   - Show the full summary by default.
   - If summary is absent while running, show an appropriate running state.
   - Clicking summary toggles execution details.

3. Details under summary
   - Show `observe`.
   - Show `reason`.
   - Show `action`.
   - Show `RecursionStateViewer` when `taskId` is available.
   - Show errors and error logs.

4. Tool timeline
   - Show each tool call separately.
   - Show arguments behind a small disclosure control.
   - Show result/error behind a small disclosure control.
   - Show pending/running state when available.
   - Expand failed results by default.
   - Keep successful results collapsed by default.

### Main Files

- `pivot/web/src/pages/chat/components/RecursionCard.tsx`
- `pivot/web/src/pages/chat/components/RecursionCard.test.tsx`

Possible light-touch changes:

- `pivot/web/src/pages/chat/components/AssistantMessageBlock.tsx`
- `pivot/web/src/pages/chat/components/AssistantMessageBlock.test.tsx`

### Implementation Steps

1. Rename the mental model of `RecursionCard` from "one collapsible card" to "one iteration block".
   - Verification: completed and running recursions still render in assistant messages.

2. Extract small rendering helpers inside `RecursionCard.tsx`.
   - `ThinkingSection`
   - `SummarySection`
   - `ExecutionDetails`
   - `ToolTimeline`
   - Verification: tests can target each visible section by text/role without relying on one giant collapse.

3. Make summary visible by default.
   - Verification: a recursion with `summary` renders that summary even when details are collapsed.

4. Move `observe`, `reason`, `action`, state viewer, reflect, and errors into summary details.
   - Verification: clicking summary/details toggle reveals the same diagnostic information that the old expanded card exposed.

5. Move tool rendering into its own visible timeline area.
   - Verification: a recursion with tool events shows tool name/count without opening the summary details.

6. Preserve current history behavior.
   - Verification: `buildMessagesFromHistory()` recursions still render thinking, summary, details, and tools from persisted task history.

7. Run frontend checks.
   - Preferred: `podman compose exec frontend npm run lint`
   - Preferred: `podman compose exec frontend npm run type-check`
   - If services are not running, use `podman compose run --rm frontend ...`.

### Acceptance Criteria

- Users can see each iteration's summary without expanding the whole iteration.
- Thinking appears as soon as provider reasoning deltas arrive.
- Tool calls/results are visually separate from observe/reason details.
- Existing observe/reason/action details remain accessible.
- No backend or database migration is required.
- Existing chat history continues to render.

## Phase 2: Backend Tool Event Streaming

### Objective

Emit tool call intent before tools run, then emit tool results as each tool completes.

This is the most valuable backend streaming improvement because it directly reduces the "silent wait" during long tool execution.

### Current Limitation

`execute_recursion()` executes tools internally and returns only after all tool work is complete. The outer engine loop only emits events after that return.

Relevant file:

- `pivot/server/app/orchestration/react/engine.py`

### Proposed Backend Behavior

After `CALL_TOOL` is parsed:

1. Persist the LLM decision.
2. Emit `action` with `CALL_TOOL`.
3. Emit `tool_call` containing tool ids, names, and arguments before execution starts.
4. Execute tools.
5. Emit `tool_result` after each tool result, or after each batch if batching is simpler.
6. Finalize recursion state with merged tool results.

### Likely Backend Changes

- Refactor `execute_recursion()` so tool execution can report intermediate events.
- Option A: convert it into an async generator.
- Option B: pass an event callback/publisher into it.
- Option C: move tool execution out of `execute_recursion()` and into the outer loop.

Option B is probably the smallest conceptual change, but the final choice should follow the existing `ReactTaskSupervisor` event persistence path.

### Frontend Changes

`ChatContainer.tsx` currently appends `tool_call` and `tool_result` events to `recursion.events`.

`RecursionCard.tsx` currently renders tool details mostly from `tool_call` events that already include both calls and results.

For true tool streaming, frontend should merge by `tool_call_id`:

- `tool_call` creates pending tool items.
- `tool_result` fills in result/error for matching ids.
- A missing result means the tool is still running.

### Acceptance Criteria

- A long-running tool call becomes visible before the tool returns.
- The UI shows pending status while the tool is running.
- Each result appears without waiting for the entire task to finish.
- Reconnect/history behavior remains consistent through persisted task events.

## Phase 3: Summary-Level Streaming

### Objective

Stream `summary`, and optionally `observe` and `reason`, before the full JSON response completes.

### Important Constraint

The current ReAct protocol requires the first assistant content block to be a complete parseable JSON object. This makes summary-level streaming non-trivial.

### Options

1. Incremental JSON field parser
   - Keep `system_prompt.md` unchanged.
   - Parse model content as it streams.
   - Emit deltas when the parser is inside known string fields like `summary`, `observe`, or `reason`.
   - Harder to implement correctly because of escaping, malformed JSON, retries, and payload blocks.

2. Prompt/protocol change
   - Ask the model to output stream-friendly sections outside or before JSON.
   - More invasive.
   - Higher risk of breaking the strict parser.
   - Requires changing `system_prompt.md` and parser expectations.

3. Keep summary non-token-streamed
   - Emit summary immediately after parse.
   - Focus streaming investment on thinking and tools.
   - Lowest risk.

### Recommendation

Do not start here.

Finish Phase 1 first. Then implement Phase 2 tool streaming. Revisit summary-level token streaming only if users still experience too much waiting after tool visibility improves.

## System Prompt Guidance

Do not modify `pivot/server/app/orchestration/react/system_prompt.md` for Phase 1.

Only consider prompt changes if Phase 3 chooses the protocol-change route.

If prompt changes are needed later, keep them small and explicit:

- Preserve the first parseable JSON object contract unless the parser is changed at the same time.
- Keep `summary` mandatory.
- Avoid adding compatibility layers for old behavior because the project is not launched yet.

## Risks

- Summary may appear all at once in Phase 1 because backend does not stream it yet.
- Some providers may not expose `reasoning_content`; Thinking should gracefully disappear or show a running state.
- Tool result payloads can be large; the timeline must keep arguments/results collapsible.
- If backend tool streaming is added, reconnect replay needs to preserve pending and completed tool states.
- Incremental JSON parsing can be fragile and should be treated as a separate feature, not bundled with the UI refactor.

## Recommended Execution Order

1. Implement Phase 1 frontend-only layout.
2. Verify with existing chat history and live streaming.
3. Add or update frontend tests around visible summary, details toggle, thinking, and tool timeline.
4. Run frontend lint and type-check.
5. Separately design Phase 2 backend tool streaming.
6. Implement tool-call-before-result events.
7. Update frontend event merging for pending tool calls.
8. Re-evaluate whether summary-level streaming is still necessary.
