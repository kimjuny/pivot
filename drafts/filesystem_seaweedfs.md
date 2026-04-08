# Pivot Filesystem Plan: SeaweedFS-First Runtime

## Summary

Pivot should switch the current workspace runtime away from host-mounted local
paths and toward a runtime-native shared filesystem model built on
`SeaweedFS`.

This plan changes two things at the same time:

- the workspace filesystem backend
- the runtime contract between backend and sandbox-manager

The recommended target model is:

- `/workspace` remains the agent-facing working directory
- `/workspace/.uploads` is part of the same live workspace surface
- non-skill workspace content is `live_sync`
- `/workspace/skills` uses detached-draft semantics, not shared live-sync
- sandbox-manager, as a trusted helper, prepares shared mounts
- untrusted sandbox containers consume prepared mounts but do not mount the
  shared filesystem themselves

This design keeps the product model simple while improving local DX, reducing
system complexity, and preserving a safer security boundary than
in-sandbox mounting.

## Why Revisit the Backend Choice

The original JuiceFS direction was strongest when Pivot wanted all of the
following from the workspace filesystem itself:

- shared live-sync workspaces
- future detached clones as a first-class filesystem capability
- strong Kubernetes alignment through a distributed filesystem client model

That assumption has now changed.

The updated product/runtime split is:

- `/workspace` is shared and live-sync
- `/workspace/skills` is not a live shared directory
- skill editing goes through allowlist + materialize/copy + submit snapshot
- skill drafts can achieve detached behavior at the application layer

Once detached behavior is moved out of the general filesystem layer and into
skill-specific runtime logic, JuiceFS loses part of its architectural edge for
this phase.

SeaweedFS becomes attractive because it offers:

- one storage family for file and object-style data
- simpler local topology than `JuiceFS + object store + metadata DB`
- a credible path to scale-out shared workspaces

This does **not** prove that SeaweedFS is the only valid choice forever. It
means SeaweedFS is the better fit for the currently refined problem.

## Core Product Semantics

The filesystem plan should now explicitly distinguish two runtime surfaces.

### 1. `/workspace`

This is the main agent workspace.

Properties:

- live-sync
- POSIX-like enough for normal shell usage
- shared persistence across sandbox recreation
- stable path for repo files, generated files, and `AGENTS.md`
- uploaded source files also live under `/workspace/.uploads/...`

### Live file references

Default file delivery should use live workspace file references, not immutable
snapshots.

Examples:

- `/workspace/report.md`
- `/workspace/.uploads/original.pdf`

This means:

- users open and edit the same live file the agent sees
- agents continue operating on the same file path
- snapshot/export stays an optional future capability, not the default UX

### 2. `/workspace/skills`

This is a runtime-visible skill surface, not the canonical shared workspace.

Properties:

- visible skills are selected through allowlist rules
- Studio import and manual skill authoring persist to canonical shared storage
- selected skills are materialized into the sandbox runtime
- edits are local draft changes inside the sandbox
- applying a change requires explicit submit + approval
- detached-draft behavior is achieved at the application layer

This distinction is intentional. It keeps shared workspace semantics simple
while preserving controlled skill editing flows.

## Goals

- preserve `/workspace` for the agent
- remove backend dependence on host workspace paths
- make local development use the same single-source-of-truth workspace model as
  the intended production runtime
- keep sandbox containers low-privilege relative to mount-capable helpers
- reduce the runtime complexity compared with the JuiceFS route
- leave thin abstraction seams so the backend is not hard-wired to SeaweedFS
- move canonical persisted assets to SeaweedFS by default
- avoid duplicate live workspace state under `server/workspace/`

## Non-Goals for This Phase

- do not ship generalized detached clone for whole workspaces
- do not require sandbox containers to mount the shared filesystem themselves
- do not commit to permanent support for both `local_fs` and SeaweedFS

## Recommended Architecture

### Storage Layers

Pivot should separate these concerns even if multiple concerns happen to use the
same storage family underneath.

#### Workspace filesystem

Used for:

- session workspaces
- project workspaces
- repo contents
- generated files
- workspace guidance files such as `AGENTS.md`

Recommended backend:

- `SeaweedFS filer + mount`

#### Skill canonical storage

Used for:

- creator-owned private skill source of truth
- shared skill source of truth

Recommended backend for this phase:

- also store canonical skill content under SeaweedFS-backed persistent storage
- but do **not** expose it to the sandbox as shared live-sync runtime content

Important distinction:

- storage backend can be unified
- runtime semantics do not need to be unified

#### Non-workspace blobs

Used for:

- extension artifacts
- creator-owned user tools

Recommended status in this phase:

- persist them through SeaweedFS-backed storage services
- allow local runtime caches where the application still needs materialized
  directories

This now includes creator-owned user tools:

- canonical source of truth lives under `/users/{username}/tools/{tool_name}/tool.py`
- builtin tools remain code-owned under
  `/server/app/orchestration/tool/builtin/`
- local runtime copies should be lazily materialized instead of preloaded at
  application startup

## Why SeaweedFS Is a Better Fit for This Phase

Compared with the earlier route:

- no separate `RustFS` service is needed for object data
- no separate `JuiceFS` client + metadata engine stack is needed
- local developer startup is simpler
- the mental model is easier to explain
- the runtime has fewer independently failing components

Compared with the current local filesystem approach:

- shared workspaces no longer depend on one backend pod's host path
- scale-out becomes possible
- sandbox-manager no longer needs reverse host-path discovery as the core model

The trade-off is explicit:

- SeaweedFS is a better fit for `live_sync`
- it is less compelling than JuiceFS when filesystem-native detached clone is a
  core requirement

This plan accepts that trade and moves detached draft behavior for skills into
application-managed logic.

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

Important notes:

- `.uploads` belongs to the workspace domain and should be mounted into the
  same live `/workspace`
- uploads can still be staged before send, but once they are attached to a
  session/project they should relocate into that workspace's
  `workspace/.uploads/...` subtree
- `/workspace/skills/...` is a runtime materialized surface and does not need a
  matching canonical SeaweedFS directory
- builtin tools remain code-owned under
  `/server/app/orchestration/tool/builtin/`
- creator-owned non-builtin tools should use SeaweedFS as canonical storage

## Local Shared-Mount Status

The local shared-mount-root implementation has moved beyond the earlier
repo-local workspace bridge:

- sandbox `/workspace` recreation now checks the actual bind source, not just
  mount presence
- shared-root bind sources are resolved to Podman host-visible paths from the
  sandbox-manager's own mount table
- background warm-sandbox cleanup now evicts containers whose `/workspace`
  source no longer matches the current attach strategy

This still stops short of a full node-level mount helper, but it keeps local
development aligned with the shared-root model instead of tolerating stale
repo-path sandboxes.

When the shared root becomes a real mount:

- the runtime now treats that mounted root as the live workspace source of
  truth
- helper-side filer hydrate/flush is skipped
- the mirror bridge remains only as a fallback for environments where the mount
  has not yet been established

## Comparative Evaluation

### SeaweedFS vs current local filesystem

`local_fs` strengths:

- simplest immediate implementation
- low local startup cost
- very easy to inspect directly on the host

`local_fs` weaknesses:

- fundamentally not scale-out friendly
- binds runtime semantics to host path assumptions
- forces sandbox-manager to reverse-discover backend mounts

SeaweedFS is clearly stronger for the long-term runtime model.

### SeaweedFS vs JuiceFS + RustFS + metadata DB

#### Performance

SeaweedFS is attractive for:

- many small files
- simple shared workspace usage
- reduced runtime indirection

JuiceFS remains attractive for:

- richer filesystem-native snapshot/clone workflows
- a stronger story when detached clones become first-class workspace behavior

The practical conclusion for Pivot is:

- for `live_sync` workspaces, SeaweedFS is likely sufficient
- for application-layer skill drafts, SeaweedFS is sufficient
- for future whole-workspace detached clones, JuiceFS still has the stronger
  native story

#### Scalability

SeaweedFS supports:

- filer-based file namespace
- scale-out object storage
- Kubernetes deployment patterns
- filer metadata backends that can evolve over time

JuiceFS also scales, but with a more complex multi-system local topology.

#### Developer Experience

SeaweedFS is the stronger option here.

Reasons:

- local all-in-one modes exist
- fewer moving parts in compose
- fewer credentials and bootstrap steps

#### System Complexity

SeaweedFS wins this phase decisively.

SeaweedFS route:

- SeaweedFS services
- trusted runtime mount helper

JuiceFS route:

- JuiceFS client
- object store such as RustFS
- metadata store such as SQLite/PostgreSQL
- trusted runtime mount helper

#### Security

The key security improvement does not come from SeaweedFS by itself. It comes
from moving mount authority out of the untrusted sandbox.

Still, SeaweedFS helps a bit indirectly because:

- the storage stack is smaller
- there are fewer credentials and runtime dependencies to distribute

## Security Model

This is a hard requirement, not an optional refinement.

### Trusted components

- backend
- sandbox-manager
- any helper process or helper container used for filesystem attach

### Untrusted components

- sandbox containers where model-authored shell commands run

### Security rules

- sandbox containers must not mount the shared filesystem themselves
- sandbox containers must not receive mount-capable privileges
- sandbox containers must not receive Podman or Docker control sockets
- sandbox containers must not receive filesystem backend admin credentials
- sandbox-manager should own runtime attach behavior

This does not make container escape impossible in the abstract. It keeps the
high-risk privileges off the untrusted execution surface.

## Runtime Model

### Backend contract

The backend should stop sending concrete backend paths as the primary workspace
identity.

Recommended mount contract:

- `workspace_id`
- `storage_backend`
- `logical_path`
- `mount_mode`
- `source_workspace_id` for future clone flows

For this SeaweedFS phase:

- `storage_backend=seaweedfs`
- `mount_mode=live_sync`

### Trusted attach flow

Recommended runtime sequence:

1. backend resolves the workspace row and storage contract
2. backend sends workspace identity to sandbox-manager
3. sandbox-manager ensures the shared SeaweedFS mount root is available
4. sandbox-manager ensures the requested logical path exists
5. sandbox-manager creates or reuses the sandbox container
6. sandbox-manager binds the logical subdirectory to `/workspace`
7. sandbox-manager materializes allowed skills into `/workspace/skills`
8. agent command runs with working directory `/workspace`

### Why this route is safer

The shared filesystem mount happens in a trusted control-plane layer.

The sandbox receives:

- a prepared workspace bind mount
- a prepared skills surface

The sandbox does **not** receive:

- FUSE capabilities
- mount privileges
- storage control credentials

## Namespace Layout

Recommended canonical logical layout:

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
  /skills
    /users
      /<username>
        /private
          /<skill_name>
  /shared-skills
    /<skill_name>
  /scratch
    /runtime-materialization
    /repair
```

Notes:

- workspace rows should point to `logical_path`, not host path
- skill canonical storage can live in the same SeaweedFS namespace without
  inheriting the same runtime mount semantics

## Local Development Topology

Recommended first local topology:

```text
backend
    |
    | workspace identity + skill materialization request
    v
sandbox-manager (trusted helper)
    |
    | ensure shared SeaweedFS mount root
    v
SeaweedFS mount root
    |
    | bind logical path into sandbox
    v
sandbox container
    |
    | /workspace
    |
    +--> /workspace/skills (sandbox-local materialized drafts)

SeaweedFS service
    |- filer
    |- volume
    |- master
```

DX principle:

- local startup should aim for the same clean workspace topology as production
- startup steps may be platform-specific
- documentation should explain those steps directly instead of assuming a
  helper script
- sandbox startup should not require per-sandbox filesystem mount commands

Recommended concrete local topology:

- one all-in-one SeaweedFS service first
- do not split master / volume / filer into separate local compose services in
  the initial implementation

### Local filer metadata

Recommended first local choice:

- embedded/default filer store on local disk

Why:

- simplest local DX
- avoids introducing PostgreSQL on day one
- keeps the storage stack light

Later options remain open:

- PostgreSQL-backed filer metadata
- MySQL-backed filer metadata
- other supported filer stores

## Shared / Production Topology

Recommended direction:

- SeaweedFS deployed as clustered services
- one or more filers per runtime environment
- trusted mount helper on each runtime worker/node
- sandbox-manager on each runtime worker/node

The exact Kubernetes shape can be decided later.

The key invariant is:

- sandboxes consume prepared workspace mounts
- sandboxes do not perform privileged mount operations themselves

## Skills Runtime Plan

This section is the biggest semantic difference from the old filesystem
discussion.

### Canonical source of truth

Skills remain persisted centrally.

Recommended first-step stance:

- canonical skill source lives in shared persistent storage
- Studio import and manual skill authoring write directly to that canonical
  shared storage
- backend registry continues to own visibility and allowlist decisions

### Runtime visibility

When a task starts:

1. backend computes visible skill set through allowlist rules
2. backend sends that skill list to sandbox-manager
3. sandbox-manager removes stale runtime skills and materializes only missing
   allowed skills into sandbox-local `/workspace/skills/<name>`
4. materialized skills are readable by the sandbox runtime

### Draft behavior

Inside the sandbox:

- skill edits affect the sandbox-local draft copy
- these edits are detached from canonical skill storage

When the agent calls `submit_skill_change`:

1. backend requests sandbox snapshot/export of the draft directory
2. backend validates and stores the draft snapshot
3. user approval decides whether canonical skill storage is updated

This reproduces detached-draft behavior without requiring filesystem-native
clone semantics.

### Why this is acceptable

Skills are a controlled domain:

- directory structure is constrained
- updates already go through approval
- explicit snapshot/apply is already a good UX fit

This is very different from making *all* workspace file operations detached by
default.

## Backend Data Model Changes

The `workspace` table should be upgraded to reflect storage identity directly.

Recommended fields:

- `workspace_id`
- `agent_id`
- `user`
- `scope`
- `session_id`
- `project_id`
- `status`
- `storage_backend`
- `logical_path`
- `mount_mode`
- `source_workspace_id`
- `created_at`
- `updated_at`

Recommended defaults for this phase:

- `storage_backend="seaweedfs"`
- `mount_mode="live_sync"`
- `source_workspace_id=NULL`

Since the project is pre-production, prioritize clean schema design over
backward-compatibility-heavy migration code.

## Skill Model Cleanup

This migration should also simplify the skill model itself.

Recommended cleanup:

- remove the `builtin skill` concept entirely
- remove the `builtin` field from the `Skill` schema
- remove builtin-skill discovery logic
- remove builtin-only read-only special cases
- keep only meaningful user-facing skill kinds such as `private` and `shared`
- keep only real skill sources such as `manual`, `network`, `bundle`, and
  `agent`

Why:

- builtin skills are no longer part of the intended long-term product model
- ownership and approval rules become uniform
- canonical storage layout becomes simpler

## Backend Service Structure

### `WorkspaceService`

Keep:

- CRUD for workspace rows
- scope validation
- ownership lookups

Stop doing:

- direct host-directory creation as the primary contract
- direct host-path derivation as the primary identity

### `WorkspaceStorageService`

This service should become the canonical storage abstraction boundary.

Own responsibilities:

- generate `logical_path`
- create canonical workspace storage state
- delete canonical workspace storage state
- build workspace mount spec for sandbox-manager

This should be the only backend service that knows the selected workspace
storage backend in detail.

### `WorkspaceGuidanceService`

Refactor goal:

- stop assuming backend can read host-mounted workspace files directly

Recommended direction:

- read guidance through storage-aware helpers or sandbox-runtime-aware helpers
- preserve the product contract that guidance is rendered as `/workspace/...`

### `TaskAttachmentService`

Refactor goal:

- stop relying on backend-visible host workspace paths

Recommended direction:

- resolve attachment source files through the active runtime workspace contract
- default to live workspace file references instead of immutable snapshots
- treat uploaded source files under `/workspace/.uploads/...` as first-class
  workspace assets

## Sandbox-Manager Changes

### New responsibilities

- manage the trusted mount lifecycle
- ensure shared SeaweedFS mount root is ready
- materialize workspace logical paths
- materialize allowed skills into sandbox-local drafts

### Suggested abstraction

Conceptually:

```python
class WorkspaceRuntimeDriver:
    def ensure_runtime_ready(...) -> None: ...
    def ensure_workspace_ready(...) -> None: ...
    def attach_workspace(...) -> None: ...
    def materialize_skills(...) -> None: ...
```

Implementations:

- temporary `LocalFilesystemWorkspaceDriver` during migration only
- target `SeaweedfsWorkspaceDriver`

### Important implementation note

The temporary local driver should be treated as migration scaffolding, not as a
permanent multi-backend product commitment.

## Mount Helper Strategy

The trusted mount helper is currently expected to be the existing
`sandbox-manager` role.

Recommended principle:

- keep this as one operational component for now
- keep the code logically separated so it can be split later if needed

### Why sandbox startup overhead should stay low

The shared mount root should be prepared once and reused.

That means:

- no per-sandbox FUSE mount
- no per-sandbox helper container startup
- only per-sandbox bind/attach work

### Real attach options

There are two plausible ways to finish the actual SeaweedFS attach path.

Option A:

- `sandbox-manager` performs the FUSE mount itself
- sandboxes bind subdirectories from the manager-owned mount root

Trade-off:

- simplest code path
- but mount propagation becomes the critical risk

Option B:

- a node-level or dedicated trusted helper owns the shared mount root
- `sandbox-manager` only binds already-visible subdirectories into sandboxes

Trade-off:

- more setup and operational plumbing
- but the security and mount semantics are cleaner

Recommended direction:

- prefer Option B for the long-term architecture
- use Option A only as a short-lived validation route if local DX must move
  faster than infrastructure design

### Local development target

Local development should target the same clean runtime shape as the intended
production architecture:

- a trusted helper prepares a shared mount root
- sandbox-manager consumes that shared root
- sandboxes bind logical workspace subpaths directly from that shared root
- backend does **not** keep a duplicate live workspace tree under
  `server/workspace/`

Current local implementation status:

- local compose already provisions SeaweedFS all-in-one
- backend and sandbox-manager already speak the new mount contract
- runtime skills already use detached materialization instead of canonical bind
  mounts
- local default now uses `shared_mount_root`
- local default also requires a real native mount under that shared root
- repo-local `server/workspace/` no longer carries duplicate live workspace
  trees or uploaded workspace assets
- sandbox-manager now exposes `/runtime/seaweedfs/status` so local startup can
  verify whether the native mount is active
- some helper-side hydrate/flush behavior still exists as the remaining bridge
  around the native mount path, but local default no longer accepts bridge
  fallback as the steady state
- that helper-side bridge now performs incremental mirror syncs instead of
  deleting and re-uploading the whole logical tree on every flush

Important clarification:

- the intended architecture does **not** give Pivot backend its own workspace
  cache
- local development should not rely on `server/workspace/` as a second live
  workspace copy
- production and local development should converge on the same shared mount
  root model

The heavier cost should be paid during:

- manager/helper startup
- shared filesystem readiness

not during every sandbox creation.

### Current local native-mount recipe

The currently proven local mount shape is:

- SeaweedFS filer gRPC is exposed on `18888`
- local native mount talks to filer through `127.0.0.1:8888`
- local native mount uses `-allowOthers=false` in Podman machine environments
- native mount readiness is validated through
  `/runtime/seaweedfs/status -> native_mount_active=true`

## Compose and Image Changes

### Local compose

Recommended change set:

- replace RustFS + JuiceFS-related services with SeaweedFS services
- add persistent volume(s) for SeaweedFS data
- keep sandbox-manager as the mount-capable trusted helper

The local compose can start simple:

- one SeaweedFS service in all-in-one mode for development

Later, if needed:

- split master / volume / filer explicitly

### Sandbox-manager image

Should include:

- SeaweedFS client tooling needed for trusted mounting/materialization
- FUSE userspace tooling if the chosen attach implementation needs it

### Sandbox image

Should **not** need:

- filesystem mount tooling
- storage admin credentials
- FUSE capability

## Rollout Plan

### Phase 1. Contract and schema cleanup

- add storage identity fields to workspace rows
- introduce `WorkspaceStorageService`
- change backend-to-manager payload to workspace identity + mount contract

### Phase 2. Manager driver abstraction

- add runtime driver interface
- keep `local_fs` driver only as temporary migration support

### Phase 3. SeaweedFS local runtime

- add SeaweedFS service to compose
- implement trusted helper readiness path
- attach workspace logical path to `/workspace`

### Phase 4. Skill materialization

- stop direct read-only bind mounting of canonical skills from backend paths
- materialize allowlisted skills into sandbox-local drafts

### Phase 5. Remove old path-first logic

- delete reverse host-path discovery as the primary architecture
- delete local_fs driver after SeaweedFS path passes validation

## Validation Checklist

### Core workspace

- local startup yields one true `/workspace` surface without a duplicate live
  copy under `server/workspace/`
- create, edit, rename, and delete files under `/workspace`
- clone a real git repository
- run `git status`, branch operations, and file renames
- recreate sandbox and verify workspace persistence

### Skills

- allowlist only exposes intended skills
- skill content appears under `/workspace/skills/<name>`
- sandbox edits stay local until submit
- submitted skill draft snapshots can be approved and applied
- rejected drafts do not mutate canonical skill storage

### Security

- sandbox does not receive Podman socket
- sandbox does not receive mount capability
- sandbox does not receive shared filesystem admin credentials

### Runtime and DX

- repeated sandbox creation does not re-run full mount initialization
- manager startup performs shared runtime initialization only once

## Risks

### 1. Shared mount transport under Podman

The exact attach mechanism between trusted helper and sandbox runtime still
needs validation.

This is a runtime plumbing risk, not a product-model risk.

### 2. FUSE requirements in helper runtime

Depending on the exact helper implementation, mount prerequisites may vary
across local platforms and Podman environments.

### 3. SeaweedFS live-sync semantics need workload validation

The official feature surface is promising, but Pivot should still verify real
developer workloads such as:

- git clone
- frequent rename
- many small file writes
- branch switching
- concurrent workspace access

### 4. Whole-workspace detached clone remains unsolved in this phase

This is an intentional deferral, not an accidental omission.

## Questions That Still Need Your Call

### 1. Should canonical skill storage move into SeaweedFS in phase 1?

Recommendation:

- yes
- Studio import and manual skill authoring should persist directly into
  SeaweedFS-backed canonical storage
- runtime semantics must still remain detached-draft

### 2. Should local compose start with a single all-in-one SeaweedFS service or split services immediately?

Recommendation:

- single all-in-one service first for local DX
- split later only if development behavior or observability requires it

### 3. Should we retain the temporary `local_fs` driver after SeaweedFS passes smoke tests?

Recommendation:

- yes, only if it remains fully contained behind the shared storage/runtime
  interfaces
- no, if preserving it forces host-path assumptions or pollutes the main
  contract

Rule:

- shared interfaces may stay
- host-path-first architecture must not come back just to preserve `local_fs`

### 4. How aggressively should we refactor services that currently assume host-visible workspace paths?

Recommendation:

- refactor all workspace-runtime-sensitive services in the same series:
  `WorkspaceGuidanceService`, `TaskAttachmentService`, tool execution context,
  sandbox service payloads

This avoids shipping a half-path-based architecture.

### 5. Do we want to reserve a future path for whole-workspace detached clone in the schema now?

Recommendation:

- yes
- keep `source_workspace_id` in the schema
- keep `mount_mode` explicit

This keeps future evolution cheap even if phase 1 only supports `live_sync`.

## Final Recommendation

Pivot should adopt the following design:

- `SeaweedFS` as the shared workspace storage backend
- canonical skill storage in SeaweedFS
- trusted mount preparation in sandbox-manager
- live-sync `/workspace`
- detached-draft `/workspace/skills`
- thin backend and manager abstraction seams
- temporary local_fs support only if it stays fully hidden behind shared
  storage/runtime interfaces
- clean schema changes now, since the project is still pre-production
- remove builtin skill support as part of the cleanup

This route is simpler than the earlier JuiceFS plan, better aligned with the
updated product semantics, and more compatible with the security boundary Pivot
wants to preserve.
