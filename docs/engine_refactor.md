# Engine Refactor Plan

## Metadata

- Status: In Progress
- Scope: `server/app/orchestration/react/engine.py` and directly related ReAct runtime persistence
- Last updated: 2026-03-06
- Document rule: keep this file updated if the execution plan changes during later implementation turns

## Goal

Reduce `engine.py` from a 2135-line mixed-responsibility file into a smaller orchestration entrypoint with clear boundaries:

- `engine.py` should orchestrate the loop, not parse every protocol detail and not persist every state mutation itself.
- Persistence logic should move into `server/app/services` with reusable, explicit interfaces.
- The ReAct output contract should become stricter. This project is not live, so compatibility branches that only support legacy or malformed shapes should be removed instead of preserved.
- State reconstruction and snapshot writing should have one source of truth.

## Non-goals

- Do not preserve database backward compatibility.
- Do not preserve old malformed LLM output formats unless they still materially improve robustness.
- Do not split files into many tiny helpers with unclear ownership.

## Current Problems

## 1. `engine.py` mixes too many responsibilities

`server/app/orchestration/react/engine.py` currently owns all of the following:

- LLM streaming and token accounting
- assistant JSON and payload parsing
- retry and error classification
- tool execution
- task runtime message persistence
- pending action result persistence
- LLM cache state persistence
- recursion row creation/finalization
- plan mutation and step status updates
- state snapshot generation
- task lifecycle updates
- SSE event construction
- session memory integration

This is the main reason every change requires loading the entire file.

## 2. Orchestration and persistence are tightly coupled

The engine directly mutates SQLModel objects and commits repeatedly:

- task runtime state methods around `engine.py:726`, `engine.py:768`, `engine.py:782`, `engine.py:838`, `engine.py:865`
- recursion persistence and state mutation throughout `engine.py:1000` onward
- multiple `self.db.commit()` calls inside one recursion path and inside step update loops

This makes the control flow hard to reason about and prevents reuse from API, tests, and future orchestration variants.

## 3. There are duplicated sources of truth

### Plan duplication

Plan definitions exist in both:

- `ReactPlanStep` rows
- `RE_PLAN` recursion `action_output`

`server/app/orchestration/react/context.py` rehydrates plan fields from the latest `RE_PLAN` recursion instead of trusting `ReactPlanStep`. That is unnecessary duplication and creates drift risk.

### Tool result duplication

Tool results are stored separately in `ReactRecursion.tool_call_results`, then merged back into `action_output` for snapshots and context reconstruction.

### Snapshot duplication

`ReactRecursionState` is a one-to-one extension table for recursion snapshots, while `context.py` also knows how to rebuild the same state by replaying recursions and plan steps. The rebuild logic is partially duplicated in two places.

## 4. The output contract is over-tolerant

Because the system is still pre-launch, several compatibility branches are not worth keeping:

- `step_status_update` is accepted from multiple locations:
  - `action.step_status_update`
  - top-level `step_status_update`
  - `action.output.step_status_update`
- `CALL_TOOL.arguments` accepts non-dict values and attempts `json.loads`
- `_normalize_step_status_update_payload()` accepts list, dict, and JSON string inputs
- runtime state fields on `ReactTask` are repeatedly decoded from loosely typed JSON blobs

These branches make the code larger and reduce confidence in the actual contract.

## 5. There is dead or low-value code

- `_normalize_assistant_message_json()` is currently unused.
- Several helper methods only exist because runtime state is split across three serialized task fields.
- Commit granularity is too fine; many commits are bookkeeping rather than meaningful state boundaries.

## Recommended Direction

## Summary

Keep `engine.py` as the orchestration facade and move the heavy stateful details into three clear areas:

1. ReAct protocol parsing and validation
2. ReAct runtime persistence
3. ReAct state/snapshot mutation

## Recommended Target Structure

```text
server/app/orchestration/react/
  engine.py                  # main loop, event orchestration only
  parser.py                  # parse + validate assistant output and payload blocks
  context.py                 # load/build ReactContext from authoritative snapshot/state
  types.py                   # typed dataclasses for parsed output and event payloads

server/app/services/
  react_runtime_service.py   # runtime messages, previous_response_id, pending action result
  react_state_service.py     # recursion lifecycle, plan writes, snapshot writes, task state transitions
```

This is intentionally not more granular than necessary.

## Recommended Schema Simplification

### A. Introduce a dedicated runtime state model or collapse runtime state into one field

Current task runtime fields:

- `ReactTask.llm_messages`
- `ReactTask.pending_action_result`
- `ReactTask.llm_cache_state`

Recommended replacement, in order of preference:

1. `ReactTaskRuntime` table, one-to-one with task
2. single `ReactTask.runtime_state` JSON field

Recommended shape:

```json
{
  "messages": [],
  "pending_action_result": null,
  "previous_response_id": null
}
```

Why this is better:

- removes three repeated `json.loads/json.dumps` paths from `engine.py`
- gives one clear persistence boundary for runtime prompt state
- isolates ephemeral execution state from durable task metadata

### B. Remove `ReactRecursionState` as a separate table

Recommended change:

- add `state_snapshot` to `ReactRecursion`
- delete `ReactRecursionState`

Why:

- snapshot is a one-to-one property of a recursion
- removes one model, one endpoint query path, and one commit per recursion
- makes historical inspection simpler

If removing the table is too large for the first implementation step, keep it temporarily but treat it as transitional.

### C. Remove `tool_call_results` as a separate persisted field

Recommended change:

- persist the enriched `action_output` after tool execution, with tool results embedded
- delete `ReactRecursion.tool_call_results`

Why:

- avoids replay/merge logic in both `engine.py` and `context.py`
- establishes one canonical representation of tool actions

### D. Make `ReactPlanStep` the only source of truth for plan state

Recommended rule:

- `RE_PLAN.action_output` remains audit/debug data only
- all context reconstruction should read plan data from `ReactPlanStep`

Why:

- removes `context.py` logic that backfills plan descriptions from recursion payloads
- makes plan mutation service-oriented and predictable

## Logic To Delete or Simplify

## Delete immediately

- `ReactEngine._normalize_assistant_message_json()` because it is unused
- repeated plan metadata rehydration from `RE_PLAN.action_output`
- separate persisted `tool_call_results` merge path, once canonical `action_output` is enriched

## Tighten the LLM contract

Recommended new rules:

- `action_type` is mandatory and must be one of the allowed enum values
- `CALL_TOOL` must contain `action.output.tool_calls: list[ToolCall]`
- each tool call must contain:
  - `id: str`
  - `name: str`
  - `arguments: dict[str, Any]`
- `step_status_update` is only accepted at `action.step_status_update`
- `step_status_update` must always be a list, never a dict or string

What should be removed:

- parsing `CALL_TOOL.arguments` from string JSON
- checking multiple locations for `step_status_update`
- normalizing `dict` or JSON-string step updates into a list

What should stay:

- one parse-retry round for malformed JSON is still useful
- timeout classification is still useful
- payload block parsing is still useful if large tool arguments remain part of the protocol

## Collapse mutation flow into services

### `ReactRuntimeService`

Suggested interface:

```python
class ReactRuntimeService:
    def load(self, task: ReactTask) -> TaskRuntimeState: ...
    def initialize(self, task: ReactTask, system_prompt: str) -> TaskRuntimeState: ...
    def append_user_payload(self, task: ReactTask, payload: dict[str, Any]) -> TaskRuntimeState: ...
    def append_assistant_message(self, task: ReactTask, content: str) -> TaskRuntimeState: ...
    def rollback_last_user_message(self, task: ReactTask) -> TaskRuntimeState: ...
    def set_next_action_result(self, task: ReactTask, value: list[dict[str, Any]] | None) -> None: ...
    def set_previous_response_id(self, task: ReactTask, response_id: str | None) -> None: ...
    def clear(self, task: ReactTask) -> None: ...
```

This service should own all runtime prompt-state serialization.

### `ReactStateService`

Suggested interface:

```python
class ReactStateService:
    def load_context(self, task: ReactTask) -> ReactContext: ...
    def start_recursion(self, task: ReactTask, trace_id: str) -> ReactRecursion: ...
    def finalize_success(
        self,
        task: ReactTask,
        recursion: ReactRecursion,
        context: ReactContext,
        decision: ParsedReactDecision,
        tool_results: list[ToolExecutionResult],
        usage: TokenUsage | None,
    ) -> RecursionPersistenceResult: ...
    def finalize_error(
        self,
        task: ReactTask,
        recursion: ReactRecursion,
        error: str,
        usage: TokenUsage | None,
    ) -> None: ...
    def mark_waiting_input(self, task: ReactTask) -> None: ...
    def mark_completed(self, task: ReactTask) -> None: ...
    def mark_failed(self, task: ReactTask) -> None: ...
    def mark_cancelled(self, task: ReactTask) -> None: ...
    def advance_iteration(self, task: ReactTask) -> None: ...
```

This service should own all database writes related to:

- recursion rows
- plan step mutations
- snapshot persistence
- task lifecycle transitions
- aggregated token counters

## Refactor `engine.py` around typed inputs and outputs

`engine.py` should stop passing large untyped dictionaries across the entire file.

Recommended typed objects:

- `ParsedReactDecision`
- `ParsedAction`
- `ToolCallRequest`
- `ToolExecutionResult`
- `RecursionOutcome`
- `TaskRuntimeState`

Benefits:

- less repeated `dict[str, Any]` defensive code
- validation happens once in parser/service layers
- event generation becomes more predictable

## Proposed End-State for `engine.py`

The end-state engine should roughly do this:

1. load runtime state via `ReactRuntimeService`
2. load context via `ReactStateService`
3. append the current user payload
4. call LLM
5. parse assistant response via `parser.py`
6. execute tools if needed
7. persist recursion outcome via `ReactStateService`
8. update runtime state via `ReactRuntimeService`
9. emit SSE events

No direct JSON column management should remain in `engine.py`.

## Phased Execution Plan

## Phase 0: Safety Baseline

- Add focused tests before changing behavior:
  - parse valid CALL_TOOL payload blocks
  - reject malformed `step_status_update`
  - CALL_TOOL success and failure
  - RE_PLAN persistence
  - CLARIFY pause and resume
  - ANSWER session memory updates
  - malformed JSON retry path
  - timeout rollback path
- Record current SSE event sequence for:
  - CALL_TOOL
  - RE_PLAN
  - CLARIFY
  - ANSWER

Exit criteria:

- baseline behavior is documented well enough to compare after each phase

## Phase 1: Extract the protocol parser

Changes:

- create `server/app/orchestration/react/parser.py`
- move the following from `engine.py` into parser-level functions/classes:
  - `_safe_load_json`
  - payload block splitting/parsing/ref resolution
  - `_safe_load_react_output`
  - strict action schema validation
- delete `_normalize_assistant_message_json`
- replace raw dict parsing with `ParsedReactDecision`

Behavioral change:

- stop accepting legacy `step_status_update` locations
- stop accepting non-dict tool arguments

Exit criteria:

- `execute_recursion()` no longer contains JSON/payload parsing details

## Phase 2: Extract runtime persistence

Changes:

- add `server/app/services/react_runtime_service.py`
- move all runtime state methods out of `engine.py`
- recommended schema change:
  - create `ReactTaskRuntime` or add `ReactTask.runtime_state`
  - remove `llm_messages`
  - remove `pending_action_result`
  - remove `llm_cache_state`
- update API resume logic in `server/app/api/react.py` to use the runtime service

Exit criteria:

- `engine.py` does not call `json.loads/json.dumps` for task runtime state
- runtime state reads/writes are reusable outside the engine

## Phase 3: Extract recursion and plan persistence

Changes:

- add `server/app/services/react_state_service.py`
- move recursion create/finalize logic out of `engine.py`
- move plan replacement and step status mutation out of `engine.py`
- remove per-step commits; use a bounded transaction per recursion finalization
- recommended schema change:
  - embed `state_snapshot` into `ReactRecursion`
  - remove `ReactRecursionState`
  - embed tool execution results into `action_output`
  - remove `tool_call_results`

Exit criteria:

- `execute_recursion()` mainly does LLM call, tool execution, and service delegation
- one successful recursion finalization uses one commit boundary instead of many scattered commits

## Phase 4: Unify context loading and snapshot writing

Changes:

- simplify `server/app/orchestration/react/context.py`
- make context reconstruction rely on one authoritative source:
  - latest snapshot if available, or
  - authoritative persisted plan + memory state without replay hacks
- remove plan metadata backfill from recursion payloads
- remove tool result merge logic from context reconstruction

Exit criteria:

- `context.py` no longer duplicates state mutation logic from the engine

## Phase 5: Slim the main loop and normalize event emission

Changes:

- split internal `run_task()` logic into a few private orchestration helpers
- optionally create small event builder functions if the SSE payload code still dominates
- keep event types unchanged unless there is a strong reason to simplify them too

Recommended target size:

- `engine.py` under 800 lines
- `execute_recursion()` under 150 lines
- `run_task()` under 250 lines

## Recommended Implementation Order

Recommended order for lowest risk:

1. parser extraction
2. runtime service extraction
3. state service extraction
4. schema cleanup for snapshots and tool results
5. context simplification
6. final engine cleanup

This order keeps behavior mostly stable while shrinking the file incrementally.

## Risks

## 1. CLARIFY resume flow may break

Why:

- resume currently depends on persisted `pending_action_result`
- API code in `server/app/api/react.py` writes that field directly

Mitigation:

- change API and engine in the same phase
- add a dedicated CLARIFY resume test before refactoring

## 2. Prompt cache chaining may regress

Why:

- incremental request mode depends on `previous_response_id`

Mitigation:

- make `previous_response_id` a first-class runtime field
- verify both normal recursion flow and malformed-response rollback flow

## 3. Snapshot correctness may drift during the transition

Why:

- current system duplicates context mutation in multiple places

Mitigation:

- during Phase 3 or 4, temporarily compare rebuilt context and persisted snapshot in tests
- do not remove old code paths until snapshot parity is verified

## 4. Tool result rendering may regress in UI/history

Why:

- current system emits separate `tool_results` while also merging results into snapshots

Mitigation:

- keep SSE event payload shape stable
- only simplify persistence representation, not the event contract, in the first pass

## 5. Schema cleanup may require coordinated API changes

Why:

- `/react/tasks/{task_id}/states` currently reads `ReactRecursionState`

Mitigation:

- either update the endpoint in the same phase, or keep a temporary adapter response

## Rollback Strategy

Because backward compatibility is not required, rollback should be simple and git-based rather than code-based.

Recommended rollback rules:

- keep each phase in a separate commit
- do not mix schema cleanup with parser extraction in the same commit
- if a phase regresses behavior:
  - revert only that phase commit
  - keep the previous successful phase
- before deleting old tables/columns, land the new service flow first and verify it

Practical rollback checkpoints:

1. parser extracted, no schema changes
2. runtime service extracted, old schema still acceptable
3. state service extracted, old snapshot schema still acceptable
4. schema cleanup committed only after parity checks pass

## Acceptance Criteria

## Code structure

- `engine.py` is the orchestration entrypoint, not the persistence layer
- no direct task runtime JSON field parsing remains in `engine.py`
- plan mutation logic lives in a service, not inside the main loop
- context reconstruction has one clear authoritative source

## Behavior

- CALL_TOOL, RE_PLAN, CLARIFY, REFLECT, ANSWER still work end-to-end
- malformed JSON retry still works once
- timeout rollback still avoids consuming iteration budget
- incremental prompt cache chaining still works

## Quality

- new or updated tests cover the main recursion branches
- `server/lint.sh` passes
- if frontend code is touched, `podman compose exec frontend npm run check-all` passes

## Nice-to-have Success Metrics

- `engine.py` line count reduced by at least 50%
- direct `self.db.commit()` calls inside `engine.py` reduced to task-level orchestration boundaries only
- number of `json.loads/json.dumps` calls inside `engine.py` reduced to near zero

## Recommended First Implementation Slice

If only one implementation slice is done next, it should be:

1. extract `parser.py`
2. delete dead compatibility branches
3. introduce typed parsed output objects

Why this is the best first slice:

- highest line-count reduction per risk unit
- no immediate schema dependency
- creates a cleaner seam for the later service extraction

## Open Decisions

These should be resolved before Phase 2 or Phase 3 implementation:

- choose `ReactTaskRuntime` table vs single `runtime_state` field
- decide whether `ReactRecursionState` is removed immediately or only after parity verification
- decide whether to keep `tool_results` as a persisted separate field for audit, or only as part of SSE/event payload

## Execution Log

Update this section in later turns instead of scattering plan changes elsewhere.

### 2026-03-06

- Initial analysis completed.
- Recommended direction:
  - extract parser first
  - move runtime persistence to a dedicated service
  - move recursion/plan persistence to a dedicated service
  - simplify schema after service boundaries are in place
- Phase 1 implemented:
  - extracted strict protocol parsing into `server/app/orchestration/react/parser.py`
  - introduced typed protocol objects in `server/app/orchestration/react/types.py`
  - removed parser-related helper methods from `engine.py`
  - tightened the contract so `step_status_update` is only accepted at `action.step_status_update`
  - tightened the contract so `CALL_TOOL.arguments` must already be an object after payload resolution
  - added parser unit tests under `server/tests/orchestration/react/test_parser.py`
- Verification completed:
  - `podman compose exec backend poetry run ruff check server`
  - `podman compose exec backend poetry run pyright server`
  - `podman compose exec backend poetry run python -m unittest discover -s server/tests`
- Phase 2 implemented:
  - added `server/app/services/react_runtime_service.py`
  - moved task runtime message loading/persistence out of `engine.py`
  - moved `pending_action_result` persistence out of `engine.py` and `server/app/api/react.py`
  - moved `previous_response_id` runtime cache persistence out of `engine.py`
  - updated the CLARIFY resume path to reuse the runtime service instead of writing task JSON fields directly
  - added runtime-service tests under `server/tests/services/test_react_runtime_service.py`
- Phase 2 implementation note:
  - service extraction is complete
  - schema cleanup for runtime state was intentionally deferred to a later phase to keep this step low-risk
- Verification completed again after Phase 2:
  - `podman compose exec backend poetry run ruff check server`
  - `podman compose exec backend poetry run pyright server`
  - `podman compose exec backend poetry run python -m unittest discover -s server/tests`
- Phase 3 implemented:
  - added `server/app/services/react_state_service.py`
  - moved recursion row creation out of `engine.py`
  - moved recursion success/error persistence out of `engine.py`
  - moved plan replacement, step status mutation, and snapshot writing out of `engine.py`
  - moved task lifecycle transitions used by the main loop into the state service
  - updated `engine.py` to consume the state service for context loading and task status changes
  - added state-service integration tests under `server/tests/services/test_react_state_service.py`
- Phase 3 implementation note:
  - service extraction is complete
  - schema cleanup for `ReactRecursionState` and `tool_call_results` is still deferred to a later phase
  - `context.py` still contains replay-oriented reconstruction logic and remains a target for the next cleanup phase
- Verification completed again after Phase 3:
  - `podman compose exec backend poetry run ruff check server`
  - `podman compose exec backend poetry run pyright server`
  - `podman compose exec backend poetry run python -m unittest discover -s server/tests`
- Phase 4 implemented:
  - simplified `server/app/orchestration/react/context.py` to prefer the latest `ReactRecursionState` snapshot
  - removed replay-oriented recursion reconstruction from `context.py`
  - removed plan metadata backfill from historical `RE_PLAN.action_output`
  - removed tool-result merge logic from context reconstruction
  - kept a minimal fallback path that restores plan rows when no valid snapshot exists
  - added context tests under `server/tests/orchestration/react/test_context.py`
- Phase 4 implementation note:
  - snapshot content is now the authoritative source for `context` and `recursion_history`
  - live task metadata still overrides snapshot global fields such as `iteration` and `status`
  - schema cleanup is still deferred; snapshots remain stored in `ReactRecursionState`
- Verification completed again after Phase 4:
  - `podman compose exec backend poetry run ruff check server`
  - `podman compose exec backend poetry run pyright server`
  - `podman compose exec backend poetry run python -m unittest discover -s server/tests`
