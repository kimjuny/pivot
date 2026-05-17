# Agent Token Usage Optimization

> Date: 2026-05-17
> Status: Draft - Analysis Complete, Implementation Pending

## 1. Current Token Consumption Breakdown

### Message Structure Per Task

```
[System Prompt]           ← sent every recursion, ~3500-4500 tokens
[User Bootstrap Prompt]   ← injected once per task, ~3000-6000 tokens
  ├─ tools_description    ← JSON catalog, ~2000-4000 tokens (largest variable)
  ├─ skills               ← JSON metadata
  ├─ mandatory_skills     ← JSON content
  └─ workspace_guidance   ← markdown
[Recursion 1 User]        ← user_intent + current_plan + attachments
[Recursion 1 Assistant]   ← JSON + payload blocks, ~500-5000+ tokens
[Recursion 2 User]        ← current_plan + action_result (tool results!)
[Recursion 2 Assistant]   ← ...
...loops until ANSWER or max_iteration
```

**Key insight**: Each additional recursion resends **all** historical messages to the LLM. Every token saved in the prompt is multiplied by N (recursion count).

### Source Files

| Component | File |
|---|---|
| System prompt template | `server/app/orchestration/react/system_prompt.md` |
| User prompt template | `server/app/orchestration/react/user_prompt.md` |
| Prompt builder | `server/app/orchestration/react/prompt_template.py` |
| Tool catalog generator | `server/app/orchestration/tool/manager.py` → `to_text_catalog()` |
| Tool metadata | `server/app/orchestration/tool/metadata.py` |
| Tool implementations | `server/app/orchestration/tool/builtin/*.py` |
| Per-recursion payload | `server/app/orchestration/react/engine.py` → `_build_recursion_user_payload()` |
| Plan payload builder | `server/app/orchestration/react/engine.py` → `_build_current_plan_payload()` |
| Compact prompt | `server/app/orchestration/compact/compact_prompt.py` |
| Response parser | `server/app/orchestration/react/parser.py` |

---

## 2. Optimization Directions (Sorted by Impact)

### 2.1 System Prompt: Chinese → English + Redundancy Elimination

**Priority**: P0 | **Estimated Savings**: ~50% (~1800 tokens/round) | **Effort**: Medium

#### Current Issues

1. **CJK characters are extremely token-expensive**: Each Chinese character consumes 2-3 tokens in mainstream tokenizers (GPT, Claude, etc.), while an English word typically costs ~1 token. The same semantic content in Chinese costs ~1.8-2.5x more tokens than English.
2. **"Agent 权限运行边界" section (lines 10-14)** is runtime permission logic irrelevant to LLM decision-making. The LLM doesn't need to know about Agent use/edit permission rules — those are Studio-side configuration constraints.
3. **JSON Schema and Examples heavily overlap**: Section 3.1 defines the full outer structure, then sections 3.2-3.6 each repeat a complete JSON example. Low information density.
4. **`thinking_next_turn` rules (lines 53-58)**: 5 detailed conditions are overly verbose; can be condensed to 1-2 sentences.
5. **Repetitive emphasis**: "禁止输出Markdown代码围栏" appears at least 3 times across the document.
6. **`observe` and `reason` descriptions**: Marked as "选填" (optional) but given verbose template descriptions that encourage the LLM to write long paragraphs.

#### Proposed Changes

- Convert entire system prompt from Chinese to English
- Remove "Agent 权限运行边界" section entirely
- Consolidate repeated format rules (no markdown fences, no extra text) into a single rules block
- Merge JSON examples: show the full structure once in 3.1, then each action type only shows the `action.output` diff
- Condense `thinking_next_turn` conditions to 2 sentences
- Reduce `observe`/`reason` descriptions to discourage verbose output

#### Estimated Result

```
Before: ~197 lines, ~3500-4500 tokens
After:  ~80-100 lines, ~1500-1800 tokens
Savings: ~50%
```

---

### 2.2 Tool Catalog: Compress Tool Descriptions

**Priority**: P0 | **Estimated Savings**: ~60% (~1800 tokens/task) | **Effort**: Low

#### Current State

`to_text_catalog()` outputs pretty-printed JSON (indent=2) with full docstrings and complete JSON Schemas.

| Tool | Param Count | Description Length |
|---|---|---|
| `web_search` | **21** | ~3,100 chars |
| `edit_file` | 2 | ~1,450 chars |
| `read_file` | 3 | ~1,180 chars |
| `search` | 6 | ~1,150 chars |
| `write_file` | 2 | ~780 chars |
| `list_directories` | 2 | ~480 chars |
| `run_bash` | 2 | ~460 chars |

#### Current Issues

1. **`web_search` dominates**: 21 parameters, ~3100 chars. Most params (`include_favicon`, `safe_search`, `auto_parameters`, `include_usage`, etc.) are almost never used by the Agent.
2. **Full docstrings in prompt**: Each tool includes its complete docstring (with Args, Returns, Raises sections). The LLM only needs to know what the tool does and what parameters it accepts.
3. **Duplicate descriptions**: JSON Schema `description` fields duplicate the tool-level `description`.
4. **`tool_type` field**: Not useful for LLM decision-making.
5. **Pretty-printed JSON**: `indent=2` adds significant whitespace overhead.

#### Proposed Changes

1. Add a `short_description` field to `ToolMetadata` (1-2 sentence summary). Use it in `to_text_catalog()` instead of the full docstring.
2. For `web_search`: expose only high-frequency parameters in the schema (`query`, `max_results`, `time_range`, `search_depth`, `include_domains`, `exclude_domains`). Hide the rest as internal.
3. Remove parameter-level `description` from JSON Schema (the short tool description covers it).
4. Use `indent=None` (compact JSON) or a custom compact serializer.
5. Remove `tool_type` from catalog output.
6. Alternatively: implement a `to_compact_catalog()` method that produces a minimal representation.

#### Implementation Sketch

```python
# In ToolMetadata
def to_compact_dict(self) -> dict[str, Any]:
    """Minimal representation for LLM consumption."""
    compact_params = {
        "type": self.parameters.get("type", "object"),
        "required": self.parameters.get("required", []),
        "properties": {
            name: {"type": schema.get("type", "string")}
            for name, schema in self.parameters.get("properties", {}).items()
            if not schema.get("internal", False)  # hide internal params
        }
    }
    return {
        "name": self.name,
        "description": self.short_description,
        "parameters": compact_params,
    }
```

#### Estimated Result

```
Before: ~8000-10000 chars, ~2000-4000 tokens
After:  ~3000-4000 chars, ~800-1200 tokens
Savings: ~60%
```

---

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

## 3. Priority Matrix

| Priority | Direction | Token Savings | Effort | Risk |
|---|---|---|---|---|
| **P0** | Tool Catalog Compression | ~60% (~1800 tokens/task) | Low | Very Low |
| **P0** | System Prompt EN + Simplify | ~50% (~1800 tokens/round) | Medium | Low (test format compliance) |
| **P1** | Per-Recursion Plan Compression | 30-50%/round (compounding) | Medium | Low |
| **P1** | Assistant Output Format | 20-30%/round output | Low | Low |
| **P2** | Compact Prompt Optimization | 30-40% | Low | Low |
| **P2** | Caching Strategy Hardening | Indirect | Medium-High | Medium |

---

## 4. Aggregate Impact Estimate

For a typical 5-recursion task:

| Component | Before (est.) | After (est.) | Savings |
|---|---|---|---|
| System Prompt | ~4000 × 5 = 20,000 | ~1800 × 5 = 9,000 | **-55%** |
| Tool Catalog (bootstrap) | ~3000 × 1 = 3,000 | ~1200 × 1 = 1,200 | **-60%** |
| Per-Recursion Payload | ~2000 × 5 = 10,000 | ~1000 × 5 = 5,000 | **-50%** |
| Assistant Output | ~2000 × 5 = 10,000 | ~1400 × 5 = 7,000 | **-30%** |
| **Total (no cache)** | **~43,000** | **~22,200** | **~48%** |

With prompt caching, actual cost savings depend on cache hit rate, but output tokens (not cached) still save ~30%. Compaction triggers will also fire less frequently since context grows more slowly.

---

## 5. Implementation Sequence (Recommended)

1. **Phase 1** (Quick wins, 1-2 days): Tool catalog compression (2.2)
2. **Phase 2** (Core prompt, 2-3 days): System prompt rewrite to English (2.1) + assistant output format tuning (2.4)
3. **Phase 3** (Payload optimization, 2-3 days): Per-recursion plan compression (2.3) + tool result truncation
4. **Phase 4** (Polish, 1-2 days): Compact prompt optimization (2.5) + caching verification (2.6)

Each phase should include:
- A/B testing against existing prompts to verify format compliance
- Token count measurement before/after using `estimate_messages_tokens()`
- Agent behavior regression testing (ensure task completion rate is maintained)
