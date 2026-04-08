# Pivot Filesystem Implementation Design: SeaweedFS Route

## Summary

This document turns
[drafts/filesystem_seaweedfs.md](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/drafts/filesystem_seaweedfs.md)
into an implementation-oriented plan.

The architectural goal is:

- backend stores workspace identity, not host path
- sandbox-manager owns trusted workspace attach
- SeaweedFS provides shared live-sync workspace storage
- `/workspace/.uploads` remains part of the same live workspace surface
- `/workspace/skills` remains a sandbox-local detached draft surface
- sandbox containers do not mount the shared filesystem themselves

This route is intentionally different from both:

- the current `local_fs` host-bind design
- the earlier `JuiceFS + RustFS + metadata DB` design

## Scope of This Phase

Included:

- add workspace storage identity fields to the database schema
- introduce `WorkspaceStorageService`
- redesign backend-to-sandbox-manager around mount contracts
- add SeaweedFS to local compose
- let sandbox-manager prepare shared SeaweedFS runtime attach
- preserve `/workspace` for agents
- change skills runtime from direct bind-mounted canonical paths to
  materialized sandbox-local drafts
- remove builtin-skill-specific schema and service logic

Excluded:

- generalized detached clone for whole workspaces
- Kubernetes manifests

## Implementation Principles

- local development should converge on the same shared-mount-root workspace
  model as production
- backend should not depend on host-mounted workspace directories
- filesystem-specific behavior should be concentrated in a few modules
- sandboxes stay low-privilege
- temporary migration code is acceptable only when it is short-lived and well
  isolated

## Current State

Today the codebase already moved most business logic onto the new filesystem
contract:

- `Workspace` rows carry `storage_backend`, `logical_path`, `mount_mode`, and
  `source_workspace_id`
- backend sends workspace mount specs instead of `workspace_backend_path`
- workspace guidance and task attachments read through sandbox/runtime helpers
- runtime skills are materialized as detached drafts instead of bind-mounted
  canonical directories

What is still transitional:

- local development now requires a real `shared_mount_root` native mount, but
  the startup/bootstrap steps are not yet documented
- `SeaweedfsWorkspaceDriver` still keeps a helper-side filer bridge as a backup
  implementation path, even though local default no longer tolerates that
  fallback
- platform-specific startup instructions for macOS/Windows/Linux are still
  pending

## Current Local Completion

The local-development implementation has completed most storage-contract work,
but it is not yet at the desired clean local runtime shape:

- workspace rows persist storage identity and mount-contract fields
- backend runtime calls use `WorkspaceMountSpec`
- `sandbox-manager` consumes storage backend + logical path + mount mode instead
  of `workspace_backend_path`
- workspace guidance and task attachments no longer depend on backend host-path
  reads
- runtime skills use sandbox-local detached drafts
- runtime skill payloads now use `canonical_location`
- extension bundle skill payloads are aligned with the same runtime contract
- backend compose now defaults persisted assets to `PERSISTED_STORAGE_BACKEND=seaweedfs`
- uploaded files persist through the filer backend instead of local absolute
  paths, with pending uploads staged under user-scoped storage and attached
  uploads relocated into `.../workspace/.uploads/...`
- extension package artifacts persist through the filer backend while keeping a
  local runtime cache
- canonical user skills persist through SeaweedFS-backed bundle artifacts while
  keeping a local materialized cache for registry scans and runtime mounting
- creator-owned user tools now persist canonically under
  `/users/{username}/tools/{tool_name}/tool.py` with lazy local
  materialization into the backend runtime cache
- task attachments now persist live workspace file references instead of
  immutable snapshot payloads
- chat text/markdown file cards now use session-scoped live workspace file APIs
  for open/edit/save flows
- local compose includes SeaweedFS all-in-one
- local compose now defaults to
  `SANDBOX_SEAWEEDFS_ATTACH_STRATEGY=shared_mount_root`
- local compose now defaults to
  `SANDBOX_SEAWEEDFS_REQUIRE_NATIVE_MOUNT=true`
- duplicate live workspace state under `server/workspace/` has been removed
- remaining local caches now live outside the repo tree, under platform/local
  cache roots or helper-owned mount roots instead of `server/workspace/`
- sandbox-manager now exposes `GET /runtime/seaweedfs/status` so local startup
  can verify whether native mount is actually active

What remains before the architecture is considered complete:

- document the real Option B shared-mount-root startup path across macOS,
  Windows, and Linux
- reduce or remove the remaining helper-side hydrate/flush bridge now that
  native mount is the required local path
- add higher-level API/end-to-end validation beyond the current service-level
  smoke coverage

Current helper-side bridge behavior:

- hydrate now mirrors remote filer contents incrementally and prunes stale local
  files under the helper-owned shared root
- flush now compares filer metadata and only uploads changed files plus deletes
  stale remote files, instead of recursive delete + full re-upload
- `shared_mount_root` bind sources are now resolved from the sandbox-manager's
  own mount table into Podman host-visible paths, instead of reusing
  sandbox-manager container-local paths
- warm sandbox cleanup now proactively evicts containers whose `/workspace`
  mount source no longer matches the current runtime strategy, so old
  repo-path sandboxes do not linger indefinitely
- when `/var/lib/pivot/seaweedfs-mnt` is a real mounted filesystem, the driver
  now skips filer hydrate/flush entirely and treats the shared root as the live
  workspace source of truth
- native mount detection now prefers the host-visible mount root that backs the
  sandbox-manager volume, because the manager container itself may see the
  mounted contents without `os.path.ismount()` returning true inside the
  container namespace

## Local Native Mount Notes

The current proven local mount recipe is:

- expose filer gRPC from the SeaweedFS service with `-filer.port.grpc=18888`
- publish `18888:18888` in local compose
- run the machine/host-side mount against `127.0.0.1:8888`, not the
  container-network IP
- pass `-allowOthers=false` for local Podman machine mounts, because the
  default `allow_other` path requires extra FUSE host configuration

Current local validation target:

- `/runtime/seaweedfs/status` returns `native_mount_active=true`
- `/runtime/seaweedfs/status` returns `fallback_bridge_active=false`

## Canonical Path Layout

Recommended canonical SeaweedFS layout:

- `/extensions/{scope}/{name}/{version}/artifact/{manifest_hash}.tar.gz`
- `/users/{username}/skills/{skill_name}/artifact/skill.tar.gz`
- `/users/{username}/skills/.submissions/{submission_id}/...`
- `/users/{username}/tools/{tool_name}/tool.py`
- `/users/{username}/agents/{agentid}/sessions/{session_id}/workspace/...`
- `/users/{username}/agents/{agentid}/sessions/{session_id}/workspace/.uploads/...`
- `/users/{username}/agents/{agentid}/projects/{project_id}/workspace/...`
- `/users/{username}/agents/{agentid}/projects/{project_id}/workspace/.uploads/...`

Rules:

- `.uploads` belongs to the workspace domain and should be mounted inside the
  same live `/workspace`
- `/workspace/skills/...` is a runtime materialized surface and should not
  force a matching canonical SeaweedFS directory
- builtin tools remain code-owned under
  `/server/app/orchestration/tool/builtin/`
- creator-owned tools should use SeaweedFS as canonical storage and lazy local
  materialization

## Target Runtime Topology

```text
backend
    |
    | workspace mount spec + skill materialization spec
    v
sandbox-manager (trusted helper)
    |
    | ensure SeaweedFS runtime root
    | ensure logical path
    | materialize skills
    v
prepared runtime mounts
    |
    | bind logical path as /workspace
    | mount sandbox-local skills draft area
    v
sandbox container

SeaweedFS
    |- master
    |- volume
    |- filer
```

Important security property:

- mount authority exists only in the trusted helper layer
- untrusted sandbox containers receive prepared surfaces only

## Schema Changes

### Workspace model

Add these fields to `workspace`:

- `storage_backend: str`
- `logical_path: str`
- `mount_mode: str`
- `source_workspace_id: str | None`

Recommended values for this phase:

- `storage_backend="seaweedfs"`
- `mount_mode="live_sync"`
- `source_workspace_id=NULL`

### Why store `logical_path` explicitly

Do not derive storage identity purely from scope/session/project every time.

Reasons:

- clearer storage contract
- simpler future clone support
- easier future backend changes
- simpler audit/debug output

### Schema migration strategy

This repository is still pre-production and can tolerate disruptive schema
cleanup.

Recommended approach:

- update the SQLModel schema cleanly
- add one workspace compatibility helper in `server/app/db/session.py`
- allow developers to delete the local SQLite database if needed

Do not spend time on elaborate backward-compatibility logic for obsolete
workspace layouts.

## Backend Service Refactor

### 1. `WorkspaceService`

Target responsibility:

- CRUD over workspace rows
- scope validation
- ownership lookups

Remove from this service:

- filesystem provisioning logic as the primary contract
- host-path identity generation as the primary contract

Recommended new methods:

- `create_workspace_row(...) -> Workspace`
- `get_workspace(...) -> Workspace | None`
- `delete_workspace_row(...) -> bool`

### 2. `WorkspaceStorageService`

This becomes the backend storage abstraction boundary.

Own responsibilities:

- build canonical `logical_path`
- provision storage for a workspace
- delete storage for a workspace
- produce `WorkspaceMountSpec`
- provide workspace-aware read helpers for runtime-sensitive services

Recommended conceptual API:

```python
@dataclass(frozen=True)
class WorkspaceMountSpec:
    workspace_id: str
    storage_backend: str
    logical_path: str
    mount_mode: str
    source_workspace_id: str | None = None


class WorkspaceStorageService:
    def build_logical_path(...) -> str: ...
    def provision_workspace(...) -> None: ...
    def delete_workspace(...) -> None: ...
    def build_mount_spec(...) -> WorkspaceMountSpec: ...
```

### 3. `SessionService` and `ProjectService`

Refactor goal:

- keep external behavior unchanged
- route workspace creation and deletion through `WorkspaceStorageService`

### 4. `SandboxService`

Replace path-first payloads with mount-spec payloads.

Target payload shape:

- `workspace_id`
- `storage_backend`
- `logical_path`
- `mount_mode`
- `skills`

### 5. `ReactTaskSupervisor`

Refactor goals:

- stop deriving both sandbox path and host path from `WorkspaceService`
- use `WorkspaceMountSpec`
- use storage-aware helpers for workspace guidance and attachments

### 6. `WorkspaceGuidanceService`

Problem today:

- it assumes backend can read a host-visible workspace directory directly

Target direction:

- guidance discovery should use a workspace-storage-aware read helper
- the rendered path must still be `/workspace/AGENTS.md` or `/workspace/CLAUDE.md`

### 7. `TaskAttachmentService`

Current direction:

- use workspace-aware file resolution helpers
- default to live workspace file references
- let files such as `/workspace/report.md` and `/workspace/.uploads/original.pdf`
  remain the primary objects that users and agents both edit
- keep immutable snapshot/export as an explicit optional capability only for
  audit/export/version-freeze scenarios

## Sandbox-Manager Refactor

### Request model changes

Use:

- `storage_backend`
- `logical_path`
- `mount_mode`
- `source_workspace_id`

Recommended Pydantic shape:

```python
class SandboxRequest(BaseModel):
    username: str
    workspace_id: str
    storage_backend: str
    logical_path: str
    mount_mode: str
    source_workspace_id: str | None = None
    skills: list[SandboxSkillSpec] = Field(default_factory=list)
```

### Driver abstraction

Add one runtime driver interface.

Conceptually:

```python
class WorkspaceRuntimeDriver(Protocol):
    def ensure_runtime_ready(self) -> None: ...
    def ensure_workspace_ready(self, logical_path: str, mount_mode: str) -> None: ...
    def bind_workspace(self, logical_path: str, sandbox_name: str) -> RuntimeBind: ...
    def delete_workspace(self, logical_path: str) -> None: ...
```

Implementations:

- `LocalFilesystemWorkspaceDriver` for migration only
- `SeaweedfsWorkspaceDriver` as the target route

### `SeaweedfsWorkspaceDriver`

Own responsibilities:

- verify SeaweedFS service reachability
- ensure a shared helper-side mount root exists
- ensure target `logical_path` exists
- provide the local helper-side path that should be bound to `/workspace`

Recommended helper-side constants:

- runtime mount root, for example `/var/lib/pivot/seaweedfs-mnt`
- optional skill materialization scratch root

### Runtime attach strategy

The exact attach mechanism should follow this rule:

- sandbox-manager performs the trusted attach work once
- sandbox containers only consume a prepared directory

The preferred steady state is:

- helper maintains a reusable mount root
- each sandbox only binds a logical subdirectory to `/workspace`

Avoid:

- per-sandbox filesystem mounting
- giving sandbox containers FUSE privileges

### Trusted attach decision

There are two realistic ways to finish the real SeaweedFS attach path.

#### Option A. Mount inside `sandbox-manager` and bind from its mount root

Shape:

1. `sandbox-manager` runs `weed mount -dir=/var/lib/pivot/seaweedfs-mnt`
2. the manager keeps that mount alive
3. each sandbox binds one logical subdirectory from that mount root to
   `/workspace`

Benefits:

- keeps the trusted attach logic inside the existing control-plane container
- no extra long-lived helper process beyond `sandbox-manager`
- simpler code-level control flow

Risks:

- relies on mount propagation between the manager container, the Podman runtime,
  and sandbox containers
- easy to get working on one local topology and then break on another
- especially fragile on macOS + `podman machine` and other nested-runtime setups

This option is attractive for code simplicity but risky for local portability.

#### Option B. Use a node-level shared mount root managed by a dedicated helper boundary

Shape:

1. one trusted helper prepares a mount root that is already visible at the node
   or Podman-machine level
2. `sandbox-manager` only consumes that prepared mount root and binds logical
   subdirectories into sandboxes
3. sandbox containers still never receive FUSE privileges or SeaweedFS
   credentials

Benefits:

- cleaner mount semantics because the bind source is already outside the
  manager's private mount namespace
- easier to reason about for Kubernetes, CSI, or future node-level mount
  orchestration
- better separation between control-plane orchestration and mount ownership

Costs:

- more operational plumbing
- local development setup becomes less self-contained
- one more component or bootstrap step must exist outside the manager process

#### Recommendation

Recommended long-term direction: Option B.

Reason:

- the project's security goals care more about a stable trusted boundary than
  about minimizing one container
- Option B is more likely to remain correct across local Podman, Linux, and
  future Kubernetes deployment shapes
- Option A is acceptable only as a short-lived experiment if we explicitly
  treat it as disposable validation code

#### Practical next step

For the current phase, treat the codebase as ready for either route, but do not
pretend the attach problem is solved until one of these is chosen explicitly.

If fast local iteration is the priority, test Option A first behind the
existing `SeaweedfsWorkspaceDriver`.

If architectural stability is the priority, skip Option A and design the
node-level shared mount root directly.

### Local implementation rule

Current implementation rule:

- local compose uses a temporary `compose_compat` attach strategy
- future production or Kubernetes environments should switch to
  `shared_mount_root`

This keeps local DX simple while preserving the long-term direction in the
runtime driver interface.

## Skills Runtime Refactor

### Current model

Today runtime-visible skills are:

- allowlisted by backend
- resolved to canonical host paths
- bind-mounted read-only into `/workspace/skills/<name>`

Draft edits happen separately in the writable skills volume and are submitted
through explicit snapshot/export.

### Target model

Runtime-visible skills should become sandbox-local materialized copies.

Canonical skill storage should also move into SeaweedFS-backed shared storage.

Recommended flow:

1. Studio import and manual skill authoring persist directly to canonical
   shared skill storage
2. backend computes allowed skills
3. sandbox-manager resolves canonical skill source locations
4. sandbox-manager copies or synchronizes allowed skills into the sandbox-local
   skills draft root
5. sandbox sees `/workspace/skills/<name>` as editable content

This preserves detached-draft semantics while removing the direct runtime
dependency on canonical host-path mounts.

### Suggested materialization abstraction

Conceptually:

```python
class SkillRuntimeMaterializer:
    def materialize(
        self,
        *,
        username: str,
        workspace_id: str,
        skills: Sequence[SandboxSkillSpec],
    ) -> None: ...
```

Expected behavior:

- clear stale runtime skills that are no longer allowed
- copy in missing allowlisted skills without overwriting existing drafts
- preserve the writable draft semantics inside the sandbox-local skills area

### Skill spec contract

Current phase:

- manager receives `canonical_location`
- the field still points at a backend-visible canonical skill directory
- this keeps the runtime contract explicit without forcing a full skill-storage
  identity system in the same patch

Longer-term target:

- manager receives canonical skill identity, not any raw backend-visible path
- user-facing runtime semantics still stay detached under `/workspace/skills/...`
- SeaweedFS does not need a canonical `.../workspace/skills/...` tree

Phase-1 pragmatic target:

- backend may still pass canonical skill storage path or identifier
- manager owns final materialization

## Compose Design

### Local development

Recommended first local topology:

- one all-in-one SeaweedFS service
- persistent volume(s) for SeaweedFS data
- sandbox-manager with trusted runtime attach responsibility

Suggested shape:

```yaml
services:
  seaweedfs:
    image: <seaweedfs-image>
    command: >
      weed server -master -volume -filer

  sandbox-manager:
    environment:
      - PIVOT_WORKSPACE_STORAGE_BACKEND=seaweedfs
      - PIVOT_SWFS_FILER_URL=http://seaweedfs:8888
      - PIVOT_SWFS_MOUNT_ROOT=/var/lib/pivot/seaweedfs-mnt
```

### Why start all-in-one locally

- lowest DX friction
- easiest to reason about
- enough for early runtime validation

Later, if local testing needs more realism:

- split master/volume/filer

This is an explicit DX choice:

- local development should optimize for one-service startup
- production or shared deployments can still split services later
- the temporary local cache exists only inside the compat transport and should
  not be treated as a backend-owned workspace cache design

## Image Changes

### Sandbox-manager image

Should include:

- SeaweedFS helper tooling needed for trusted runtime mount/materialization
- any required FUSE userspace tooling if the chosen attach path requires it

### Sandbox image

Should include:

- normal runtime tools only

Should not include:

- shared filesystem mount tooling
- shared filesystem credentials
- FUSE capability requirements

## Security Requirements

These are non-negotiable implementation constraints.

- sandbox containers do not receive Podman socket access
- sandbox containers do not receive mount-capable privileges
- sandbox containers do not receive shared-storage admin credentials
- sandbox-manager remains the only component that talks to Podman
- sandbox-manager should isolate helper-side runtime state from the sandbox

Also note:

- `sandbox-manager` itself becomes a more security-sensitive trusted component
- do not leak its control surface into sandbox runtime mounts

## Patch Breakdown

Recommended patch order:

### Patch 1. Add SeaweedFS design docs

- add SeaweedFS planning docs
- freeze the target architecture in writing

### Patch 2. Workspace schema and storage abstraction

- update `Workspace` model
- add workspace schema compatibility helper
- add `WorkspaceStorageService`
- refactor `SessionService` / `ProjectService` to use it
- remove builtin-specific fields and logic from the skill model/service layer

### Patch 3. Backend-to-manager mount contract

- update `SandboxService`
- update tool execution context
- update manager request models
- keep a migration-only local driver

### Patch 4. Manager runtime driver abstraction

- add `WorkspaceRuntimeDriver`
- extract local path logic behind the temporary local driver
- add `SeaweedfsWorkspaceDriver` skeleton

### Patch 5. Compose and image support

- add SeaweedFS service
- update manager image/tooling
- add runtime mount root configuration

### Patch 6. SeaweedFS trusted attach path

- ensure runtime readiness
- ensure logical path materialization
- bind logical path to `/workspace`
- remove the current `compose_compat` fallback from the default local path
- make local and production both consume shared mount root semantics

### Patch 7. Skill materialization

- stop direct canonical skill bind mounts
- materialize allowlisted skills into sandbox-local draft space
- use `canonical_location` as the current runtime materialization field

### Patch 8. Runtime-sensitive service cleanup

- workspace guidance loading
- task attachment live-reference redesign
- remaining host-path assumptions

### Patch 9. Remove old path-first architecture

- delete reverse host-path discovery
- delete local driver after validation
- this remains intentionally incomplete until production attach is ready

## Test Plan

### Unit tests

Add or update tests for:

- workspace logical path generation
- workspace mount spec generation
- manager request model validation
- skill materialization behavior
- workspace guidance loading through `WorkspaceRuntimeFileService`
- live workspace file reference handling for chat/file-open UX
- creator-owned tools materialization from SeaweedFS canonical storage

### Integration / runtime validation

Validate:

- local startup yields one true `/workspace` surface without a duplicate live
  tree under `server/workspace/`
- first task creates or reuses a shared workspace correctly
- repeated sandbox creation reuses the helper-side runtime
- file edits persist across sandbox recreation
- files under `/workspace/.uploads/...` remain live workspace assets
- git clone works
- rename-heavy workflows work
- multiple sandboxes can target different logical paths
- skill materialization obeys allowlist rules
- edited skills remain detached until approval

### Security validation

Check:

- sandbox container inspect output does not expose Podman socket
- sandbox container inspect output does not expose privileged mount surfaces
- sandbox environment does not include shared-storage admin credentials

## Failure Handling

Fail early at sandbox preparation time when:

- SeaweedFS is unavailable
- runtime mount root cannot be prepared
- target logical path cannot be created
- skills cannot be materialized
- `/workspace` cannot be attached

Do not allow the agent to start running first and discover storage failure
mid-task.

## Settled Decisions

### 1. Canonical skill storage migration timing

Decision:

- migrate canonical skills into SeaweedFS in the same series
- keep runtime semantics detached-draft

### 2. Local SeaweedFS topology

Decision:

- use one all-in-one local SeaweedFS service first

### 3. Attachment extraction strategy in phase 1

Decision:

- replace the default attachment model with live workspace file references
- keep snapshot/export only as an explicit future option when a frozen copy is
  really required

### 4. Temporary `local_fs` support lifetime

Decision:

- keep a temporary `local_fs` implementation only if it stays fully hidden
  behind the shared storage/runtime interfaces
- delete it immediately if preserving it would reintroduce host-path-first
  design pressure

### 5. Builtin skill cleanup

Decision:

- remove the builtin skill concept entirely
- clean `Skill` schema and service logic in the same migration series

### 6. Tools source of truth

Decision:

- builtin tools stay code-owned under `/server/app/orchestration/tool/builtin/`
- creator-owned non-builtin tools should use SeaweedFS canonical storage under
  `/users/{username}/tools/{tool_name}/tool.py`
- local runtime copies should be materialized lazily instead of eagerly syncing
  all tools at process startup

### 7. Skill change submissions

Decision:

- keep skill-change submissions as an approval staging concept
- persist them canonically through shared storage under
  `/users/{username}/skills/.submissions/{submission_id}/snapshot.zip`

## Final Recommendation

The clean implementation route is:

- adopt `SeaweedFS` as the shared workspace backend
- migrate canonical skill storage into SeaweedFS
- migrate creator-owned tools into SeaweedFS canonical storage
- redesign all runtime contracts around workspace identity
- let sandbox-manager own trusted attach behavior
- keep `/workspace` live-sync
- keep `/workspace/.uploads` inside the same live workspace surface
- keep `/workspace/skills` detached-draft
- default file delivery to live workspace references
- centralize backend storage knowledge in `WorkspaceStorageService`
- treat the temporary local driver as migration scaffolding only when it does
  not distort the primary abstraction
- remove builtin skill support as part of the same cleanup

This keeps the design aligned with Pivot's refined product semantics while
avoiding the runtime and DX complexity of the earlier JuiceFS route.
