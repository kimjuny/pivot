# Pivot Filesystem Implementation Design

## Summary

This document turns the higher-level plan in
[drafts/filesystem.md](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/drafts/filesystem.md)
into an implementation-oriented design for the first route-B rollout.

The most important change is architectural, not cosmetic:

- stop designing around host-mounted workspace paths
- start designing around runtime-mounted workspace identities

In practical terms, the first serious implementation target is:

- `podman compose up` starts the local stack
- `sandbox-manager` receives workspace identity, not host path
- each sandbox mounts JuiceFS inside its own runtime environment
- the agent still sees `/workspace`

## Scope of This Phase

Included:

- keep `WorkspaceStorageService` and `logical_path`
- redesign backend-to-sandbox-manager contract around workspace identity
- package JuiceFS runtime dependencies into container images
- add RustFS to local compose
- mount JuiceFS inside sandbox containers
- keep `/workspace` unchanged for the agent

Excluded:

- public `detached_clone` API
- uploads migration
- task attachment migration
- extension artifact migration
- Kubernetes manifests

## Implementation Principles

- `podman compose up` should remain the main local developer entrypoint
- no required host-side helper scripts in the default path
- backend should not need host-path knowledge
- sandbox-manager should own runtime attach behavior
- service-layer persistence should remain in backend services
- filesystem-specific logic should stay concentrated in a small number of
  modules

## Target Local Runtime Topology

```text
backend
    |
    | workspace identity + mount contract
    v
sandbox-manager
    |
    | create sandbox with FUSE capability + shared metadata volume
    v
sandbox container
    |
    | juicefs mount inside container
    v
/workspace

RustFS service <---- JuiceFS object backend
shared named volume <---- SQLite metadata file
```

## Why This Topology Is Better

It eliminates the biggest DX and portability problems from the earlier plan:

- no required host mount scripts
- no assumption that the host can or should browse the workspace filesystem
- no need to reverse-discover host paths from backend container mounts
- much better path to Windows/macOS contributors because the mount logic lives
  in the Linux container runtime

## Local Compose Design

The default development stack should gain:

- `rustfs` service
- one named volume for JuiceFS metadata, for example `pivot-juicefs-meta`
- environment variables for JuiceFS object credentials and metadata URL

Conceptual compose shape:

```yaml
services:
  rustfs:
    image: <rustfs-image>
    ports:
      - "9000:9000"

  backend:
    environment:
      - WORKSPACE_STORAGE_BACKEND=local_fs or juicefs
      - SANDBOX_MANAGER_URL=http://sandbox-manager:8051

  sandbox-manager:
    environment:
      - PIVOT_JFS_META_URL=sqlite3:///var/lib/pivot/juicefs-meta/pivot-workspaces.db
      - PIVOT_JFS_BUCKET=http://rustfs:9000/pivot-juicefs
      - PIVOT_JFS_ACCESS_KEY=...
      - PIVOT_JFS_SECRET_KEY=...
    volumes:
      - pivot-juicefs-meta:/var/lib/pivot/juicefs-meta
```

Important difference from the earlier design:

- backend no longer needs `/app/server/workspace` to be backed by a host JuiceFS
  mount
- sandbox-manager and sandbox runtime own JuiceFS lifecycle

## Image Changes

### Sandbox image

The sandbox runtime image should include:

- `juicefs` CLI
- FUSE userspace tooling
- any required mount helpers

Why:

- each sandbox should be able to mount JuiceFS directly
- this avoids cross-container mount propagation problems

### Sandbox-manager image

The sandbox-manager image should include:

- `juicefs` CLI, if manager performs filesystem bootstrap or health checks
- access to the shared metadata volume

The backend image does **not** need JuiceFS tooling for the core runtime path.

## Backend-to-Manager Contract

The current API is too path-oriented. It should move toward an explicit
workspace mount contract.

Recommended payload shape:

```text
workspace_id
storage_backend
logical_path
mount_mode
source_workspace_id (later)
```

What should disappear from the long-term contract:

- backend-visible concrete mount path as the primary identity
- assumptions that sandbox-manager can derive everything from bind-mounted
  backend paths

## New Sandbox-Manager Responsibilities

Sandbox-manager should gain a runtime-focused abstraction, conceptually:

```python
class WorkspaceRuntimeDriver:
    def ensure_filesystem_ready(...) -> None: ...
    def ensure_workspace_materialized(...) -> None: ...
    def attach_workspace(...) -> None: ...
```

### `ensure_filesystem_ready`

Responsibilities:

- verify RustFS is reachable
- verify JuiceFS metadata location is accessible
- perform idempotent `juicefs format` for local development if the filesystem
  is not initialized yet

For local dev, this step should happen inside containerized runtime context, not
on the host.

### `ensure_workspace_materialized`

Responsibilities:

- ensure the target logical path exists
- later, provision detached clone targets

### `attach_workspace`

Responsibilities:

- mount JuiceFS inside the sandbox
- expose the requested logical path as `/workspace`
- make the final sandbox view look native to the agent

## How a Sandbox Should Start in JuiceFS Mode

Recommended runtime sequence:

1. backend requests sandbox for a workspace
2. sandbox-manager receives workspace identity and mount mode
3. sandbox-manager ensures filesystem bootstrap is complete
4. sandbox-manager creates sandbox with:
   - FUSE capability
   - access to the shared metadata volume
   - JuiceFS credentials
   - network access to `rustfs`
5. sandbox bootstrap mounts JuiceFS inside the sandbox
6. sandbox bootstrap exposes `logical_path` at `/workspace`
7. agent command runs with working directory `/workspace`

This preserves the product contract while removing host-path coupling.

## How `/workspace` Should Be Exposed

Recommended final target:

- bind mount the logical subdirectory to `/workspace` from inside the sandbox

Why this is better than a symlink:

- more native path behavior
- fewer surprises for tools that inspect working directories
- closer to the existing mental model

Allowed temporary fallback during bring-up:

- symlink `/workspace -> /var/lib/pivotfs/<logical_path>`

But the steady-state target should be a bind mount.

## Local Metadata Strategy

Recommended first attempt:

- shared named volume
- SQLite file on that volume
- same metadata URL visible to sandbox-manager and sandbox containers

Example:

```text
sqlite3:///var/lib/pivot/juicefs-meta/pivot-workspaces.db
```

Risk to validate:

- concurrent access across multiple sandbox containers

Fallback if needed:

- keep the exact same architecture, but swap local metadata to a small
  containerized PostgreSQL service

## Local Object Storage Strategy

Recommended first attempt:

- `rustfs` in `compose.yaml`
- bucket name `pivot-juicefs`
- path-style S3 access

Fallback:

- `SeaweedFS` S3 gateway

This fallback should not require changing backend storage abstractions.

## Backend Service Changes

### `WorkspaceStorageService`

Keep and continue evolving this service.

It should own:

- logical path generation
- canonical workspace provisioning
- detached-clone provisioning later

It should no longer be framed around:

- host mount sentinel files
- host-path readiness checks as the main architecture

### `WorkspaceService`

Keep:

- CRUD over workspace rows
- scope validation
- ownership rules

Delegate:

- logical path generation
- storage backend provisioning

### `SessionService` and `ProjectService`

No product behavior change for callers, but their provisioning path should flow
through `WorkspaceStorageService`.

## Sandbox-Manager Refactor Plan

### Step 1. Introduce explicit mount contract

- backend sends workspace identity, not just path
- sandbox-manager request/response models are updated first

### Step 2. Add runtime driver abstraction

- encapsulate `local_fs` and `juicefs` attach logic behind one driver interface
- keep the old local bind path as one implementation during migration

### Step 3. Add JuiceFS runtime mode

- add bootstrap code for filesystem readiness
- add sandbox bootstrap code for in-container mount

### Step 4. Retire reverse-discovered host path as the preferred path

- keep compatibility only as long as needed for `local_fs`
- do not extend it further for JuiceFS

## Local Developer Experience

The intended DX after this rollout is:

```bash
podman compose up
```

Optional toggles may still exist, but the default path should not require:

- host shell helper scripts
- host FUSE setup steps beyond what Podman/runtime already needs
- manual mount commands

If special setup is still required for JuiceFS mode after implementation, that
should be treated as a bug in the developer experience, not as an acceptable
steady state.

## Failure Handling

The runtime should fail loudly when:

- RustFS is unreachable
- JuiceFS filesystem bootstrap fails
- metadata storage is inaccessible
- sandbox mount fails
- `/workspace` cannot be materialized

The failure should happen at sandbox preparation time, not after the agent is
already running.

## Smoke Test Checklist

### Storage/runtime validation

- `podman compose up` starts the stack without host helper scripts
- first sandbox can trigger idempotent filesystem bootstrap
- later sandboxes reuse the same filesystem without reformatting
- create, overwrite, rename, and delete files in `/workspace`
- clone a real git repo
- run git status and branch operations
- verify `AGENTS.md` discovery still works
- recreate a sandbox and verify persistence

### Concurrency validation

- two sandboxes mount different logical paths at the same time
- two sandboxes mount the same logical path in `live_sync`
- metadata locking behaves correctly under local SQLite

### Failure-path validation

- RustFS unavailable
- metadata volume missing
- invalid credentials
- JuiceFS mount command failure

## Suggested Patch Breakdown

Recommended patch order:

1. update design docs to route B
2. keep `logical_path` and storage abstraction changes
3. add manager-side request model changes for workspace identity
4. add runtime driver abstraction in sandbox-manager
5. package JuiceFS tooling into sandbox runtime image
6. add RustFS and metadata volume to compose
7. implement in-sandbox JuiceFS mount path
8. end-to-end validation

## What To Do With Helper Scripts

The old host helper scripts should not be treated as the primary design.

Recommended stance:

- remove them from the main plan
- keep them only as an optional experiment if they help temporary debugging
- do not make them the normal contributor workflow

## Points That Still Need Your Call

These are the two decisions that still matter architecturally.

### 1. Local SQLite fallback policy

Recommendation:

- implement local JuiceFS mode with SQLite metadata first
- if concurrency behavior is poor, switch local JuiceFS mode to PostgreSQL

What I need from you:

- are you okay with SQLite being a best-effort local default rather than a hard
  forever decision?

### 2. Rollout default

Recommendation:

- keep `local_fs` as the default backend until route-B JuiceFS mode passes smoke
  tests
- then make JuiceFS the local default

What I need from you:

- do you want the safer staged rollout, or should we target "JuiceFS by
  default" immediately once the new runtime path lands?

## Final Recommendation

The clean implementation direction is:

- backend owns workspace identity
- sandbox-manager owns workspace attach
- JuiceFS mounts happen inside runtime containers
- local DX stays `podman compose up`
- host-path reverse discovery stops being the long-term architecture
