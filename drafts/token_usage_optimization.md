# Agent Token Usage Optimization

> Date: 2026-05-17
> Status: Phase 1 + Phase 2 + Phase 3 + Phase 3b + Phase 4 + Phase 5 complete

---

## Completed Work

### 2.1 System Prompt: Chinese → English + Redundancy Elimination ✅ DONE

**Result**: Rewrote `system_prompt.md` from Chinese to English. Removed "Agent 权限运行边界" section, consolidated repeated format rules, merged JSON examples. ~55-60% token reduction.

### 2.1b Prompt Split: Session-level vs Task-level ✅ DONE

**Key architectural change**: Moved `tools_description` and `skills_index` from per-task user prompt → session-level system prompt. These are stable within a session and survive context compaction (engine.py restores system prompt after compaction).

- **System prompt** (`system_prompt.md`): protocol rules + `{{tools_description}}` + `{{skills}}`
- **User prompt** (`user_prompt.md`): only task-level content — `{{system_time}}` + `{{mandatory_skills}}` + `{{workspace_guidance}}`
- **Savings**: ~3000-4000 tokens per task after the first one in a session (tools/skills no longer re-injected)

**Files modified**:
- `server/app/orchestration/react/system_prompt.md`
- `server/app/orchestration/react/user_prompt.md`
- `server/app/orchestration/react/prompt_template.py`
- `server/app/orchestration/react/engine.py`
- `server/app/services/react_context_service.py`
- `server/tests/services/test_workspace_guidance_service.py`

### 2.2 Tool Catalog: Schema-based Approach (Option 2) ✅ DONE

**Decision**: Chose Option 2 (structured JSON Schema from decorator) over Option 1 (docstring-based) for forward-compatibility with native LLM tool calling (OpenAI/Anthropic/Gemini all share the same schema: `name + description + parameters JSON Schema`).

**Implementation**:
1. **`Param` descriptor class** — used inside `Annotated[type, Param("description")]` to attach per-parameter descriptions. Supports `hidden=True` to exclude params from LLM schema while keeping them in the Python function signature.
2. **`@tool` decorator enhanced** — accepts explicit `description` parameter (LLM-facing tool overview). Docstring no longer feeds LLM at all.
3. **Auto-extraction from function signature**:
   - `tool_name` ← `func.__name__`
   - `parameter_name` / `parameter_type` ← type hints → JSON Schema type
   - `parameter_required` ← no default value → `required` array
   - `parameter_default` ← default value → `default` field
   - `parameter_description` ← `Param("...")` in `Annotated` → `description` field
4. **All 9 builtin tools migrated** to new format.
5. **Output format** now matches OpenAI/Anthropic/Gemini native tool calling schema exactly.

**Example output** (what the LLM sees):
```json
{
  "name": "run_bash",
  "description": "Run one bash command from /workspace and return stdout.",
  "parameters": {
    "type": "object",
    "properties": {
      "command": {"type": "string", "description": "Shell command string executed with bash -lc."},
      "fail_on_nonzero": {"type": "boolean", "description": "Raise RuntimeError on non-zero exit code.", "default": false}
    },
    "required": ["command"]
  }
}
```

**`web_search` special handling**: `provider` param marked `Param(hidden=True)` — excluded from LLM schema (design decision: LLM should not hard-code provider keys).

**Files modified**:
- `server/app/orchestration/tool/decorator.py` — `Param` class, enriched schema builder
- `server/app/orchestration/tool/metadata.py` — clean `to_dict()` / `to_openai_format()`
- `server/app/orchestration/tool/__init__.py` — export `Param`
- All 9 files in `server/app/orchestration/tool/builtin/`

### 2.2b Web Search Tool: Two-Layer Parameter Architecture ✅ DONE

**Problem**: `web_search` exposed 19 LLM-visible parameters (20 total). Most were provider-specific knobs (`search_depth`, `include_favicon`, `auto_parameters`, etc.) that an Agent never needs to reason about. The 20-field `WebSearchQueryRequest` tried to abstract across all providers, creating a leaky abstraction — most params were ignored by Baidu, and providers couldn't expose their own native parameters.

**Decision**: Refactored into a clean two-layer architecture:
- **Layer 1 (Agent)**: 6 universal abstract params the LLM controls
- **Layer 2 (Config JSON)**: Provider-native params, pre-populated from manifest defaults, editable per-binding in the "Edit Web Search" dialog

**Implementation**:
1. **`WebSearchQueryRequest` trimmed from 20 → 7 fields**: `query`, `provider`, `max_results`, `topic`, `time_range`, `include_domains`, `exclude_domains`. Removed 13 provider-specific fields and their validators.
2. **`WebSearchProviderManifest` gained `default_runtime_config`**: Each provider declares its native parameter defaults in the manifest. These flow to the frontend via `manifest.model_dump()` and pre-populate the Config JSON textarea when creating a new binding.
3. **Providers read native params from `binding.runtime_config`**: Tavily reads 15 native params (search_depth, include_answer, etc.). Baidu reads 5 (edition, safe_search, include_images, start_date, end_date).
4. **Merge priority**: Agent's abstract params override Config JSON on overlap (e.g., Agent sends `max_results=10`, Config JSON has `max_results=5` → 10 wins).
5. **Frontend**: Replaced `ConfigFieldGroup` for runtime config with a JSON textarea (matching `ExtensionBindingDialog` pattern). Pre-fills from `manifest.default_runtime_config`.
6. **`search` tool**: `max_candidates` and `max_hits_per_file` hidden via `Param(hidden=True)`.

**Result**: LLM-visible params reduced from 19 → 6 per `web_search` call (all 6 are Agent-facing, zero hidden params). Provider-native parameters are correctly separated and configurable per-binding. The `provider` key is resolved from the execution context at runtime rather than passed as a tool parameter.

**Files modified**:
- `server/app/orchestration/web_search/types.py` — trimmed request model, added `default_runtime_config`
- `server/app/orchestration/web_search/normalization.py` — removed 13 field normalizations
- `server/app/orchestration/tool/builtin/web_search.py` — 6 LLM-visible params
- `server/app/orchestration/tool/builtin/search.py` — 2 params hidden
- `extensions/extensions/tavily/providers/tavily.py` — reads from `runtime_config`, merge logic
- `extensions/extensions/baidu/providers/baidu.py` — reads from `runtime_config`, merge logic
- `web/src/utils/api.ts` — `default_runtime_config` on manifest type
- `web/src/components/WebSearchBindingDialog.tsx` — Config JSON textarea
- 4 test files updated for new manifest field

### 2.3 Per-Recursion Payload: Plan Compression ✅ DONE

**Decision**: Adopted a two-tier `current_plan` injection strategy based on whether context compaction has occurred.

**Implementation**:
1. **Before compaction**: Inject a one-line plan status summary via `_build_plan_status_line()`, e.g. `"Steps 1,2 done, Step 3 in_progress, Steps 4,5 pending"` (~13 tokens vs ~400 tokens for full plan). Rationale: the LLM already has full plan context in its message history — re-injecting the entire structured plan is redundant.
2. **After compaction**: Inject the full structured plan via `_build_current_plan_payload()`. Rationale: compaction loses plan details, so the full context must be rebuilt.
3. **Detection**: `after_compaction` flag = `runtime_state.compact_result is not None`.

**Result**: ~97% token reduction for `current_plan` field per recursion before compaction (13 tokens vs ~400 tokens). Compounds across all recursions until compaction triggers.

**Files modified**:
- `server/app/orchestration/react/engine.py` — added `_build_plan_status_line()`, updated `_build_recursion_user_payload()` with `after_compaction` parameter
- `server/app/services/react_context_service.py` — mirrored same logic for token estimation accuracy

**Note**: UI event streaming (SSE) continues to use full `_build_current_plan_payload()` for frontend display — only the LLM-facing payload is compressed.

### 2.4 Assistant Output Format Cleanup ✅ DONE

**Result**: Removed 4 dead fields, renamed 1 field, moved 1 field to action-specific output, removed `trace_id` from LLM prompt. The LLM's JSON envelope shrank from 8 top-level fields to 4.

#### Changes

1. **Removed `observe` + `reason` entirely**: These classic ReAct artifacts were listed as "optional" but the LLM wrote paragraphs for them every recursion. Removed from system prompt, parser, types, DB model (`ReactRecursion`), engine streaming, schemas, API serialization, and all frontend rendering/SSE handling.

2. **Moved `session_title` to ANSWER-only**: Previously the LLM generated a session title every recursion, but only the first write was ever persisted. Now `session_title` is an optional field inside `action.output` when `action_type == "ANSWER"`. The engine extracts it only on ANSWER actions and passes it to `_persist_session_title()`.

3. **Renamed `summary` → `message`**: Field semantics expanded from "brief status update" to "a note to the user about what you are doing, what you found, or what happens next. Every recursion must include this." Renamed across: system prompt, parser, types, DB column (`ReactRecursion.message`), state service, engine, schemas, SSE event type (`"message"`), API serialization, frontend types, SSE handling, and RecursionCard rendering.

4. **Removed `task_summary`**: Dead code — parsed from LLM output but never persisted, streamed, or displayed. The engine placed it in `event_data` as a top-level key, but the supervisor only reads `event_data["data"]`, so it was silently discarded every recursion.

5. **Removed `trace_id` from LLM-facing prompt**: The engine generates a UUID `trace_id` and injected it into the user message, asking the LLM to echo it back. The parser never extracted it — the engine used its own copy for all logging, DB records, and SSE events. Removed from `_build_recursion_user_payload()` and context service preview payloads.

6. **Deleted `current_state_schema.md`**: Dead file with no references, contained outdated Chinese descriptions.

#### New JSON Envelope

```json
{
  "iteration": 3,
  "message": "note to the user about current progress",
  "thinking_next_turn": false,
  "action": {
    "action_type": "CALL_TOOL | RE_PLAN | REFLECT | CLARIFY | ANSWER",
    "output": {},
    "step_id": "current step being executed",
    "step_status_update": []
  }
}
```

#### Token Savings

- Removed `observe` (~2-4 sentences) + `reason` (~2-4 sentences) per recursion: **~100-200 output tokens/recursion**
- Removed `trace_id` echo: **~5-10 output tokens/recursion**
- Removed `task_summary` on ANSWER: **~50-100 output tokens** on final recursion
- `session_title` only on ANSWER: **~20-30 output tokens** on non-ANSWER recursions
- **Estimated total: ~175-340 output tokens saved per recursion** (~30-40% of output tokens)

#### Files Modified

**System prompt**:
- `server/app/orchestration/react/system_prompt.md`

**Parser + Types**:
- `server/app/orchestration/react/parser.py`
- `server/app/orchestration/react/types.py`

**DB Model + State Service**:
- `server/app/models/react.py`
- `server/app/services/react_state_service.py`

**Engine + Orchestration**:
- `server/app/orchestration/react/engine.py`
- `server/app/orchestration/base/stream.py`
- `server/app/services/react_context_service.py`
- `server/app/services/channel_service.py`

**Schemas + API**:
- `server/app/schemas/react.py`
- `server/app/schemas/session.py`
- `server/app/services/session_service.py`
- `server/app/api/session.py`
- `server/app/api/operations.py`

**Frontend**:
- `web/src/pages/chat/types.ts`
- `web/src/pages/chat/ChatContainer.tsx`
- `web/src/pages/chat/utils/chatData.ts`
- `web/src/pages/chat/utils/chatPlan.ts`
- `web/src/pages/chat/components/RecursionCard.tsx`
- `web/src/utils/api.ts`
- `web/src/studio/operations/api.ts`

**Deleted**:
- `server/app/orchestration/react/current_state_schema.md`

**Tests**:
- `server/tests/orchestration/react/test_parser.py`
- `server/tests/orchestration/react/test_engine_stream_usage.py`
- `server/tests/orchestration/react/test_engine_thinking_mode.py`
- `server/tests/orchestration/react/test_engine_tool_batches.py`
- `server/tests/orchestration/react/test_context.py`
- `server/tests/orchestration/react/test_engine_compaction.py`
- `server/tests/services/test_react_state_service.py`
- `server/tests/services/test_session_service.py`
- `server/tests/services/test_channel_service.py`
- `web/src/pages/chat/components/RecursionCard.test.tsx`
- `web/src/pages/chat/utils/chatData.test.ts`
- `web/src/pages/chat/utils/chatPlan.test.ts`
- `web/src/studio/operations/SessionDetailPage.test.tsx`
- `web/src/studio/operations/diagnostics.test.ts`
- `web/src/studio/operations/OperationsHookReplayPanel.test.tsx`

**Note**: DB schema changed (removed `observe`/`reason` columns, renamed `summary` → `message`). Requires deleting `pivot.db` and restarting.

### 2.5 Compact Prompt Optimization ✅ DONE

**Result**: Rewrote compact prompt from Chinese to English, removed `meta` field, renamed `interaction_digest` → `task_digest` with Task-level granularity, simplified `important_files` schema. Compact output JSON reduced from 5 top-level sections to 5 (but significantly leaner).

#### Changes

1. **Chinese → English**: Full prompt rewritten — 14 rules, JSON schema descriptions, user instruction wrapper. Same ~50-60% token reduction on prompt tokens as system prompt (2.1).

2. **Removed `meta` field**: `merge_strategy` and `conflict_policy` were always output as fixed values. Removed from LLM output schema — these are system behaviors, not LLM decisions.

3. **`interaction_digest` → `task_digest`**: Renamed to eliminate ambiguity. Prompt now explicitly states: "Each entry represents one complete task cycle: the user's original request through to the agent's final ANSWER. Do NOT create one entry per recursion/iteration within a task." Removed `turn` field (array order = chronological order).

4. **`change_log` kept as-is**: Structured change tracking retained — valuable for precision in subsequent recursions.

5. **`important_files` simplified**: Removed `name`, `abstract`, `role` (input|output|intermediate|reference), `status` (active|superseded|deprecated|unknown). Retained only `path` + `description`.

#### New Compact Schema

```json
{
  "current_state": {
    "user_profile": [{"key": "", "value": ""}],
    "preferences": [{"key": "", "value": ""}],
    "constraints": [{"key": "", "value": ""}],
    "decisions": [""]
  },
  "task_digest": [
    { "user": "", "assistant": "", "artifacts": [""] }
  ],
  "change_log": [
    { "turn": 1, "type": "preference|constraint|decision|file|correction|other", "key": "", "from": "", "to": "", "reason": "" }
  ],
  "important_files": [
    { "path": "", "description": "" }
  ],
  "history_summary": ""
}
```

#### Token Savings

- Prompt: ~50-60% reduction (CJK → English)
- Output: `meta` removal (~30 tokens), `task_digest` fewer entries (Task-level vs per-turn), `important_files` fewer fields per entry (~50-70% per file entry)
- **Estimated total: ~40-50% compact output token reduction**

#### Files Modified

- `server/app/orchestration/compact/compact_prompt.py`

**Note**: No code or test changes needed — compact result is treated as an opaque JSON string throughout the system. No programmatic parsing of internal field names.

---

## Remaining Optimization Directions

---

## Priority Matrix (Updated)

| Priority | Direction | Token Savings | Effort | Status |
|---|---|---|---|---|
| **P0** | System Prompt EN + Simplify | ~50% (~1800 tokens/round) | Medium | ✅ Done |
| **P0** | Prompt Split (session vs task) | ~3000-4000 tokens/task | Medium | ✅ Done |
| **P0** | Tool Catalog Schema (Option 2) | ~60% (~1800 tokens/task) | Medium | ✅ Done |
| **P1** | Per-Recursion Plan Compression | ~97% before compaction (~387 tokens/round) | Medium | ✅ Done |
| **P1** | Assistant Output Format | ~30-40%/round output (~175-340 tokens) | Low | ✅ Done |
| **P2** | Compact Prompt Optimization | ~40-50% compact output | Low | ✅ Done |
| **P2** | Caching Strategy Hardening | Indirect | Medium-High | Pending |

---

## Remaining Implementation Sequence

1. ~~**Phase 3** (Payload optimization): Per-recursion plan compression (2.3) ✅~~
2. ~~**Phase 4** (Output tuning): Assistant output format cleanup (2.4) ✅~~
3. ~~**Phase 5** (Polish): Compact prompt optimization (2.5) ✅~~
4. **Phase 6** (Optional): Caching strategy hardening (2.6)

Each phase should include:
- Token count measurement before/after using `estimate_messages_tokens()`
- Agent behavior regression testing (ensure task completion rate is maintained)
