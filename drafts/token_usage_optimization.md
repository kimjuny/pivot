# Agent Token Usage Optimization

> Date: 2026-05-17
> Status: Phase 1 + Phase 2 partially complete

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

---

## Remaining Optimization Directions

### 2.3 Per-Recursion Payload: Plan History Compression

**Priority**: P1 | **Estimated Savings**: 30-50%/round (compounds over recursions) | **Effort**: Medium

#### Current State

Each recursion's user payload includes the full `current_plan` with every step containing 5+ fields:

```json
{
  "step_id": "1",
  "general_goal": "Overall goal of this step",
  "specific_description": "Detailed instructions...",
  "completion_criteria": "Acceptance criteria...",
  "status": "pending",
  "recursion_history": [
    {"iteration": 2, "summary": "..."},
    {"iteration": 3, "summary": "..."}
  ]
}
```

#### Current Issues

1. **Completed steps still carry full fields**: When `status=done`, the `general_goal`, `specific_description`, and `completion_criteria` are no longer needed — the LLM only needs to know it's completed.
2. **`recursion_history` grows linearly**: Even with `REACT_CURRENT_PLAN_HISTORY_LIMIT`, this accumulates over multi-recursion tasks.
3. **`action_result` tool results can be enormous**: `read_file` may return an entire file, `search` may return many matches — all injected directly into the payload.
4. **Plan is fully re-sent every recursion**: No diff/incremental mechanism.

#### Proposed Changes

1. **Compress completed steps**: When `status=done`, only keep `step_id` + `status` in the payload.
2. **Truncate `recursion_history` for completed steps**: Remove history entries for steps already done.
3. **Truncate large tool results**: When a tool result exceeds a threshold (e.g., 2000 chars), truncate with a hint: `"... (truncated, use read_file to see full content)"`.
4. **Long-term**: Consider sending plan diffs instead of full plan (higher complexity).

#### Implementation Location

`engine.py` → `_build_current_plan_payload()` and `_build_next_pending_action_result()`

#### Estimated Result

```
For a 5+ recursion task: 30-50% reduction in per-recursion payload tokens
Compounding effect: savings grow with each additional recursion
```

---

### 2.4 Assistant Output Format Optimization

**Priority**: P1 | **Estimated Savings**: 20-30%/round output tokens | **Effort**: Low

#### Current Issues

1. **`observe` and `reason` are "optional" but LLM writes them anyway**: The system prompt gives them descriptive templates, so the LLM tends to write a paragraph each time. These are "internal thinking" fields that shouldn't consume many output tokens.
2. **`session_title` generated every recursion**: But it's only used once (persisted on first write). The LLM wastes tokens generating it on recursions 2, 3, 4...
3. **`summary` required every recursion**: Many intermediate recursion summaries have low user value.

#### Proposed Changes

1. In the system prompt, explicitly instruct: `observe` and `reason` should only be populated at **critical decision points**; omit them during routine tool-calling recursions.
2. Only request `session_title` on `iteration=1`. Add instruction: "Omit `session_title` after the first recursion."
3. Add length guidance for `summary` (e.g., "≤50 chars") or only require it on `CALL_TOOL` and `ANSWER` actions.

#### Estimated Result

```
Per-recursion output tokens: -20-30%
```

---

### 2.5 Compact Prompt Optimization

**Priority**: P2 | **Estimated Savings**: 30-40% | **Effort**: Low

#### Current Issues

1. **`interaction_digest` requires per-turn records**: In long sessions this field becomes very large — but compaction's purpose is to compress, not create another large structure.
2. **`change_log` type classification is too granular**: 6 types (preference, constraint, decision, file, correction, other) increase compact output tokens.
3. **`meta` field** (`merge_strategy`, `conflict_policy`): Pure metadata that can be hardcoded rather than generated by the LLM.
4. **Written in Chinese**: Same CJK token overhead as system prompt.

#### Proposed Changes

- Remove `meta` field from required output (hardcode in system)
- Merge `change_log` into `history_summary` (single narrative instead of structured entries)
- Limit `interaction_digest` to recent N turns; older turns merged into `history_summary`
- Consider converting to English

---

### 2.6 Prompt Caching Strategy Hardening

**Priority**: P2 | **Savings**: Indirect (reduces redundant computation) | **Effort**: Medium-High

#### Current State

Already implements provider-level cache policies (Qwen block cache, Kimi prompt cache, Doubao `previous_response_id`, Anthropic auto-cache).

#### Current Issues

1. System prompt should always be cacheable (stable within a session), but its size affects first-fill cost.
2. User bootstrap prompt (with tool catalog) is stable within a task and could be cached.
3. Each new recursion payload pushes the cache window forward, potentially evicting earlier cached content.

#### Proposed Changes

- Keep system prompt as short as possible (aligned with 2.1) for reliable cache hits
- Ensure user bootstrap prompt follows immediately after system prompt for stable cache prefix
- For long sessions: consider extracting the tool catalog from message history (since it's stable within a task)

---

## Priority Matrix (Updated)

| Priority | Direction | Token Savings | Effort | Status |
|---|---|---|---|---|
| **P0** | System Prompt EN + Simplify | ~50% (~1800 tokens/round) | Medium | ✅ Done |
| **P0** | Prompt Split (session vs task) | ~3000-4000 tokens/task | Medium | ✅ Done |
| **P0** | Tool Catalog Schema (Option 2) | ~60% (~1800 tokens/task) | Medium | ✅ Done |
| **P1** | Per-Recursion Plan Compression | 30-50%/round (compounding) | Medium | Pending |
| **P1** | Assistant Output Format | 20-30%/round output | Low | Pending |
| **P2** | Compact Prompt Optimization | 30-40% | Low | Pending |
| **P2** | Caching Strategy Hardening | Indirect | Medium-High | Pending |

---

## Remaining Implementation Sequence

1. **Phase 3** (Payload optimization, 2-3 days): Per-recursion plan compression (2.3) + tool result truncation
2. **Phase 4** (Output tuning, 1-2 days): Assistant output format optimization (2.4)
3. **Phase 5** (Polish, 1-2 days): Compact prompt optimization (2.5) + caching verification (2.6)

Each phase should include:
- Token count measurement before/after using `estimate_messages_tokens()`
- Agent behavior regression testing (ensure task completion rate is maintained)
