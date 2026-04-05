# Projects And Workspace Routing

## Problem

The current workspace model binds one sandbox container and one mounted
workspace directory to a `(user, agent)` pair:

- Host workspace: `server/workspace/{username}/agents/{agent_id}/`
- Sandbox container identity: `pivot-sandbox-{username}-{agent_id}`
- Sandbox mount target: `/workspace`

This model is simple, but it creates a real contamination problem:

- One session can mutate the shared environment with `apt-get`, package
  installs, shell scripts, or broad file edits.
- Later sessions for the same agent inherit that mutated environment whether
  they want it or not.
- Session history is isolated in the database, but filesystem state is not.

That mismatch is now a product issue, not just an implementation detail.

## Decision Summary

Adopt a hybrid model:

- Default: every session gets a private workspace and a private sandbox.
- Project mode: multiple sessions can be attached to one project, and all
  sessions inside that project share one workspace and one sandbox.

This keeps the default behavior safe and intuitive while still supporting
long-running, multi-session project work.

## Proposed Directory Layout

The proposed host paths are good and should stay human-readable:

- Standalone session workspace:
  `server/workspace/{username}/agents/{agent_id}/sessions/{session_id}/`
- Project workspace:
  `server/workspace/{username}/agents/{agent_id}/projects/{project_id}/`

I agree with this layout.

### Important refinement

These paths should be treated as storage layout only, not as the primary
identity used across the backend.

Internally, the system should introduce a first-class `workspace_id` and route
all sandbox, attachment, and filesystem operations through it.

Why this matters:

- A project may later be cloned or forked without changing its semantic role.
- A session may need workspace reset, replacement, or migration.
- Container names should not depend on path conventions.
- Delete and archive flows become much easier when `workspace` is its own
  resource.

## Recommended Domain Model

### Workspace

Add a dedicated workspace entity.

Suggested fields:

| Field | Type | Notes |
|-------|------|-------|
| `workspace_id` | str (UUID) | Primary identifier |
| `user` | str | Workspace owner |
| `agent_id` | int | Owning agent |
| `scope` | str | `session_private` or `project_shared` |
| `session_id` | str or None | Present for private session workspaces |
| `project_id` | str or None | Present for shared project workspaces |
| `status` | str | `active`, `archived`, `deleting`, `broken` |
| `created_at` | datetime | Auditability |
| `updated_at` | datetime | Activity sorting |

Invariants:

- A `session_private` workspace must have `session_id` and no `project_id`.
- A `project_shared` workspace must have `project_id` and no `session_id`.
- A session always belongs to exactly one workspace.

### Project

Add a project entity owned by one `(user, agent)` pair.

Suggested fields:

| Field | Type | Notes |
|-------|------|-------|
| `project_id` | str (UUID) | Primary identifier |
| `agent_id` | int | Owning agent |
| `user` | str | Owner |
| `name` | str | Required display name |
| `description` | str or None | Optional |
| `workspace_id` | str | Shared workspace backing the project |
| `archived_at` | datetime or None | Soft-delete path |
| `created_at` | datetime | Auditability |
| `updated_at` | datetime | Sorting |

### Session

Extend session ownership semantics:

| Field | Type | Notes |
|-------|------|-------|
| `project_id` | str or None | Null for standalone sessions |
| `workspace_id` | str | Always required |

Rules:

- A standalone session gets its own new private workspace.
- A project session reuses the project's shared workspace.
- If `project_id` is present, `session.workspace_id` must equal the linked
  `project.workspace_id`.

## Workspace And Sandbox Routing

### Host storage

Keep the host directory layout readable:

- `server/workspace/{username}/agents/{agent_id}/sessions/{session_id}/`
- `server/workspace/{username}/agents/{agent_id}/projects/{project_id}/`

### Sandbox identity

Do not keep sandbox identity keyed by `agent_id`.

Instead, route sandbox lifecycle by `workspace_id`.

Recommended container naming:

- `pivot-sandbox-{username}-{workspace_id}`

Recommended backend resolution flow:

1. Resolve `workspace_id` from the current session or project.
2. Load the workspace record.
3. Resolve the actual host path for that workspace.
4. Ensure or reuse the sandbox bound to that workspace.

This is the key architectural change that actually fixes contamination.

If the container is still keyed by `(user, agent)`, then session-private
directories alone do not solve the environment pollution problem.

## User Experience Model

The mental model should be:

- `Session`: one conversation thread
- `Workspace`: one filesystem + sandbox environment
- `Project`: one named shared workspace that can host many sessions

This is much easier to explain than overloading `session` to mean both
conversation history and runtime environment.

## Sidebar And Main Chat UX

Your proposed sidebar direction is solid, with a few refinements.

### Sidebar layout

In `SessionSidebar.tsx`, show two top-level groups:

- `Projects`
- `Sessions`

Recommended behavior:

- `Projects` lists all projects for the current agent.
- Expanding a project reveals its sessions.
- `Sessions` lists standalone sessions only.
- Standalone sessions and project sessions should not be mixed into one flat
  list.

This separation is important because they have different workspace semantics.

### Project interactions

Projects should support:

- Create
- Rename
- Archive or delete
- Open project overview
- Create new session inside project
- Open an existing project session

### Clicking a project

I do not recommend making project click jump directly into an unnamed new
session without any context.

A better behavior:

- Clicking a project opens a project landing state in the main panel.
- That state shows project name, recent sessions, workspace status, and a clear
  `New Session` action.

Why:

- It avoids silently creating low-value sessions.
- It gives users a stable place to understand what this shared workspace is.
- It gives us room for workspace actions such as reset, archive, or health
  inspection.

### New session flows

There should be three explicit creation flows:

1. `New Session`
   Creates a standalone session with a private workspace.
2. `New Project`
   Creates a project and its shared workspace.
3. `New Session In Project`
   Creates a session linked to that project's workspace.

This is much clearer than trying to infer intent from sidebar selection alone.

## Additional Features I Strongly Recommend

### 1. Workspace reset

This is the most important companion feature.

Each workspace should support a reset action:

- Standalone session workspace reset
- Project workspace reset

Reset semantics for the first version can be simple:

- Destroy the existing sandbox container
- Recreate the workspace directory if needed
- Start a fresh sandbox from the base image

For project workspaces, show a stronger warning because reset impacts multiple
sessions.

### 2. Archive before delete

Projects should prefer `Archive` over hard delete in the first version.

Why:

- A project owns a shared workspace and many session references.
- Hard delete is operationally risky.
- Archive gives safer UX while keeping cleanup simple later.

Standalone sessions can still support direct delete if desired.

### 3. Workspace scope badge

In the chat header and session metadata, show whether the current session is:

- `Private Workspace`
- `Project Workspace`

This small cue helps users understand why a session sees prior files.

### 4. Concurrency guardrails

Shared project workspaces introduce write-race risks.

For the first version, I recommend one of these simple rules:

- Only allow one active running task per workspace at a time, or
- Allow concurrency but show a warning when another session is currently
  operating in the same workspace

I recommend the first option for v1 because it is easier to reason about.

### 5. Workspace status and repair

Projects and sessions should expose minimal workspace health information:

- Sandbox running or stopped
- Last active time
- Last task failure related to sandbox or tool execution

If the sandbox is broken, users should see a visible `Repair Workspace` or
`Reset Workspace` action rather than vague task failures.

### 6. Session move semantics

Do not support moving an existing standalone session into a project in the
first version.

Likewise, do not support detaching a project session into a private workspace
in v1.

These moves raise confusing questions:

- Does the old conversation now refer to a different filesystem history?
- Should files be copied?
- Should the old workspace be preserved?

For v1, keep creation-time binding immutable.

### 7. Project landing page details

When a project is opened, the main panel should show:

- Project name and optional description
- Recent sessions
- Create new project session action
- Workspace status
- Optional path hint or repository summary in the future

This is a better default than immediately dropping the user into an empty chat.

## Data Ownership Boundaries

Not everything should become workspace-scoped.

### Keep user-scoped

These existing directories should stay user-level unless a stronger reason
appears later:

- `server/workspace/{username}/files/`
- `server/workspace/{username}/tools/`
- `server/workspace/{username}/skills/`
- `server/workspace/{username}/skill_change_submissions/`

Why:

- These are more like user assets or libraries than runtime workspace state.
- Making them workspace-scoped would create duplication and management overhead.

### Make workspace-scoped

These should resolve through `workspace_id`:

- The mounted `/workspace` directory
- Sandbox container lifecycle
- File-path resolution for task output attachments

Task attachments can remain task-scoped snapshots, but the source path lookup
should resolve from the owning workspace, not from `agent_id` alone.

## API And Service Surface

The backend should grow explicit project and workspace services rather than
spreading filesystem logic across controllers.

### Service responsibilities

- `workspace_service`
  CRUD and path resolution for workspaces
- `project_service`
  CRUD for projects
- `session_service`
  Session creation and listing with project/workspace binding
- `sandbox_service`
  Container lifecycle keyed by `workspace_id`

This keeps persistent-state access in the service layer, which matches the
existing project rule.

### Minimal API changes

Suggested additions:

- `POST /projects`
- `GET /projects?agent_id=...`
- `PATCH /projects/{project_id}`
- `DELETE /projects/{project_id}` or archive endpoint
- `POST /sessions` with optional `project_id`
- Session list responses should include `project_id`, `workspace_id`, and
  `workspace_scope`

## Recommended Sidebar Data Shape

The frontend will be easier to build if the API already returns grouped
concepts instead of forcing the client to infer everything.

Suggested response shape:

```json
{
  "projects": [
    {
      "project_id": "uuid",
      "name": "Website Redesign",
      "workspace_id": "uuid",
      "workspace_status": "active",
      "updated_at": "2026-04-04T10:00:00Z",
      "sessions": [
        {
          "session_id": "uuid",
          "title": "Refactor landing hero",
          "runtime_status": "idle",
          "updated_at": "2026-04-04T10:05:00Z"
        }
      ]
    }
  ],
  "standalone_sessions": [
    {
      "session_id": "uuid",
      "title": "Quick curl debugging",
      "workspace_id": "uuid",
      "workspace_scope": "session_private",
      "runtime_status": "idle",
      "updated_at": "2026-04-04T09:00:00Z"
    }
  ]
}
```

This keeps the sidebar rendering direct and avoids fragile client grouping.

## Migration Strategy

This change is large enough that migration needs an explicit plan.

### Existing reality

Today, one `(user, agent)` pair effectively owns one workspace. Existing
sessions implicitly share it.

### Recommended migration for the first rollout

Treat the current shared agent workspace as legacy and avoid trying to
perfectly preserve it for all old sessions.

Recommended practical strategy:

1. Add the new tables and fields.
2. New sessions use the new workspace model immediately.
3. Existing sessions can either:
   - remain legacy sessions that still resolve through the old agent workspace,
     or
   - be migrated into one auto-created legacy project per `(user, agent)`.

I recommend the second option if you want a cleaner long-term model:

- Create a generated project such as `Imported Workspace`.
- Bind old sessions to that project and shared workspace.
- New standalone sessions then start clean.

This keeps old user work accessible without making the new architecture depend
on indefinite legacy branching.

## Points I Would Not Ship In V1

To keep this manageable, I would explicitly defer:

- Moving sessions between private and project workspaces
- Forking projects
- Branching workspaces
- Per-project uploaded file libraries
- Cross-agent shared projects
- Multi-user collaborative projects

These can come later once the core workspace boundary is solid.

## Final Recommendation

I agree with the two concrete path rules you proposed:

- Private session workspace:
  `server/workspace/{username}/agents/{agent_id}/sessions/{session_id}/`
- Project shared workspace:
  `server/workspace/{username}/agents/{agent_id}/projects/{project_id}/`

I also agree with adding a `Projects` region above `Sessions` in the sidebar.

The two changes I would insist on before implementation are:

1. Introduce a first-class `workspace_id` resource in the backend instead of
   treating directory paths as identity.
2. Add workspace lifecycle UX from day one:
   archive, reset, status, and basic concurrency guardrails.

If we do only the directory split without those two pieces, we will reduce some
confusion but we will not fully solve the environment contamination problem.
