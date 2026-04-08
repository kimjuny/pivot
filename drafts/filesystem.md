# Pivot Filesystem Plan

## Summary

Pivot should adopt `JuiceFS` as the long-term workspace filesystem, but the
integration strategy should change from the earlier "host mount compatibility"
approach to a cleaner runtime-native model:

- `JuiceFS` remains the workspace filesystem.
- local metadata stays `SQLite` first, with `PostgreSQL` as the shared/prod
  target.
- local object storage stays `RustFS` first, with `SeaweedFS` S3 gateway as
  the main fallback.
- `Redis` stays out unless later benchmarks justify it.
- the sandbox runtime should mount workspaces by workspace identity, not by
  reverse-discovered host path.

The key architectural decision is:

- do **not** make host-visible filesystem paths the long-term source of truth
- do **not** require host-side helper scripts as the default developer path
- do make `podman compose up` the primary local-development experience

## Why We Are Changing Direction

The earlier compatibility-first plan assumed:

- backend exposes `/app/server/workspace/...`
- sandbox-manager reverse-discovers the corresponding host path
- sandbox-manager bind mounts that host path into sandbox `/workspace`

That shape can work, but it creates three problems:

- local setup becomes dependent on host-side mount scripts
- Windows and other non-Linux contributors get a much worse experience
- Pivot stays conceptually tied to "workspace == host path", which is not the
  right long-term abstraction for shared filesystems or Kubernetes

The better model is:

- `workspace == storage identity + mount contract`
- sandbox-manager is responsible for attaching that workspace into the sandbox
- the agent still sees a native `/workspace`

This keeps the product model unchanged for the agent while making the runtime
architecture much cleaner.

## Core Principles

- preserve the agent-facing `/workspace` path
- keep filesystem semantics POSIX-like for arbitrary bash usage
- make `podman compose up` the default local path
- isolate persistence access behind service-layer abstractions
- separate workspace identity from physical mount implementation
- keep room for both `live_sync` and `detached_clone`
- keep the path open to Kubernetes-native mounting later

## Non-Goals

- do not migrate uploads, task attachments, or extension artifacts in the first
  filesystem rollout
- do not require host-side browsing of the workspace filesystem
- do not make contributors install and run host helper scripts as the default
  path
- do not fully redesign production orchestration in the same patch series

## Current Pivot State

Pivot already has the right product-level model:

- `session_private` workspaces
- `project_shared` workspaces
- one mounted `/workspace` per sandbox
- repo-local guidance such as `/workspace/AGENTS.md`

Relevant code paths today:

- `server/app/services/workspace_service.py`
- `server/app/services/session_service.py`
- `server/app/services/project_service.py`
- `server/sandbox_manager/main.py`
- `server/app/services/workspace_guidance_service.py`

So the product contract does not need to change. What must change is the
runtime contract between backend and sandbox-manager.

## Recommended Architecture

### Storage Layers

Pivot should explicitly separate four concerns.

### 1. Workspace filesystem

Used for:

- session workspaces
- project workspaces
- repo contents
- generated files
- workspace-root guidance files

Recommended backend:

- `JuiceFS`

### 2. Workspace metadata engine

Used by JuiceFS for directory entries, inode metadata, clone metadata, and file
structure.

Recommended backends:

- local development: `SQLite`
- shared/prod: `PostgreSQL`

### 3. Workspace object data

Used by JuiceFS for file data blocks.

Recommended backends:

- local development: `RustFS`
- fallback local backend: `SeaweedFS` S3 gateway
- shared/prod: validated S3-compatible object storage

### 4. Non-workspace persisted blobs

Used for:

- extension artifacts
- uploaded files
- task attachment snapshots

These should move later behind explicit blob/object services, but they should
not block the workspace rollout.

## The New Runtime Model

The core architectural move is:

- backend stores workspace records and logical identity
- backend no longer treats a host path as the authoritative workspace handle
- sandbox-manager receives an explicit workspace mount contract
- sandbox-manager materializes and attaches the workspace into the sandbox

### Workspace identity

Each workspace should be identified by stable storage-level fields such as:

- `workspace_id`
- `scope`
- `logical_path`
- `mount_mode`
- `source_workspace_id` for detached clones later

Example logical path:

```text
pivot/workspaces/users/alice/agents/7/projects/project-1
```

### Workspace mount contract

When backend asks sandbox-manager to prepare a sandbox, it should pass a mount
contract conceptually shaped like:

```text
workspace_id=...
storage_backend=juicefs
logical_path=pivot/workspaces/users/alice/agents/7/projects/project-1
mount_mode=live_sync
```

The important point is that sandbox-manager should receive a storage identity,
not a reverse-engineered host path.

## Local Development Topology

The recommended local-development topology for the new model is:

```text
RustFS service
    ^
    |
JuiceFS clients inside sandbox containers
    ^
    |
shared SQLite metadata volume
    ^
    |
sandbox-manager orchestrates mount + attach
    ^
    |
backend sends workspace identity
```

Properties of this design:

- `podman compose up` remains the normal developer entrypoint
- no default host helper scripts are required
- the host does not need to browse the filesystem directly
- the real workspace mount happens inside the Linux container runtime where the
  agent already runs

This is a much better fit for Windows, macOS, and Linux contributors because
the important filesystem behavior now lives inside the containerized runtime,
not in the host shell environment.

## Shared / Production Topology

Recommended future shared topology:

```text
S3-compatible object storage
    ^
    |
JuiceFS client on each runtime worker
    ^
    |
PostgreSQL metadata
    ^
    |
runtime mounts workspace into each sandbox
```

In Kubernetes, the exact implementation may later become:

- CSI-mounted shared filesystem on runtime workers
- a runtime-side mount helper container
- or direct mount inside the sandbox pod/container

The important design choice now is not to hard-code "workspace == host path".

## Recommended JuiceFS Layout

Use one JuiceFS filesystem per Pivot environment.

Recommended filesystem name:

- `pivot-workspaces`

Recommended namespace layout:

```text
/pivot
  /workspaces
    /users
      /<username>
        /agents
          /<agent_id>
            /sessions
              /<session_id>
            /projects
              /<project_id>
  /scratch
    /clones
    /repair
```

Rationale:

- one filesystem is easier to operate
- workspaces stay as ordinary subdirectories
- clone and repair workflows remain inside one namespace
- the path shape maps cleanly onto existing Pivot concepts

## Workspace Modes

`scope` and mount behavior should remain separate.

Current scope:

- `session_private`
- `project_shared`

Mount behavior:

- `live_sync`
- `detached_clone`

### live_sync

The sandbox mounts the canonical workspace path.

Behavior:

- writes persist back to the canonical workspace
- best fit for normal project workspaces
- also valid for ordinary session workspaces

### detached_clone

The sandbox mounts a clone derived from another workspace path.

Behavior:

- writes do not affect the source workspace
- good for risky experiments, previews, and isolated task runs

Recommended first rollout:

- keep public behavior simple
- `project_shared` defaults to `live_sync`
- `session_private` stays `live_sync` on its own canonical path for now
- build detached-clone plumbing internally, but do not expose it yet

## Metadata Strategy

### Local development: SQLite

Recommended metadata URL shape:

```text
sqlite3:///var/lib/pivot/juicefs-meta/pivot-workspaces.db
```

Why this still works in the new design:

- the SQLite file is not on the host
- it lives on a container-managed named volume shared with sandbox-manager and
  sandbox containers
- local contributors still do not need to operate another database

Important constraint:

- SQLite in this model must be validated under multiple sandbox containers
  accessing the same metadata file through the same local volume

If this proves flaky under real concurrency, local development should switch to
containerized PostgreSQL without changing the higher-level design.

### Shared / production: PostgreSQL

Recommended URL shape:

```text
postgres://<user>:<password>@<host>:5432/pivot_juicefs
```

Rules:

- use a dedicated database such as `pivot_juicefs`
- do not reuse the Pivot application schema
- only use schema separation if a dedicated database is impossible

## Object Storage Strategy

### Local development: RustFS

Recommended local bucket:

```text
http://rustfs:9000/pivot-juicefs
```

Why RustFS remains a good local candidate:

- lightweight
- S3-compatible goal
- fits naturally into `podman compose up`

### Compatibility stance

RustFS should still be treated as "validated by smoke tests", not as an
assumption.

Required validation:

- `juicefs format`
- `juicefs mount`
- large file write/read
- many small files
- rename-heavy repo workflows
- `juicefs fsck`
- `juicefs gc`
- disposable `juicefs destroy`

Fallback order if RustFS proves incompatible:

1. `SeaweedFS` S3 gateway
2. shared cloud S3-compatible object storage

`MinIO` is intentionally not the preferred fallback anymore.

## Pivot Data Placement

### v1: move canonical workspaces only

Move into JuiceFS first:

- session workspaces
- project workspaces
- repo-local guidance files
- repo clones
- agent-generated workspace files

Keep out of scope for v1:

- extension artifacts and runtime cache
- uploads
- task attachment snapshots
- user tools and skills that are not yet tied to workspace lifecycle

## Required Model Changes

Recommended workspace model direction:

- keep `scope`
- add `logical_path`
- add `mount_mode`
- plan for `source_workspace_id`
- plan for `materialization_status`

Recommended first implementation:

- persist `logical_path` now
- keep `mount_mode` internal or defaulted at first
- defer broader schema expansion until the runtime attach flow lands

## Required Service Changes

### 1. Keep `WorkspaceStorageService`

This service remains the right place for:

- canonical logical path generation
- workspace provisioning
- future detached clone provisioning
- storage backend policy

But it should stop being modeled around "host path resolution" as the core
primitive.

### 2. Introduce a runtime attach abstraction

Pivot needs a new runtime-side abstraction, conceptually something like:

```text
WorkspaceRuntimeDriver
```

Responsibilities:

- ensure the backing JuiceFS filesystem is initialized
- ensure the target logical path exists
- mount the filesystem in the sandbox runtime
- expose the requested logical subdirectory as `/workspace`

This should live on the sandbox-manager side, not in the backend service layer.

### 3. Change backend-to-manager communication

Instead of sending a backend-visible path, backend should eventually send:

- workspace identity
- storage backend
- logical path
- mount mode

This is the critical architectural seam.

### 4. Stop treating `server/workspace` as conceptual truth

`server/workspace` may remain as a local legacy path for `local_fs`, but it
should not define the long-term filesystem architecture.

## Sandbox Runtime Design

Recommended runtime behavior for JuiceFS-backed sandboxes:

1. sandbox-manager creates sandbox with FUSE capability available
2. sandbox-manager passes JuiceFS credentials + metadata location into sandbox
3. sandbox bootstrap mounts the JuiceFS filesystem inside the sandbox
4. sandbox bootstrap exposes the requested logical path at `/workspace`
5. agent runs exactly as if `/workspace` were a normal native directory

This can be implemented with either:

- an in-sandbox bind mount from the mounted filesystem to `/workspace`
- or a symlink as an interim step

Recommendation:

- target a bind mount for the final runtime behavior
- allow a symlink-based fallback only if needed during bring-up

## Rollout Strategy

### Phase 1. Storage identity and abstraction

- keep the new `logical_path` work
- keep `WorkspaceStorageService`
- stop deepening direct `server/workspace` assumptions

### Phase 2. Runtime attach contract

- change backend-to-sandbox-manager API to send workspace identity instead of
  path
- add runtime-side attach abstraction

### Phase 3. Containerized local JuiceFS runtime

- package JuiceFS tooling into runtime images
- add RustFS to `compose.yaml`
- store local SQLite metadata on a named volume
- mount JuiceFS inside sandbox containers

### Phase 4. End-to-end validation

- create session workspace
- create project workspace
- run sandbox commands
- verify `/workspace/AGENTS.md` still works
- verify file persistence across sandbox recreation

### Phase 5. Detached clone

- add clone provisioning
- expose detached mode later when runtime behavior is stable

## What We Should Not Do

- do not make host-mounted helper scripts the default DX
- do not require host-side browsing of JuiceFS
- do not keep sandbox-manager permanently coupled to backend bind mounts
- do not mix workspace migration with every blob-storage migration

## Points That Still Need Your Call

I recommend the following, but they are real architecture decisions rather than
implementation trivia:

### 1. Local metadata engine fallback

Recommendation:

- start with `SQLite` on a shared named volume
- if concurrency tests look noisy, switch local JuiceFS mode to
  containerized `PostgreSQL`

What I need from you:

- are you comfortable treating local `SQLite` as the first attempt rather than
  a guaranteed permanent choice?

### 2. Local default during rollout

Recommendation:

- keep `local_fs` as the default backend until the containerized JuiceFS path
  is smoke-tested
- then promote JuiceFS to the default local workspace backend

What I need from you:

- do you want a safer staged rollout, or do you want local development to jump
  straight to JuiceFS once the runtime path is implemented?

## Final Recommendation

The cleaner long-term Pivot architecture is:

- `JuiceFS` for workspace storage
- `SQLite` local first, `PostgreSQL` shared/prod
- `RustFS` local first, `SeaweedFS` fallback
- backend owns workspace identity
- sandbox-manager owns runtime attach
- sandbox sees only a native `/workspace`
- no default host helper scripts
- no long-term dependence on host-path reverse discovery
