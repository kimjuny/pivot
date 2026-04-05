# Mandatory Skill Mention Design

## Summary

This document proposes a full-stack design for the new "Mandatory Skill"
interaction in the ReAct chat composer.

The goal is:

- let the user type `/` in the chat composer to open a skill picker
- show only the current agent runtime-visible skill metadata
- let the user explicitly choose one or more skills for the current turn
- make those choices visually obvious in the composer
- inject the chosen skills into `{{mandatory_skills}}` in
  `server/app/orchestration/react/user_prompt.md`
- inject the full `SKILL.md` content, not only metadata

This design intentionally builds on the current dynamic skill loading model:

- `{{skills}}` remains the runtime-visible metadata catalog
- `{{mandatory_skills}}` becomes a task-scoped explicit hint channel driven by
  the user
- the backend still mounts skills into `/workspace/skills/<name>/SKILL.md`

## Current Baseline

After reading:

- `docs/react_flow.md`
- `server/app/orchestration/react/system_prompt.md`
- `server/app/orchestration/react/user_prompt.md`
- `drafts/skill_resolution.md`

the current model is:

1. The task bootstrap prompt is injected once per task.
2. `{{skills}}` already carries compact metadata for the agent-visible skill set.
3. The agent can dynamically read a skill file during recursion when needed.
4. `{{mandatory_skills}}` now exists in the prompt template, but there is not yet
   any frontend or backend path filling it.

So the missing piece is not the skill-loading architecture itself. The missing
piece is the user-driven explicit selection path from chat composer to prompt
bootstrap injection.

## Design Goals

- keep the runtime mental model simple
- avoid hiding important behavior in frontend-only text tricks
- keep the backend authoritative for skill resolution and prompt injection
- preserve clear UX: users should know which skills they have explicitly chosen
- keep prompt estimation accurate when mandatory skills are selected
- avoid direct persistence-layer access outside services

## Important Constraint

There is one key technical constraint we should be explicit about:

`Badge` components cannot literally render "inside" a native HTML
`<textarea>`.

A native textarea only stores and displays plain text. It cannot contain real
inline React nodes.

That means the requirement "render a skill as badge in the Textarea" can only
be implemented in one of these ways:

1. Visual overlay:
   Render a mirror layer above the textarea that paints badges and plain text,
   while the real textarea remains underneath for editing.
2. Rich text editor:
   Replace textarea with a contenteditable-based editor or editor framework.
3. Hybrid visible-token row:
   Keep textarea plain text, but render selected skill badges in a compact row
   attached to the composer.

My recommendation for v1 is:

- use a hybrid approach that feels inline enough without replacing the editor
- keep the underlying textarea plain text
- render selected mandatory skill badges in a dedicated composer row near the
  textarea, not inside native text content

If strict inline badge rendering is mandatory, then we should accept the extra
complexity and build the overlay approach. I describe both below.

## Recommended UX

### User Flow

1. The user focuses the composer and types `/`.
2. A mention picker opens near the caret or near the composer input area.
3. The picker lists only the current agent's runtime-visible skills.
4. Each item shows:
   - `name`
   - `description`
   - optional scope/source tag if useful
5. The user chooses a skill, for example `sample_skill`.
6. The composer records that selection as a mandatory skill for this turn.
7. The composer visually shows the chosen skill as a badge.
8. When the message is sent, the request payload includes:
   - the plain user message text
   - the explicit mandatory skill names
9. The backend resolves those names to real skills and injects their full prompt
   payload into `{{mandatory_skills}}`.

### Recommended Composer Presentation

I recommend showing selected mandatory skills in a compact row attached to the
composer, similar in spirit to reply context:

- placement: above the textarea, below reply context if both exist
- visual: `Badge` tokens with remove buttons
- behavior: selecting a skill does not pollute the raw user message text

Why this is the most practical v1:

- avoids fake inline rendering hacks
- avoids brittle cursor math
- keeps editing behavior native and reliable
- keeps selected mandatory skills "obvious" exactly as intended

If we want a more ChatGPT-like slash insertion feel, we can still trigger the
picker from `/`, but once selected, convert that slash token into a badge row
selection rather than an inline rendered badge.

## Alternative UX: Inline Overlay

If product direction strongly prefers "badge appears in the text body", we can
build an overlay renderer:

- the actual textarea still contains a serialized marker token
- a positioned mirror layer renders:
  - normal text as text spans
  - mentioned skills as `Badge`
- the textarea text color becomes transparent while caret remains visible

This can work, but it adds complexity:

- line wrapping must perfectly match textarea layout
- badge width changes make cursor mapping harder
- selection, IME, copy/paste, and mobile behavior get trickier
- accessibility is substantially more complex

I do not recommend this as the first version unless true inline rendering is a
hard requirement.

## Frontend Design

### Existing Relevant Components

The current building blocks already exist:

- `web/src/pages/chat/components/ChatComposer.tsx`
- `web/src/components/ui/popover.tsx`
- `web/src/components/ui/command.tsx`
- `web/src/components/ui/badge.tsx`

Note: there is currently a separate project issue where
`@radix-ui/react-popover` is missing from `web/package.json`, and
`web/src/components/ui/popover.tsx` therefore breaks full type-check/lint.
That needs to be fixed before this feature can be fully shipped.

### New Frontend State

The composer should track:

- `inputMessage: string`
- `mandatorySkills: MandatorySkillChip[]`
- `isSkillMentionOpen: boolean`
- `skillMentionQuery: string`
- `skillMentionAnchor`: caret or composer anchor metadata

Suggested shape:

```ts
interface MandatorySkillChip {
  name: string;
  description: string;
  path: string;
}
```

This frontend state should be treated as turn-scoped draft state only.

### Skill Picker Data Source

The picker needs the current agent's runtime-visible skills.

Recommended backend contract:

- add a dedicated endpoint returning the skill metadata visible to the current
  agent runtime for the current user

Suggested response shape:

```json
[
  {
    "name": "sample_skill",
    "description": "Example skill description",
    "path": "/workspace/skills/sample_skill/SKILL.md"
  }
]
```

Why I recommend a dedicated endpoint instead of assembling on the client:

- it reuses the same backend allowlist and visibility rules as runtime prompt
  injection
- it avoids duplicating filtering rules in React
- it avoids fetching all visible skills and then re-implementing allowlist logic
  in the browser
- it stays correct when extension-bundled skills participate in runtime

Suggested service reuse:

- `list_allowed_visible_skills(...)`
- `build_skills_metadata_prompt_json(...)`

but exposed as structured JSON rather than pre-rendered prompt text.

### Slash Trigger Behavior

Recommended slash behavior:

- open the skill picker only when `/` starts a new token
- examples:
  - `" /"` opens
  - `"\n/"` opens
  - `"/sam"` filters
- do not open when slash is in paths or URLs such as:
  - `/workspace/foo`
  - `https://...`

Picker filtering should use:

- skill name
- description

### Selection Behavior

When the user selects `sample_skill`:

- add it to `mandatorySkills`
- remove the trigger token like `/sam` from the draft text
- close the picker
- keep focus in the composer

Deduping rule:

- selecting the same skill twice should not create duplicates

Ordering rule:

- preserve insertion order

Removal rule:

- each badge should have an `x` affordance
- removing a badge updates `mandatorySkills`

### Composer Rendering Recommendation

Recommended v1 rendering order:

1. reply context row if present
2. mandatory skill badge row if at least one exists
3. textarea
4. bottom action row

That keeps mandatory skill chips visually prominent and avoids fighting native
textarea limitations.

### Optional Future Enhancement

If we later want stronger inline affordance, we can add a ghost prefix inside
the textarea area such as:

- `Using: [sample_skill]`

but still keep the actual badge row authoritative.

## Backend Design

### Guiding Principle

The backend should not rely on scraping markdown links out of freeform user
text as the primary contract.

Even if the frontend internally represents a selected skill as something like:

```md
[sample_skill](/workspace/skills/sample_skill/SKILL.md)
```

the request payload should still send structured mandatory skill names.

Recommended request contract:

```json
{
  "agent_id": 1,
  "message": "Please solve this with the selected skill.",
  "mandatory_skill_names": ["sample_skill"]
}
```

Why structured transport is better:

- avoids brittle regex parsing
- lets the UI evolve without breaking backend extraction
- supports exact validation against runtime-visible skills
- makes prompt estimation straightforward
- makes audit/history clearer if we later persist the list

### API Changes

#### 1. Extend task launch request

Files:

- `server/app/schemas/react.py`
- `server/app/api/react.py`
- `server/app/services/react_task_supervisor.py`
- `web/src/utils/api.ts`

Add:

```py
mandatory_skill_names: list[str] = Field(default_factory=list)
```

#### 2. Add runtime-visible skill metadata endpoint

Recommended new endpoint:

- `GET /agents/{agent_id}/runtime/skills`

or consumer equivalent if this chat surface is strictly consumer-facing.

Response:

```json
[
  {
    "name": "sample_skill",
    "description": "...",
    "path": "/workspace/skills/sample_skill/SKILL.md"
  }
]
```

Implementation should reuse service-layer skill visibility logic.

### Validation Rules

When a task launch request arrives with `mandatory_skill_names`:

1. Normalize names:
   - trim whitespace
   - drop empty items
   - preserve first-seen order
   - dedupe duplicates
2. Resolve the runtime-visible skill set for this agent/user/runtime.
3. Reject any selected skill not visible to this runtime.

Suggested failure:

- `400 Bad Request`
- message like:
  `"Mandatory skill 'sample_skill' is not visible to this agent runtime."`

This prevents clients from forcing arbitrary path injection.

### Prompt Injection Contract

`{{mandatory_skills}}` should be rendered as a JSON array.

Each item should include:

- `name`
- `description`
- `path`
- `content`

Example:

```json
[
  {
    "name": "sample_skill",
    "description": "Example skill description",
    "path": "/workspace/skills/sample_skill/SKILL.md",
    "content": "# full markdown content..."
  }
]
```

This matches your stated requirement and keeps the prompt explicit.

### Recommended Service Additions

I recommend adding a new service-layer helper near `skill_service.py`:

- `build_mandatory_skills_prompt_json(...)`

Suggested behavior:

- input:
  - session
  - username
  - raw agent allowlist
  - selected skill names
  - optional extension skills
- output:
  - deterministic JSON string for `{{mandatory_skills}}`

Pseudo-shape:

```py
def build_mandatory_skills_prompt_json(
    session: Session,
    username: str,
    *,
    raw_skill_ids: str | None,
    selected_skill_names: list[str],
    extra_skills: list[dict[str, str]] | None = None,
) -> str:
    ...
```

For registry-backed skills, the service should read the actual markdown source.
For extension-bundled runtime skills, it should read the bundle entry file from
the registered location.

### Prompt Template Changes

`server/app/orchestration/react/prompt_template.py` currently replaces:

- `{{tools_description}}`
- `{{skills}}`

It should be extended to also replace:

- `{{mandatory_skills}}`

Recommended signature change:

```py
def build_runtime_user_prompt(
    tool_manager: ToolManager | None = None,
    skills: str = "",
    mandatory_skills: str = "[]",
    prefix_blocks: list[str] | None = None,
    suffix_blocks: list[str] | None = None,
) -> str:
```

Then:

```py
.replace("{{mandatory_skills}}", mandatory_skills)
```

### Task Supervisor Flow

In `ReactTaskSupervisor._run_task(...)`, before `engine.run_task(...)`, build:

- `skills_metadata_json`
- `mandatory_skills_json`

and pass both into `engine.run_task(...)`.

Then `ReactEngine.run_task(...)` should pass both into
`build_runtime_user_prompt(...)`.

### Context Usage Estimation

This feature changes prompt size. That means the context estimator must know
about mandatory skills too.

Files:

- `server/app/schemas/react.py`
- `server/app/services/react_context_service.py`
- `web/src/utils/api.ts`
- `web/src/pages/chat/ChatContainer.tsx`

Add `mandatory_skill_names` to the context-estimation request so:

- selecting a mandatory skill updates the ring estimate before send
- users can see the prompt cost of injecting full skill content

This is important because mandatory skills can be much larger than the compact
metadata catalog.

## Persistence Strategy

There are two viable strategies.

### Option A: No new DB persistence for v1

Use launch-request data only.

Pros:

- minimal schema change
- simplest first implementation

Cons:

- full session history cannot clearly reconstruct which mandatory skills were
  chosen
- prompt/debug tooling cannot easily inspect the selected mandatory skills after
  the fact

### Option B: Persist selected mandatory skills on `ReactTask`

Add a JSON field such as:

- `mandatory_skill_names_json`

Pros:

- task history/debug can show explicit user-selected skills
- future replays and diagnostics are easier
- cleaner observability

Cons:

- requires one schema change

Recommendation:

- Option B is better if we want this feature to be first-class and inspectable
- Option A is acceptable only if we want the fastest possible first slice

Because Pivot is still pre-launch, I slightly prefer Option B.

## Message Rendering Strategy

There is another design choice:

should the user message history display those selected skills as plain text, as
badges, or not at all?

I recommend:

- store the plain text user message separately from mandatory skill selections
- render selected mandatory skill badges in chat history above the user bubble
  if we persist them

This keeps the actual user message semantically clean while still preserving
what the user explicitly chose.

## Security and Correctness

The backend must never trust frontend-provided filesystem paths.

Rules:

- frontend sends only skill names, not file contents, as the authoritative
  transport contract
- backend resolves name -> runtime-visible skill
- backend computes canonical sandbox path
- backend reads the content from the registered storage location
- backend injects that content into prompt

This avoids:

- path traversal
- arbitrary skill spoofing
- mismatched link text vs actual file target

## Edge Cases

### Empty allowlist

If the agent has no visible skills:

- slash menu should not open into an empty picker silently
- show a compact empty state like:
  - `No skills available for this agent`

### Null allowlist

If `skill_ids = null`, the runtime means "all visible skills".

Recommended picker behavior:

- show all visible skills

### Multiple selections

Allowed.

Rules:

- preserve insertion order
- dedupe by name

### Clarify reply flow

If the user is replying to a CLARIFY prompt:

- mandatory skills should still be allowed
- the reply should launch with both:
  - `task_id`
  - `mandatory_skill_names`

This lets the user deliberately steer the assistant with a chosen skill while
answering a clarify step.

### Copy/paste

For the recommended badge-row approach:

- copy/paste remains normal because the textarea still contains only text

For the overlay approach:

- copy/paste semantics become much trickier

### Skill renamed or deleted after draft selection

If the draft holds `sample_skill` but the backend can no longer resolve it at
send time:

- reject the send with a user-facing error
- keep the draft and badge selection intact so the user can recover

## Implementation Plan

### Phase 1

1. Fix `popover` dependency issue so the shared component is usable.
2. Add backend endpoint for runtime-visible skill metadata.
3. Extend launch and context-estimation payloads with
   `mandatory_skill_names`.
4. Add backend mandatory-skill prompt builder.
5. Extend prompt-template rendering for `{{mandatory_skills}}`.
6. Add composer slash picker and selected badge row.
7. Include selected skills in send and context-estimation requests.

### Phase 2

1. Persist selected mandatory skills on `ReactTask`.
2. Show them in chat history.
3. Surface them in runtime debug tooling if useful.

### Phase 3

1. Evaluate whether true inline overlay rendering is worth the complexity.

## Recommended Final Direction

My recommendation is:

- keep user selection structured, not regex-scraped from markdown
- use `/` only as the picker trigger
- render chosen mandatory skills as visible composer badges in a dedicated row
- inject full skill payloads into `{{mandatory_skills}}`
- include `mandatory_skill_names` in both send and context-estimation APIs
- preferably persist the selected skill names on the task for observability

This gives us a robust first implementation without replacing the composer
editor architecture.

## Decisions Needed From You

These are the main points that need your call:

1. Badge rendering mode
   - Recommended: selected skill badges in a dedicated composer row
   - Alternative: visually inline badges through a textarea overlay

2. Transport contract
   - Recommended: add structured `mandatory_skill_names` to the request payload
   - Alternative: rely on backend regex parsing of markdown links from `message`

3. Persistence
   - Recommended: persist selected mandatory skill names on `ReactTask`
   - Faster v1: do not persist, only use them for launch-time prompt injection

4. Null allowlist UX
   - Recommended: if `skill_ids = null`, picker shows all runtime-visible skills
   - Alternative: require explicit allowlist to enable picker

5. History rendering
   - Recommended: show mandatory skill badges in user-message history when
     persisted
   - Alternative: keep history text-only and use mandatory skills only for
     prompt injection

## Confirmed Decisions

The following decisions are now confirmed:

1. Badge rendering mode
   - Use the recommended approach.
   - `/` still triggers the picker, but selected mandatory skills render as
     dedicated composer badges instead of attempting true inline badge rendering
     inside the native textarea.

2. Transport contract
   - Use the recommended structured request shape.
   - Add `mandatory_skill_names` to the task launch and context-estimation
     payloads.
   - Do not rely on backend regex parsing of markdown links inside `message`.

3. Persistence
   - Use the recommended persistent model.
   - Persist selected mandatory skill names on `ReactTask` for observability,
     history rendering, and debugability.

4. Null allowlist UX
   - Use the recommended approach.
   - When `skill_ids = null`, the mention picker shows all runtime-visible
     skills for the current agent/user/runtime.

5. History rendering
   - Approved to render persisted mandatory skills as badges.
