# Pivot Filesystem And DFS Design

## Goal

Pivot needs one filesystem architecture that supports:

- Extremely simple default development startup
- Optional external filesystem providers
- Safe fallback to `local_fs` when external providers are unavailable
- Session-private and project-shared workspaces
- Live file references inside the active workspace
- Future scale-out in production

This draft records the current design consensus and the remaining open
questions.

## Implementation Status

Current phase summary:

- Phase 1 through Phase 7 are substantially implemented in code.
- Phase 8 is functionally complete:
  - storage providers, resolver fallback, and the `seaweedfs` profile exist
  - backend and sandbox-manager now share a configurable backend-visible
    workspace root
  - the Studio UI can surface storage fallback via `/api/system/storage-status`
  - the repository `compose.yaml` now includes a `seaweedfs` profile
  - one repository `compose.yaml` now owns both the default stack and the
    optional external SeaweedFS stack
- Phase 9 is now the main remaining track:
  - validate real platform workflows
  - document which paths are fully supported versus operator-prepared

## Validation Snapshot

The following observations were validated on the current development machine on
2026-04-09.

### Validated now

- `podman compose up -d` starts Pivot successfully.
- `GET /health` returns healthy.
- `GET /api/system/storage-status` reports:
  - `requested_profile=auto`
  - `active_profile=local_fs`
  - `object_storage_backend=local_fs`
  - `posix_workspace_backend=local_fs`
- `podman compose --profile seaweedfs up -d` successfully starts the SeaweedFS
  filer service in the same repository compose stack.
- `http://localhost:8888` serves the SeaweedFS filer explorer UI correctly.
- with `STORAGE_PROFILE=auto`, a healthy filer plus one namespace-matching
  POSIX entrypoint activates the external profile automatically and reports:
  - `requested_profile=auto`
  - `active_profile=seaweedfs`
  - `object_storage_backend=seaweedfs`
  - `posix_workspace_backend=mounted_posix`
- the currently validated default external POSIX root is:
  - `/tmp/pivot-seaweedfs-posix`
- on macOS with Podman machine, that path is VM-local rather than a macOS host
  directory

### Validated current limitation

- The repository compose stack can start SeaweedFS itself.
- SeaweedFS startup alone is not enough to activate the external profile.
- Before the current fix, the external POSIX entrypoint pointed at a separate
  host path and did not share namespace with the filer.
- That mismatch is what produced the warning:
  - `SeaweedFS object and POSIX roots are not exposing the same namespace`

Why this warning is currently expected:

- the backend healthcheck writes one probe object through the SeaweedFS filer
  API
- Pivot then checks whether the same logical file becomes visible from the
  configured POSIX entrypoint
- when the filer and POSIX entrypoint do not share one backing directory, the
  external profile must stay on `local_fs`

## POSIX Bridge Design

This is now the main remaining engineering problem for the external profile.

### What is missing today

The repository can already do these two things:

- start SeaweedFS itself
- consume one operator-prepared POSIX bridge from the backend and
  sandbox-manager containers

What it does not do yet:

- prepare the SeaweedFS FUSE mount automatically
- fully validate the bridge across the whole sandbox lifecycle on every target
  platform

So the current setup can now prove:

- filer availability
- real shared namespace between object and POSIX views
- fallback correctness
- diagnostic clarity

But it still cannot yet prove:

- one-command automatic POSIX bridge preparation
- long-term production-grade POSIX bridge recommendations

### Candidate bridge shapes

#### Option A: VM-local FUSE mount

Shape:

- SeaweedFS filer runs in the repository compose stack
- one SeaweedFS FUSE mount is prepared at `/tmp/pivot-seaweedfs-posix`
- backend and sandbox-manager consume that path as `/app/server/external-posix`

Validated mount command:

```bash
weed mount \
  -filer=127.0.0.1:8888 \
  -dir=/tmp/pivot-seaweedfs-posix \
  -dirAutoCreate \
  -nonempty \
  -allowOthers \
  -volumeServerAccess=filerProxy
```

Important note:

- `-volumeServerAccess=filerProxy` is required in the current Podman-machine
  dev topology
- without it, the mount may expose directory entries but still fail ordinary
  POSIX writes with `Errno 5`

Pros:

- validated successfully on the current macOS + Podman machine setup
- avoids macOS host filesystem bridge issues
- keeps one neutral default path that also makes sense on Linux
- does not reintroduce a startup wrapper

Cons:

- the POSIX bridge is still operator-prepared rather than repository-managed
- the mount lifecycle still needs more validation through real sandbox use

Current decision:

- chosen as the current mainline development bridge

#### Option B: host-level FUSE mount

Shape:

- operator prepares a SeaweedFS FUSE mount on host
- Pivot points its external POSIX entrypoint at that mounted path

Pros:

- closest match to the intended long-term `POSIXWorkspace` semantics
- remains a strong production-oriented direction

Cons:

- host preparation remains outside repository compose
- macOS and Linux need real validation
- Windows remains the weakest path

#### Option C: host-level WebDAV mapped drive

Shape:

- operator prepares a WebDAV-backed host path and points Pivot at it

Pros:

- closer to the official SeaweedFS Windows story
- may be more practical than FUSE on some hosts

Cons:

- not automatically equivalent to POSIX semantics
- needs explicit validation for sandbox workspace behavior
- should not be treated as production-ready without testing

#### Option D: repository-managed mount helper

Shape:

- the repository itself tries to prepare the POSIX bridge automatically

Current decision:

- not chosen as the mainline path

Why not:

- it would reintroduce extra orchestration complexity
- it would blur the line between "service startup" and "host filesystem
  preparation"
- it is exactly the kind of hidden setup we do not want to hide behind another
  startup wrapper

### Current recommendation

- keep one repository `compose.yaml`
- keep developer startup to:
  - `podman compose up`
  - `podman compose --profile seaweedfs up -d`
- use the VM-local FUSE bridge first
- keep validating the bridge through `/api/system/storage-status`

### What counts as a successful bridge

The bridge should be considered valid only when all of the following are true:

- SeaweedFS filer is reachable
- the shared external POSIX entrypoint is visible to backend
- a filer-written probe object becomes visible from the same logical path under
  the POSIX entrypoint
- `/api/system/storage-status` reports:
  - `active_profile=seaweedfs`
  - `object_storage_backend=seaweedfs`
  - `posix_workspace_backend=mounted_posix`

### Important compose finding

- Compose profile selection does not flow into variable substitution.
- A direct validation with a temporary compose file showed that
  `${COMPOSE_PROFILES:-none}` still resolves to `none` even when the stack is
  launched with `--profile seaweedfs`.
- Therefore, the repository uses `STORAGE_PROFILE=auto` and backend-side
  runtime validation instead of relying on compose profile interpolation to
  change env vars.

### Practical conclusion

- The current repository is now honest about three states:
  - default startup works and stays on `local_fs`
  - SeaweedFS service startup works in the same compose stack
- automatic activation of the external profile only happens when the filer
  and the POSIX entrypoint prove they expose the same namespace
- The remaining work is no longer startup wiring. It is platform validation and
  documentation of the external POSIX mount prerequisite.

### Diagnostic endpoint

`GET /api/system/storage-status` is the main developer diagnostic surface.

It should be treated as the quickest way to answer:

- which profile was requested
- which profile is actually active
- whether fallback happened
- which external POSIX root Pivot is trying to use
- whether that POSIX root is visible to backend right now

## Current Dev Startup Commands

The repository now uses one `compose.yaml`:

```bash
podman compose up
podman compose up -d
podman compose --profile seaweedfs up -d
```

Meaning:

- `podman compose up`
  - starts Pivot in auto-detect mode
  - falls back to `local_fs` unless the external profile validates cleanly
- `podman compose --profile seaweedfs up -d`
  - starts the optional SeaweedFS service in the same stack
  - lets Pivot auto-activate the external profile when the POSIX entrypoint is
    ready

Default path policy:

- macOS and Linux default external POSIX root:
  - `/tmp/pivot-seaweedfs-posix`
- macOS note:
  - when using Podman machine, this path lives inside the VM rather than on the
    macOS host filesystem
- Windows:
  - default to `local_fs`
  - do not require an external POSIX root for development

Important limitation:

- compose does not create the POSIX mount for SeaweedFS
- the host-visible POSIX root must already exist before startup

### Current platform startup steps

Linux:

1. Install Podman and `podman compose`.
2. Run `podman compose up` for the default local development path.
3. If you want to validate the external provider path, prepare
   `/tmp/pivot-seaweedfs-posix` so it exposes the same namespace as SeaweedFS.
4. Run `podman compose --profile seaweedfs up -d`.
5. Check `/api/system/storage-status`.
   `active_profile=seaweedfs` means the full external path is active.
   `active_profile=local_fs` means Pivot stayed on fallback.

macOS:

1. Install Podman and ensure Podman machine is running.
2. Run `podman compose up` for the default local development path.
3. If you want to validate the external provider path, prepare
   `/tmp/pivot-seaweedfs-posix` inside the Podman VM before startup.
4. Run `podman compose --profile seaweedfs up -d`.
5. Check `/api/system/storage-status`.

Windows:

1. Install Podman Desktop or an equivalent Podman environment.
2. Run `podman compose up`.
3. Use the default `local_fs` path as the normal development workflow.
4. Treat external SeaweedFS plus external POSIX workspace routing as a separate
   validation path, not a baseline requirement.

## Decision Summary

### Agreed decisions

- Pivot will support two logical storage capabilities:
  - `POSIXWorkspace`
  - `ObjectStorage`
- `local_fs` remains the default storage profile.
- External storage is optional. Pivot must still start with `podman compose up`
  even when the external provider is not started.
- If an external provider is configured but fails health checks at startup,
  Pivot must log a prominent `WARNING` and fall back to `local_fs`.
- The logical directory structure must look the same under both `local_fs` and
  external providers.
- Sandbox only sees one mounted workspace at `/workspace`.
- Assistant-generated attachments should become live references inside the
  active workspace rather than immutable snapshots.
- Builtin skills should be removed from the long-term architecture.
- Long-lived local materialization cache should be avoided.
- If temporary local files are unavoidable for one library or runtime edge
  case, they should live under `/server/data/.local_cache/`.

### Current recommendation

- Default development profile: `local_fs`
- First external profile to evaluate seriously: `seaweedfs`
- External provider startup can live in the main repository compose stack as an
  optional profile, as long as Pivot still boots and falls back cleanly.

## Why The Storage Model Must Split Into Two Capabilities

Pivot does not just "store files". It has two different runtime needs:

- It needs object-like persistence for uploads, extension artifacts, skill
  bundles, and tool source payloads.
- It also needs one real directory tree that sandbox-manager can bind mount
  into `/workspace`.

These are different capabilities even when one product can implement both.

### POSIXWorkspace

`POSIXWorkspace` means:

- There is one real host-visible directory tree for the active workspace.
- Sandbox-manager can bind mount that directory into `/workspace`.
- The agent can read and write normal files inside the mounted workspace.

In `local_fs`, this is just a normal local directory.

In an external profile, this still must end as a host-visible directory tree.
The difference is that the directory may come from an external filesystem that
is already mounted or otherwise exposed on the host.

### ObjectStorage

`ObjectStorage` means:

- The backend can persist and load named blobs by logical key.
- The backend does not assume the caller needs a host path.
- This layer is the long-term source of truth for non-workspace assets.

Even when one system provides both APIs, Pivot should still keep the two
capabilities separate in code.

## Logical Namespace

The same logical layout must be used for `local_fs` and external providers.
This is a hard requirement.

### Workspace-backed paths

```text
users/{username}/agents/{agent_id}/sessions/{session_id}/workspace/...
users/{username}/agents/{agent_id}/sessions/{session_id}/workspace/.uploads/...
users/{username}/agents/{agent_id}/projects/{project_id}/workspace/...
users/{username}/agents/{agent_id}/projects/{project_id}/workspace/.uploads/...
```

These paths are the canonical logical roots for workspaces.

### Other asset paths

The following structure is also currently recommended:

```text
extensions/{scope}/{name}/{version}/artifact/{manifest_hash}.tar.gz
users/{username}/skills/{skill_name}/artifact/{content_hash}.tar.gz
users/{username}/skills/.submissions/{submission_id}/snapshot.zip
users/{username}/tools/{tool_name}/artifact/{content_hash}.py
```

This keeps workspace data and non-workspace assets in one consistent namespace
without mixing storage semantics.

## Sandbox Mapping

Only the active workspace subtree should be exposed to sandbox.

Example:

- Logical root:
  `users/alice/agents/7/sessions/s-123/workspace/`
- Sandbox mount target:
  `/workspace`

Inside sandbox, the agent should only see:

- `/workspace/...`
- `/workspace/.uploads/...`
- `/workspace/AGENTS.md`
- `/workspace/skills/...`

The higher-level namespace prefix must not be exposed inside sandbox.

## Workspace Semantics

### Session-private workspace

One session-private workspace uses:

```text
users/{username}/agents/{agent_id}/sessions/{session_id}/workspace/
```

### Project-shared workspace

One project-shared workspace uses:

```text
users/{username}/agents/{agent_id}/projects/{project_id}/workspace/
```

### Live uploads and generated artifacts

The active workspace owns one `.uploads` folder:

```text
/workspace/.uploads/
```

This should hold:

- User-uploaded files that are intended for the active session or project
- Assistant-generated files that the user may open and continue editing

The important product decision is:

- Attachments are live references, not snapshots

Implications:

- Historical attachment views may show the current file contents, not the
  original content from the moment the answer was produced.
- If the file is deleted, the attachment reference becomes broken.
- This is acceptable because the product goal is live editing, not immutable
  archival playback.

Because of this decision, the separate snapshot-oriented
`task_attachments/{task_id}/...` object namespace is no longer preferred.

### External POSIX explorer visibility

When an external `POSIXWorkspace` provider is active, the workspace body should
be visible in that provider's file explorer.

Examples:

- `users/{username}/agents/{agent_id}/sessions/{session_id}/workspace/...`
- `users/{username}/agents/{agent_id}/projects/{project_id}/workspace/...`

This should include normal workspace files such as:

- ordinary workspace files
- `.uploads/...`
- `AGENTS.md`

The explorer should therefore let operators and developers inspect the real
workspace contents maintained by the external `POSIXWorkspace` provider.

## Local Paths Inside Pivot

### Recommended local layout

```text
/server/data/storage/
/server/data/.local_cache/
```

Recommended meaning:

- `/server/data/storage/`
  - Source-of-truth local data when the active profile is `local_fs`
- `/server/data/.local_cache/`
  - Temporary files only
  - Short-lived spill files
  - Transitional library compatibility files

### Important clarification

`local_fs` is not a cache.

It is safer to keep its source-of-truth data out of `.local_cache`, even if
both directories live under `/server/data/`.

This keeps the architecture easier to reason about:

- If something under `.local_cache` is lost, Pivot should recover.
- If something under `storage/` is lost while `local_fs` is active, data is
  truly lost.

## Fallback Semantics

Fallback must mean a full storage profile switch, not a background sync mode.

When Pivot falls back to `local_fs`:

- the active workspace source of truth becomes local
- object-storage semantics also fall back to the local implementation
- sandbox mounts the local workspace directly
- Pivot must not start a hidden workspace synchronizer
- Pivot must not mirror workspace contents continuously to the failed external
  provider

This is especially important for Windows development.

Windows `local_fs` fallback should not mean:

- download the whole workspace from external object storage before sandbox
  start
- keep a filesystem watcher running
- upload every local change back to the external provider

That would turn fallback into a bidirectional sync system, which would add
substantial complexity and conflict handling.

Instead, fallback should be treated as one complete storage-mode decision for
the current runtime.

## No Long-Lived Local Materialization Cache

The long-term design direction is:

- Do not keep a persistent local materialization cache for external object
  storage.
- Load small objects directly into memory when possible.
- Only create temporary local files when a specific library absolutely requires
  a file path.

This does not remove the need for `POSIXWorkspace`.

`POSIXWorkspace` still must be a real directory tree because sandbox-manager
bind mounts it into `/workspace`.

The "no cache" decision applies to non-workspace assets first:

- Extension artifacts
- Tool source payloads
- Skill bundle payloads
- Submission snapshots

## Source Of Truth Rules

### Extensions

The canonical source of truth for extensions should live in `ObjectStorage`.

Recommended canonical form:

```text
extensions/{scope}/{name}/{version}/artifact/{manifest_hash}.tar.gz
```

Runtime directories used to load extension tools, hooks, providers, and assets
are derived views, not the source of truth.

### Skills

The canonical source of truth for skills should also live in `ObjectStorage`.

Recommended canonical form:

```text
users/{username}/skills/{skill_name}/artifact/{content_hash}.tar.gz
```

The runtime-visible `/workspace/skills/...` tree is not the source of truth.
It is a derived runtime view created only for the current sandbox.

### How to tell `POSIXWorkspace` from `ObjectStorage` in one shared backend

If one system such as SeaweedFS provides both capabilities, the distinction is
logical rather than UI-native.

The backend should rely on namespace conventions:

- `.../workspace/...`
  - `POSIXWorkspace`
- `.../artifact/...`
  - canonical `ObjectStorage` artifacts
- `.../.submissions/...`
  - canonical `ObjectStorage` submission payloads

This means that in one shared file explorer, both may appear as ordinary files
and directories. The meaning comes from the path contract, not from a storage
type badge inside the explorer UI.

### Local fallback interpretation

When the active profile is `local_fs`, the same rules still apply logically:

- `ObjectStorage` remains the canonical abstraction
- `local_fs` is just the implementation behind that abstraction

This keeps the meaning of "source of truth" stable across profiles.

## Security Model

Pivot's sandbox security assumption is intentionally strict:

- Assume malicious code may run inside sandbox.
- Assume the worst case is sandbox escape.
- Even after escape, the attacker should not gain host root privileges.
- This is one reason Pivot uses Podman rather than Docker.

This has direct consequences for filesystem design.

### Security requirements

- Sandbox must never receive global object storage credentials.
- Sandbox must never see the full external storage root.
- Sandbox must only receive the active workspace bind mount at `/workspace`.
- External storage health checks, authentication, and provider operations must
  happen in Pivot Server or sandbox-manager, not inside sandbox.
- If a host-level external filesystem mount exists, sandbox-manager should bind
  only the workspace subtree, never a broader mount root.

### Why this matters for DFS design

If the external provider requires broad host access to a mounted filesystem,
that access becomes part of the attack surface after a hypothetical escape.

So Pivot must keep the blast radius narrow:

- Workspace subtree only
- No provider admin credentials in sandbox
- No mount of global storage root into sandbox

## Provider Model

In Pivot, a "provider" is just backend Python code behind stable interfaces.

It is not a new process model and not a plugin protocol by itself.

### Recommended code layout

```text
server/app/storage/types.py
server/app/storage/profiles.py
server/app/storage/providers/local_fs.py
server/app/storage/providers/seaweedfs_object.py
server/app/storage/providers/mounted_posix.py
```

### Recommended interfaces

`ObjectStorageProvider` should own:

- `healthcheck()`
- `get_bytes(key)`
- `put_bytes(key, data, ...)`
- `delete(key)`
- `exists(key)`

`POSIXWorkspaceProvider` should own:

- `healthcheck()`
- `ensure_workspace(logical_root)`
- `delete_workspace(logical_root)`

### Storage profiles

A user-facing storage profile can map to multiple internal provider classes.

Example:

- `local_fs`
  - object provider: local filesystem implementation
  - posix provider: local filesystem implementation
- `seaweedfs`
  - object provider: SeaweedFS object API implementation
  - posix provider: mounted external POSIX implementation

This keeps configuration simple without forcing one Python class to fake both
roles at once.

## Runtime Injection Rules

### Skills are not pre-baked into every workspace

The preferred model is:

- do not pre-copy all skills into every workspace
- do not treat skills as ordinary workspace files
- expose skills to sandbox only when sandbox is created or refreshed
- expose only the skills allowed for the current runtime

So `/workspace/skills` should be treated as:

- a runtime-injected view
- derived from the current allowlist and runtime context
- read-only from the sandbox perspective

This means the preferred behavior is:

- skills are not fully pre-populated into every workspace ahead of time
- when sandbox is created or refreshed, only the allowlisted skills for the
  current runtime are exposed under `/workspace/skills`

### Extension runtime assets are also on-demand

Extensions should follow the same spirit:

- extension artifacts live canonically in `ObjectStorage`
- runtime loading should fetch or materialize only what is needed
- long-lived local runtime copies should not become the canonical source

## Startup Model

### Required default behavior

Pivot must start with one command:

```text
podman compose up
```

This command must start Pivot successfully even when no external provider is
running.

### External provider behavior

External providers should live in the same repository and should be startable
through the same `compose.yaml`, but they should remain optional.

The preferred shape is `compose` profiles.

Example shape:

```text
podman compose up
podman compose --profile seaweedfs up
```

Meaning:

- `podman compose up`
  - starts Pivot only
- `podman compose --profile seaweedfs up`
  - starts Pivot plus the SeaweedFS services defined in the same repository

This keeps the DX simple while avoiding a hard dependency on external storage
for every developer.

Pivot startup should then:

1. Read storage profile configuration.
2. If the profile is external, run provider health checks.
3. If health checks pass, use the external profile.
4. If health checks fail, emit a prominent `WARNING` and fall back to
   `local_fs`.

### Warning requirements

The startup warning should include:

- The configured profile name
- The endpoint or mount root that failed
- The failure reason
- The fact that Pivot fell back to `local_fs`

## Cross-Platform Development

### Agreed requirement

Development startup must support:

- macOS
- Windows
- Linux

### Current conclusion

Pivot itself can satisfy this requirement because:

- Default development startup uses `local_fs`
- `podman compose up` can still boot Pivot without the external provider

### External provider conclusion

Cross-platform startup for the external storage service itself appears feasible.
SeaweedFS officially documents:

- prebuilt binaries for different platforms
- one-binary local startup with `weed mini`
- container-based S3 startup
- FUSE-based local directory mounting
- WebDAV access for mapped drives on Mac and Windows

However, the *full* external `POSIXWorkspace` path is not equally mature across
all development hosts.

#### Practical interpretation

- macOS: external SeaweedFS service startup is feasible; POSIX-style workspace
  access appears feasible but needs local validation in our exact Podman-based
  setup.
- Linux: external SeaweedFS service startup is feasible; POSIX-style workspace
  access appears feasible and is the most straightforward target.
- Windows: external SeaweedFS service startup is feasible, but host-side POSIX
  workspace routing for sandbox should be treated as uncertain until validated.
  Windows may require WSL2 or another compatibility layer for the POSIX side.

### Important clarification about Windows risk

The expected Windows risk is not `local_fs`.

The expected Windows risk is the external provider path when `POSIXWorkspace`
must be exposed as a real host-visible directory for sandbox bind mounting.

Current expectation:

- `local_fs` is the safe default path on Windows.
- External object storage service startup is likely feasible on Windows.
- External `POSIXWorkspace` routing is the part that remains uncertain on
  Windows and needs validation.

Because Pivot always falls back to `local_fs`, this uncertainty does not block
cross-platform development startup for Pivot itself.

## Why SeaweedFS Is The Current Leading Candidate

SeaweedFS is currently the most promising first external profile because its
official project documentation presents one system with:

- object API support
- filer-based directory semantics
- POSIX FUSE mount support
- WebDAV support
- simple single-binary development startup
- Kubernetes-oriented deployment paths

This is a better fit for Pivot's "simple by default, scalable later" direction
than a more fragmented stack.

### Current recommendation

- Treat `seaweedfs` as the first serious external profile candidate.
- Do not make external storage mandatory for local development.
- Keep `local_fs` as the default path until SeaweedFS integration is validated
  on real developer machines.

### Current platform recommendation for development

- Linux:
  - prefer validating external `POSIXWorkspace` with `SeaweedFS`
- macOS:
  - also prefer validating external `POSIXWorkspace` with `SeaweedFS`
- Windows:
  - default to `local_fs`
  - do not require the full external `POSIXWorkspace` path for the normal
    development workflow
  - keep the normal startup path as plain `podman compose up`

### Summary of the two development modes

#### With external `POSIXWorkspace` provider

- workspace bodies are maintained by the external `POSIXWorkspace` provider
- sandbox mounts the external workspace path directly into `/workspace`
- developers should be able to inspect workspace files in the external
  provider's file explorer
- `skills` and `extensions` still use `ObjectStorage` as their canonical source
  of truth
- the preferred local entrypoint is:
  - `podman compose --profile seaweedfs up`

#### Without external `POSIXWorkspace` provider

- workspace bodies are maintained on the developer host via `local_fs`
- sandbox mounts the host workspace directly into `/workspace`
- `local_fs` fallback is a full storage profile switch
- Pivot does not run a hidden bidirectional sync loop between local workspace
  data and the external provider
- the preferred local entrypoint is:
  - `podman compose up`

## Skills Direction

Builtin skills should be removed from the target design.

Future skill sources should instead come from:

- user-owned skills
- extension-provided skills
- future explicitly published shared skills, if the product still wants that
  concept

This means the schema and runtime should eventually remove special handling for:

- builtin skill discovery
- builtin skill source labels
- builtin skill visibility branches

## Migration Direction

The current codebase still contains many direct path assumptions. The long-term
design should move these concerns behind storage services.

High-priority migration targets:

- `FileAsset.storage_path`
- `FileAsset.markdown_path`
- `TaskAttachment.storage_path`
- `Skill.location`
- `ExtensionInstallation.install_root`
- APIs that directly return `FileResponse(path=...)`

The service layer should eventually own:

- logical path resolution
- object access
- temporary local file creation when absolutely required
- workspace path resolution for sandbox mounts

## Execution Plan

The implementation should proceed in phases rather than as one large rewrite.

### Phase 1: Lock The Storage Contract

Goal:

- freeze the architectural contract before code migration starts

Work:

- finalize the logical namespace documented in this file
- finalize the `storage profile` concept
- finalize the rule that fallback means a full profile switch
- finalize the rule that `skills` and `extensions` use `ObjectStorage` as
  canonical source of truth
- finalize the rule that `POSIXWorkspace` owns workspace bodies

Done when:

- this draft is stable enough to guide implementation
- no core terminology remains ambiguous

### Phase 2: Introduce Storage Abstractions In Code

Goal:

- stop letting service code depend directly on ad-hoc filesystem rules

Work:

- add `server/app/storage/` package
- add `ObjectStorageProvider` and `POSIXWorkspaceProvider` interfaces
- add `storage profile` resolver
- add first implementation pair for `local_fs`
- route storage resolution through service-layer helpers rather than direct
  `Path` construction where practical

Done when:

- new storage-facing code can depend on provider interfaces
- `local_fs` works through the same abstraction layer that future external
  providers will use

### Phase 3: Normalize Local Storage Layout

Goal:

- make `local_fs` look like the external namespace contract

Work:

- move local source-of-truth storage under `/server/data/storage/`
- align local logical paths with the shared namespace contract
- ensure `local_fs` object keys and workspace paths match the same logical
  prefixes used by external providers
- reserve `/server/data/.local_cache/` for temporary files only

Done when:

- local workspace and local object artifacts follow the same logical naming
  scheme expected from external providers
- `local_fs` is a true provider implementation rather than a one-off layout

### Phase 4: Convert Attachments To Live References

Goal:

- remove snapshot semantics from assistant-generated attachments

Work:

- replace snapshot-oriented attachment persistence with live workspace
  references
- store workspace identity and workspace-relative paths instead of snapshot file
  paths
- update attachment serving APIs to resolve the current workspace file via the
  service layer
- remove snapshot-specific storage logic where it is no longer needed

Done when:

- assistant attachments resolve to live files under the active workspace
- no new snapshot copies are created for task attachments

### Phase 5: Remove Builtin Skill Special Cases

Goal:

- simplify the skill model before externalizing it further

Work:

- remove builtin skill discovery from the target runtime path
- remove builtin-specific schema and branching
- keep user and extension-provided skills only
- update runtime skill visibility and prompt assembly code accordingly

Done when:

- builtin skill concepts no longer shape the runtime storage design
- skill resolution is based on creator-owned and extension-provided assets only

### Phase 6: Move Skills And Extensions To Canonical ObjectStorage

Goal:

- make skills and extensions truly artifact-backed

Work:

- make extension artifacts canonical in `ObjectStorage`
- make skill artifacts canonical in `ObjectStorage`
- keep `/workspace/skills` as a runtime-injected view rather than canonical
  storage
- load extension runtime assets on demand
- prepare allowlisted skills only when sandbox is created or refreshed

Done when:

- `skills` and `extensions` no longer rely on host-local source directories as
  their canonical source of truth
- runtime loading uses object-backed artifacts through the service layer

### Phase 7: Refactor Workspace Routing To POSIX Providers

Goal:

- isolate workspace lifecycle from raw path-building helpers

Work:

- route workspace creation, deletion, and path resolution through the
  `POSIXWorkspaceProvider`
- teach sandbox-manager to consume provider-resolved workspace roots
- preserve the single-workspace `/workspace` mount model
- keep skills runtime exposure allowlist-based

Done when:

- workspace ownership and sandbox mounting are provider-driven
- service code no longer treats raw local directories as the only workspace
  model

### Phase 8: Add External SeaweedFS Profile

Goal:

- add the first serious external storage profile

Work:

- add `seaweedfs` services to the repository `compose.yaml`
- gate them behind a `seaweedfs` compose profile
- implement external object-storage access for SeaweedFS
- implement external `POSIXWorkspace` resolution for SeaweedFS-backed
  workspaces
- add startup health checks and prominent fallback warnings

Done when:

- `podman compose --profile seaweedfs up` can boot Pivot plus SeaweedFS
- Pivot cleanly falls back to `local_fs` when the external profile is not
  healthy

### Phase 9: Platform Validation

Goal:

- validate the intended development matrix honestly

Work:

- validate `local_fs` default path on macOS, Windows, and Linux
- validate external `seaweedfs` profile on Linux
- validate external `seaweedfs` profile on macOS
- validate and document Windows limitations for external `POSIXWorkspace`
- make sure docs clearly distinguish supported, experimental, and fallback-only
  paths
- keep the developer startup contract fixed to compose only
- do not reintroduce extra startup wrappers such as `dev-up.sh`

Done when:

- the platform matrix is documented from real validation instead of inference

Current working matrix:

- macOS:
  - `podman compose up` is a supported default path
  - `podman compose --profile seaweedfs up -d` is a supported service startup
    path
  - external POSIX entrypoint preparation remains operator-prepared and must be
    validated on real machines
- Linux:
  - `podman compose up` is a supported default path
  - `podman compose --profile seaweedfs up -d` is a supported service startup
    path
  - external POSIX entrypoint preparation is the main remaining validation item
- Windows:
  - `podman compose up` is the supported default path
  - `local_fs` is the intended normal development mode
  - external POSIX workspace routing remains explicitly outside the normal
    supported path for now

Phase 9 validation checklist:

1. Confirm default fallback path.
   - Run `podman compose up`.
   - Expect `/api/system/storage-status` to report:
     - `requested_profile=auto`
     - `active_profile=local_fs`

2. Confirm service-only SeaweedFS startup.
   - Run `podman compose --profile seaweedfs up -d`.
   - Expect filer explorer to be reachable at `http://localhost:8888`.
   - Expect Pivot to stay on `local_fs` unless the external POSIX entrypoint is
     already prepared.

3. Confirm POSIX visibility state.
   - Check `/api/system/storage-status`.
   - Record:
     - `external_posix_root`
     - `external_posix_root_exists`
   - If `external_posix_root_exists=false`, the host-visible entrypoint is not
     ready yet.

4. Confirm namespace bridge state.
   - If `external_posix_root_exists=true` but `active_profile=local_fs`, record
     that the path exists but is not exposing the same namespace as the filer.
   - This is the exact state currently observed in repository validation.

5. Confirm full external activation only after real POSIX bridge exists.
   - Only treat the external profile as validated when:
     - `active_profile=seaweedfs`
     - `object_storage_backend=seaweedfs`
     - `posix_workspace_backend=mounted_posix`

Phase 9 constraint:

- The supported validation entrypoints remain:
  - `podman compose up`
  - `podman compose --profile seaweedfs up -d`
- Do not add another wrapper script for development startup.

### Phase 10: Cleanup And Hardening

Goal:

- remove obsolete storage assumptions and stabilize the new design

Work:

- remove dead compatibility paths that are no longer part of the chosen model
- reduce direct `FileResponse(path=...)` style path leakage where possible
- centralize temporary-file handling rules
- add or update tests for provider fallback, workspace routing, live
  attachments, skill injection, and external profile startup

Done when:

- the storage design is enforced consistently across services
- storage behavior is testable and documented

## Remaining Open Questions

The following items still need product and implementation decisions.

### 1. Windows external POSIX validation

We still need to validate whether the external `POSIXWorkspace` path can be made
reliable on Windows in the actual Pivot + Podman development environment.

This is the biggest open cross-platform question.

### 2. Exact SeaweedFS integration shape

We still need to decide whether the first `seaweedfs` profile should use:

- SeaweedFS object API plus host-mounted external POSIX path
- or another equivalent routing shape that still preserves the same security
  boundary

The design currently leans toward:

- object API for object storage
- mounted host path for `POSIXWorkspace`

### 3. Temporary file policy

We still need one exact implementation rule for unavoidable temporary files:

- in-memory only when possible
- `/server/data/.local_cache/` when a real path is required
- the old `/server/data/seaweedfs/` repo directory is retired; SeaweedFS
  container state now lives in the compose named volume `seaweedfs-data`

The remaining work is to define which services are allowed to create these
temporary files and how they are cleaned up.

### 4. Final live-reference schema details

The product decision is now settled:

- attachments are live references
- snapshot copies should be removed from the target design

What still remains open is the exact final schema shape and migration plan.

Current direction:

- store workspace identity
- store workspace-relative path
- stop storing snapshot copy path

## Current Working Answer To The Main Product Questions

### Can external storage start across macOS, Windows, and Linux?

Most likely yes for the storage service itself.

But no, we should not yet promise that the full external `POSIXWorkspace`
integration path is equally frictionless on every host OS. That part still
needs validation, especially on Windows.

### Can Pivot still keep a one-command startup?

Yes.

The correct contract is:

- `podman compose up` always starts Pivot
- external provider is optional
- external provider services may live in the same repository and same
  `compose.yaml`, but should be activated via profile
- if external provider is absent or broken, Pivot falls back to `local_fs`

That preserves the desired DX.

### Are skills and extensions canonically stored in ObjectStorage?

Yes.

Current consensus:

- `skills` and `extensions` should both use `ObjectStorage` as their canonical
  source of truth
- runtime loading should fetch or derive only what is needed
- `/workspace/skills` and extension runtime load paths are derived runtime
  views, not the canonical source

## Sources

- SeaweedFS official repository:
  https://github.com/seaweedfs/seaweedfs
- SeaweedFS operator repository:
  https://github.com/seaweedfs/seaweedfs-operator
- SeaweedFS README currently describes:
  - filer server with normal directories and files via HTTP
  - POSIX FUSE mount support
  - S3 API access
  - WebDAV mapped-drive access on macOS and Windows
