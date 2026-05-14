# File Mention Design (`@` trigger)

## Summary

This document describes the design for a file-reference mention feature in the
chat composer. Users type `@` to search and reference files from the current
session's workspace sandbox, inserting file paths into the message for the
agent to read.

This is distinct from the Skill Mention feature (`/` trigger) documented in
`drafts/mention.md`.

## Motivation

Agents operate on files inside a workspace sandbox. Users often need to
explicitly point the agent at a specific file. Currently they must type the
full path manually, which is error-prone and requires knowing the exact file
structure. A mention-style file picker makes this natural and efficient.

## Design Decisions

### 1. Search via Sandbox Container (not backend filesystem)

**Decision:** File search is executed inside the sandbox container using
ripgrep, not by scanning the backend filesystem directly.

**Why:**

- The system will eventually run on Kubernetes with a distributed filesystem.
  Backend pods cannot assume local access to workspace files.
- The sandbox container is the single source of truth for file access -- it
  always has the workspace correctly mounted at `/workspace`, regardless of
  whether the storage backend is local POSIX, SeaweedFS, or a distributed FS.
- This approach is forward-compatible with any future storage architecture.

**How:** `SandboxService.exec()` → sandbox-manager →
`container.exec_run(cmd, workdir="/workspace")`

### 2. Ripgrep for Search

**Decision:** Use `rg --files` combined with grep filtering, or `rg -l` with
regex patterns, for file search inside the sandbox.

**Why:**

- The sandbox base image (`localhost/pivot-sandbox-base:py311-rg`) already has
  ripgrep installed (note `rg` in the image tag).
- ripgrep parallelizes directory traversal, respects `.gitignore`, and is
  significantly faster than `find` for large codebases.
- Workspaces can contain thousands of files (especially when skills are
  mounted), so performance matters.

### 3. No Database File Index

**Decision:** Do not maintain a database index of workspace files.

**Why:**

- Workspace files are ephemeral and constantly changing during agent execution.
  Keeping an index in sync adds complexity (writes, deletes, migrations)
  without clear benefit.
- ripgrep inside the sandbox is fast enough for real-time interactive search.
- Avoids schema changes, Alembic migrations, and index consistency issues.

### 4. On-Demand Sandbox Creation

**Decision:** Ensure a sandbox exists at search time by calling
`SandboxService.create()` (idempotent) before executing search.

**Why:**

- Sandboxes are created on-demand when agent tools need them. A user might type
  `@` before any tool has been executed, meaning no sandbox exists yet.
- `SandboxService.create()` is idempotent -- calling it when a sandbox already
  exists is a no-op.
- The sandbox-manager already has idle TTL cleanup and LRU eviction for
  resource management.

### 5. Debounced Search

**Decision:** Frontend applies debounce (~300ms) before sending search
requests. Only the latest keyword is sent.

**Why:**

- Each keystroke triggers a sandbox exec call (network round-trip + container
  exec). Debouncing prevents excessive calls.
- The sandbox-manager has configurable timeouts (default 30s), so individual
  calls are bounded.

## Search Flow

```
User types "@" in chat composer
  → Frontend shows empty state or root directory listing
  → User continues typing "@conf"
  → Frontend debounces 300ms, then calls:
      GET /api/sessions/{session_id}/workspace/search?q=conf
  → Backend:
      1. Resolve session → workspace_id → workspace_backend_path
      2. SandboxService.create() (idempotent, ensures container exists)
      3. SandboxService.exec(["rg", "--files", "/workspace", ...])
         or similar ripgrep command
      4. Filter results by keyword, limit to ~20 matches
      5. Return matched file paths
  → Frontend renders filtered list in mention popover
  → User selects a file
  → File path inserted into message text
```

## Edge Cases

### No workspace yet

A brand-new session may not have a workspace until the first task is created.

- Return an empty result list.
- Optionally show a message: "No workspace available yet."

### Sandbox cold start

First `SandboxService.create()` for a session may take a few seconds
(container pull + start).

- Frontend should show a loading state in the mention popover.
- Subsequent searches are fast since the container is already running.

### Workspace with thousands of files

Skills and dependencies can inflate the file count.

- ripgrep handles this efficiently.
- Result limit (~20 matches) keeps response small.
- Consider excluding common noise directories (`.git`, `node_modules`,
  `__pycache__`) from search.

### Multiple mentions

Users may reference multiple files in one message.

- Each `@` trigger is independent.
- No deduplication needed at mention level.

## API Contract (Draft)

### Search workspace files

```
GET /api/sessions/{session_id}/workspace/search?q={keyword}&limit={limit}
```

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `q` | string | `""` | Search keyword / regex fragment |
| `limit` | int | 20 | Maximum results to return |

**Response:**

```json
{
  "files": [
    {
      "path": "src/config.ts",
      "name": "config.ts",
      "kind": "file"
    }
  ]
}
```

### Root directory listing (initial `@` with no keyword)

```
GET /api/sessions/{session_id}/workspace/search?limit=20
```

Returns top-level workspace entries as the initial picker content.

## Relation to Existing Infrastructure

| Component | Role |
|-----------|------|
| `SandboxService` | HTTP client to sandbox-manager, used for `create()` and `exec()` |
| `sandbox-manager` | Manages container lifecycle, exposes `/sandboxes/exec` |
| `WorkspaceService` | Resolves `workspace_id` to `workspace_backend_path` |
| `WorkspaceFileService` | Not used for search (requires local filesystem access) |
| `FileService` | Handles uploaded file attachments, unrelated to workspace search |

## Open Questions

1. **Mention format:** After the user selects a file, how is it represented in
   the message text? Options:
   - Plain path: `@src/config.ts`
   - Markdown link: `[config.ts](src/config.ts)`
   - Structured metadata in request payload (similar to `mandatory_skill_names`)

2. **Agent consumption:** How does the backend communicate the mentioned file
   to the agent? Options:
   - Include the file path in the user prompt template
   - Auto-read the file content and inject into context
   - Let the agent decide whether to read it (just reference the path)

3. **Exclusion patterns:** Should certain directories be excluded from search
   by default (`.git`, `node_modules`, `__pycache__`, `skills/`)?

4. **Directory navigation:** Should the picker support browsing into
   subdirectories, or only flat search results?
