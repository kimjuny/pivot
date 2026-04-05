# Dynamic Skill Loading For ReAct

## Summary

Pivot should remove the current pre-task Skill Resolution flow and replace it
with a dynamic skill loading model.

Under the new design:

- The runtime no longer asks a separate LLM to pre-select skills before the
  first recursion.
- The task bootstrap prompt injects only compact metadata for every skill that
  is visible to the current agent runtime.
- The agent decides during normal ReAct iterations whether it needs a skill.
- When needed, the agent reads the full `SKILL.md` file from the sandbox path
  by using `read_file` or another allowed file-reading mechanism.
- Skills remain mounted into the sandbox so the agent can read not only
  `SKILL.md` but also other package files if the skill workflow requires them.

This keeps the runtime simpler, more transparent, and closer to Pivot's
directory-based skill model.

## Background

Today Pivot has a dedicated Skill Resolution stage before task execution.
Conceptually, the flow is:

1. Load visible skill metadata.
2. Optionally run a resolver-only LLM to select relevant skills.
3. Persist resolution progress and result.
4. Inject the selected skill markdown content directly into the task bootstrap
   prompt.
5. Start normal ReAct recursion after that.

This design has several drawbacks:

- It adds one extra runtime phase before real task execution.
- It requires a second LLM configuration on the agent model.
- It creates extra stream events, task persistence fields, and frontend states
  that only exist to support this pre-processing phase.
- It hides an important runtime decision from the agent itself. The agent sees
  the selected full-text skill content, but it does not choose when to fetch it.
- It makes the prompt heavier up front by injecting whole skill markdown files
  before the model has proven they are necessary.

Pivot is still pre-launch, so this is a good time to simplify the architecture
instead of carrying forward a more complex compatibility layer.

## Goals

- Remove the dedicated Skill Resolution runtime phase entirely.
- Remove the resolver-only LLM configuration from agent runtime design.
- Expose all runtime-visible skills to the agent as compact metadata only.
- Let the agent fetch full skill content on demand during ReAct iterations.
- Keep skill access aligned with the existing sandbox security model.
- Preserve the agent-level skill allowlist model through `skill_ids`.
- Standardize skill entry files to `SKILL.md` so the runtime path contract is
  simple and stable.
- Keep service-layer ownership clear for all persistence and filesystem work.

## Non-Goals

- Do not redesign the broader skill registry and visibility model.
- Do not remove skill mounting into the sandbox.
- Do not change skill package identity rules.
- Do not introduce a new dedicated builtin tool only for loading skills in the
  first implementation. Existing file access tools are sufficient.
- Do not preserve backward compatibility for the old Skill Resolution UX or
  stored task payloads if a cleaner model is available.

## Design Principles

- Metadata first, full content on demand.
- One runtime flow, not a pre-flow plus runtime.
- Stable sandbox paths over entry-file ambiguity.
- Agent autonomy over hidden orchestration.
- Small bootstrap prompts, heavier context only when needed.
- Service-mediated persistence and filesystem changes only.

## Proposed Runtime Model

### High-Level Flow

For each task:

1. Build the request-scoped tool catalog.
2. Resolve the visible skills for the current user and current agent allowlist.
3. Mount all allowed visible skills into the sandbox under `/workspace/skills`.
4. Inject skill metadata into the bootstrap user prompt at `{{skills}}`.
5. Start normal ReAct recursion immediately.
6. During any iteration, the agent may read one skill's `SKILL.md` file when it
   decides that the skill is relevant.

This replaces the old flow:

```text
load visible skills
-> optional resolver LLM
-> selected skill full-text prompt injection
-> start ReAct recursion
```

with:

```text
load visible skills
-> mount skills
-> inject metadata only
-> start ReAct recursion
-> agent reads SKILL.md on demand if needed
```

### Why This Model Is Better

- It removes one artificial phase boundary from task execution.
- It removes duplicated logic across supervisor, channel, persistence, and UI.
- It makes skill usage observable through ordinary tool calls rather than a
  hidden pre-selection step.
- It better matches the true skill abstraction: a directory package whose full
  content can be explored when needed.
- It avoids spending prompt budget on whole skills that might never be used.

## Prompt Injection Design

### Injection Location

The injection point remains:

- `server/app/orchestration/react/user_prompt.md`
- section `## 6. Related Skills`
- placeholder `{{skills}}`

The text guidance around that placeholder should continue to explain that the
list contains only metadata and that the agent should read the skill file by
path when deeper detail is needed.

### Injected Data Shape

`{{skills}}` should render as a JSON array.

Each item must contain exactly:

- `name`
- `description`
- `path`

Example:

```json
[
  {
    "name": "coding",
    "description": "General coding workflow for reading, editing, testing, and validating code changes.",
    "path": "/workspace/skills/coding/SKILL.md"
  },
  {
    "name": "research_notes",
    "description": "Reusable research workflow for evidence collection and synthesis.",
    "path": "/workspace/skills/research_notes/SKILL.md"
  }
]
```

### Actual Prompt Example

The rendered section should look like this:

```md
## 6. Related Skills

- Below is the list of every Skill you are allowed to use in this task. Only
  compact metadata is injected here: `name`, `description`, and `path`.
  If you determine that a skill is relevant during an iteration, read the full
  `SKILL.md` file from the provided path before relying on it.

```json
[
  {
    "name": "coding",
    "description": "General coding workflow for reading, editing, testing, and validating code changes.",
    "path": "/workspace/skills/coding/SKILL.md"
  },
  {
    "name": "research_notes",
    "description": "Reusable research workflow for evidence collection and synthesis.",
    "path": "/workspace/skills/research_notes/SKILL.md"
  }
]
```
```

### Formatting Rules

- The JSON array should be deterministic.
- Items should be sorted by `name`.
- Duplicate names must not appear.
- If no skills are available, inject `[]`.
- `description` should be passed through as stored metadata with no forced
  single-line normalization or truncation in this phase.

## Skill Path Contract

### New Contract

Every runtime-visible skill should be readable at:

```text
/workspace/skills/{skill_name}/SKILL.md
```

This path should be considered part of the runtime contract.

### Why Standardization Is Needed

The current implementation allows multiple entry filenames such as:

- `SKILL.md`
- `skill.md`
- `Skill.md`
- `{skill_name}.md`

That flexibility is convenient for ingestion, but it weakens the runtime
contract. The agent should not have to guess which filename exists inside the
sandbox. A stable path is materially better for prompt design and model
reliability.

### Decision Already Agreed

Based on discussion, Pivot should standardize on `SKILL.md` and migrate current
skills accordingly.

### Recommended Ingestion Rule After Migration

Pivot may continue to accept legacy incoming filenames during import or local
write flows, but once the skill is stored into the canonical workspace layout,
the persisted entry file should become:

```text
{skill_root}/SKILL.md
```

This keeps authoring flexible enough while keeping runtime deterministic.

## Skill Visibility And Mounting

The new model does not change the visibility rules:

- Builtin skills remain always visible.
- Shared skills remain visible to all users.
- Private skills remain visible only to their owner.

The new model also does not change the agent allowlist behavior:

- `skill_ids = null` means all visible skills are available.
- `skill_ids = []` means no skills are available.
- A non-empty `skill_ids` array restricts the visible set to that allowlist.

For sandbox execution:

- All allowed visible skills should still be mounted.
- The runtime should not mount only a pre-selected subset.
- Extension-contributed skills should follow the same metadata injection and
  mounting rules if they are visible to the agent runtime.

## Required Backend Changes

### 1. Replace Full-Text Skill Prompt Injection

The current helper that builds prompt blocks from full skill markdown should be
removed or retired from runtime usage.

Instead, add a new helper whose job is to build the metadata JSON injected into
`{{skills}}`.

Recommended service responsibility:

- Input: username, allowed skill names, optional extension skill payloads
- Output: deterministic JSON string for prompt injection

Suggested helper shape:

```python
def build_visible_skills_metadata_prompt_json(...) -> str:
    ...
```

This helper should live in the skill service layer because it operates on
persisted skill registry metadata and runtime-visible skill resolution.

### 2. Remove Task-Startup Skill Resolution

The task supervisor should stop doing all of the following:

- checking `runtime_config.skill_resolution_llm_id`
- deciding whether skill resolution should run
- calling the resolver LLM
- selecting skills before recursion begins
- publishing `skill_resolution_start`
- publishing `skill_resolution_result`
- persisting `task.skill_selection_result`
- passing selected full-text skill prompt blocks into the engine

Instead, it should:

- resolve the allowed visible skills once
- mount them all
- inject metadata JSON into the bootstrap prompt
- start normal ReAct execution immediately

### 3. Remove Channel Skill Resolution Branches

Channel-oriented execution currently contains logic that mirrors the old skill
resolution model. That code should be removed rather than partially preserved.

There should be no special channel-only text like:

- `Matched skills: ...`
- `Matched skills: none`

If the agent wants to tell the user that it is loading a skill, that should
come from ordinary assistant progress behavior, not a backend-only synthetic
progress event.

### 4. Update Prompt Estimation

Prompt estimation for the frontend must use the same skill metadata injection as
real runtime bootstrap messages.

Otherwise, estimated prompt usage will be lower than actual runtime usage.

### 5. Keep Sandbox Mount Logic

The existing mount logic is still useful and should remain, but it should
operate on the final allowed visible skill set, not a resolver-selected subset.

## Required Data Model And API Changes

### Agent Model

Remove `skill_resolution_llm_id` from:

- database model
- API schemas
- agent create and update handlers
- release snapshots
- test snapshots
- runtime config structures
- frontend types
- agent settings UI

This field becomes dead once the dedicated resolver phase no longer exists.

### Task Model

Remove `skill_selection_result` from:

- task database model
- task serialization
- session task history responses
- frontend task timeline models
- tests and fixtures

There is no longer a meaningful persisted concept of skill resolution result.

### Event Schema

Remove these stream event types:

- `skill_resolution_start`
- `skill_resolution_result`

No replacement event type is required for the first implementation.

## Required Frontend Changes

The frontend should remove the dedicated Skill Resolution experience
end-to-end.

This includes:

- the special task status `skill_resolving`
- skill resolution progress cards
- task history reconstruction from `skill_selection_result`
- stream event handling for `skill_resolution_start`
- stream event handling for `skill_resolution_result`
- tests and replay fixtures that depend on those events

The task should move directly from normal send/start state into normal running
state.

## Migration Plan

### Phase 1: Canonical Skill Entry File Migration

Standardize every persisted skill directory so that its entry file is:

```text
SKILL.md
```

Migration responsibilities:

- Builtin skills should be renamed to `SKILL.md`.
- User-created and imported skills should be normalized to `SKILL.md`.
- Extension-packaged skills should already require `SKILL.md` as their package
  contract and should stay that way.
- Registry metadata should continue to reflect the stored canonical filename.

Recommended behavior for the service layer:

- when saving or importing a skill, rewrite or move the entry file to `SKILL.md`
- reject malformed packages that do not provide a recognizable entry markdown
  file
- keep the directory name equal to the globally unique skill name

### Phase 2: Runtime Refactor

- Add metadata JSON builder helper.
- Replace full-text prompt injection with metadata injection.
- Remove resolver startup flow from task supervisor.
- Remove resolver helper usage from channel service and any related flow.
- Update prompt estimation to use the same metadata injection path.

### Phase 3: Model, Schema, And UI Cleanup

- remove `skill_resolution_llm_id`
- remove `skill_selection_result`
- remove stream event enums and parsing
- remove frontend states, cards, and tests

### Phase 4: Documentation Cleanup

Update:

- `docs/react_flow.md`
- `docs/skills.md`
- any architecture notes that still describe Skill Resolution

The new docs should explain that skills are discovered by metadata, mounted into
the sandbox, and read on demand by the agent.

## Suggested Implementation Order

1. Canonicalize persisted skill entry files to `SKILL.md`.
2. Add one skill metadata prompt builder in the service layer.
3. Switch runtime bootstrap prompt generation to metadata injection.
4. Remove startup skill resolution from the task supervisor.
5. Remove channel-service branches and progress text related to resolution.
6. Remove task persistence fields and stream event types.
7. Remove frontend Skill Resolution UI and state handling.
8. Update tests and docs.

This order reduces the time spent in mixed-mode states.

## Risks And Mitigations

### Risk: The Agent Ignores Skills More Often

Because full skill text is no longer pre-injected, the model might sometimes
fail to read a skill even when it would help.

Mitigations:

- keep the `Related Skills` prompt wording explicit
- provide a stable path contract
- keep descriptions reasonably informative
- prefer deterministic JSON formatting over prose formatting

### Risk: More Tool Calls In Some Tasks

Some tasks that previously got skill text for free will now need one extra
`read_file` call.

Mitigations:

- this cost is acceptable because it happens only when a skill is actually used
- it usually saves prompt tokens across tasks that do not need any skill
- it makes the decision trace more interpretable

### Risk: Path Contract Drift

If future save/import paths stop producing `SKILL.md`, the prompt path guidance
becomes misleading.

Mitigations:

- enforce `SKILL.md` as the persisted canonical entry filename
- add tests around save, import, and mount behavior

### Risk: Mixed Runtime During Rollout

If old frontend code expects skill resolution events while backend no longer
emits them, task rendering may be inconsistent.

Mitigations:

- land backend and frontend cleanup in the same development branch
- update replay fixtures and integration tests together

### Risk: Database Drift During Refactor

Removing task and agent columns will require model and schema cleanup.

Mitigations:

- use a single focused migration for schema changes
- because Pivot is pre-launch, favor clean removal over compatibility shims
- if local development databases drift during implementation, recreating the
  local database is acceptable

## Testing Plan

### Backend

- skill service tests for metadata JSON builder
- skill save/import tests proving canonical `SKILL.md` output
- runtime tests confirming metadata injection appears in bootstrap prompt
- supervisor tests proving no skill resolution startup events are emitted
- task history tests proving no `skill_selection_result` payload is returned
- release snapshot and test snapshot tests after removing
  `skill_resolution_llm_id`

### Frontend

- chat timeline tests after removing `skill_resolving`
- stream event parsing tests after removing skill resolution events
- agent settings tests after removing resolver LLM controls
- session/task replay tests after removing `skill_selection_result`

### End-To-End

- agent with allowed skills can read `/workspace/skills/{name}/SKILL.md`
- agent with restricted `skill_ids` only sees permitted skill metadata
- agent with no available skills receives `[]`

## Open Questions Requiring Product Decision

### 1. Should the runtime inject extension-contributed skills into `{{skills}}`?

Recommendation:

- Yes. If a packaged extension skill is visible to the current runtime and
  mounted into the sandbox, it should be treated exactly like any other skill in
  the metadata list.

Why:

- A mixed model would be harder for the agent to reason about.
- The prompt should reflect the real accessible runtime surface.

### 2. Should Pivot add a dedicated builtin tool like `read_skill` later?

Recommendation:

- Not in the first implementation.

Why:

- `read_file` already works for `/workspace` paths.
- Adding a dedicated tool early increases surface area without proving need.
- We can revisit this later if telemetry shows repeated awkward skill-loading
  patterns.

### 3. Should runtime-visible skill metadata include anything besides
`name`, `description`, and `path`?

Recommendation:

- No for now.

Why:

- The prompt should stay minimal.
- More fields increase prompt size and create more contract surface.
- The current requirement is satisfied by these three fields.

## Final Recommendation

Pivot should fully replace Skill Resolution with dynamic skill loading.

The system should:

- canonicalize all persisted skill entry files to `SKILL.md`
- mount every runtime-allowed visible skill
- inject only `name`, `description`, and `path` metadata into `{{skills}}`
- let the agent read `/workspace/skills/{skill_name}/SKILL.md` on demand
- remove the resolver-only LLM model, task persistence, stream events, and UI
  that existed only for the old pre-selection flow

This design is simpler, more legible, more agentic, and a better fit for
Pivot's long-term directory-based skill architecture.
