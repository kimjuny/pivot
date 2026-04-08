# Pivot Filesystem Pending Decisions: SeaweedFS Route

This document tracks the remaining architecture decisions that are not fully
implemented yet in the SeaweedFS migration.

## 1. Trusted Attach Strategy

### Current direction

We currently prefer **Option B**.

That means:

- the real SeaweedFS mount should not live only inside the private mount
  namespace of `sandbox-manager`
- `sandbox-manager` should consume a shared mount root that is already visible
  outside its own container-private mount namespace
- sandbox containers should continue to receive only a prepared `/workspace`
  bind mount

### Why Option B is preferred

The main reason is not code style. It is runtime correctness and security.

Option B reduces dependence on mount propagation behavior across:

- the `sandbox-manager` container
- the Podman runtime
- the sandbox containers
- macOS `podman machine` or other nested container environments

This aligns better with the project's security goals:

- untrusted sandbox containers should not receive FUSE privileges
- untrusted sandbox containers should not receive SeaweedFS credentials
- trusted mount ownership should stay outside the untrusted runtime

### Important clarification

`trusted helper` does **not** necessarily mean "one more container".

It means:

- one trusted role owns the real mount
- that role is allowed to hold the extra privileges and credentials
- sandbox containers are not

This can be implemented in two deployment shapes:

1. one extra dedicated mount-helper container or node agent
2. a host or Podman-machine level shared mount root that `sandbox-manager`
   consumes

So the real distinction is:

- **Option A**: mount happens inside `sandbox-manager`
- **Option B**: mount happens outside `sandbox-manager`, and manager only
  consumes the prepared shared mount root

## 2. What remains unresolved in Option B

We have chosen the direction, but not the final implementation shape.

The unresolved sub-decision is:

### B1. Dedicated mount-helper process/container

Shape:

- one separate trusted helper owns the real SeaweedFS mount
- `sandbox-manager` binds subdirectories from that shared mount root into
  sandboxes

Pros:

- very explicit boundary between orchestration and mount ownership
- easier to reason about later for Kubernetes or CSI-like evolution

Cons:

- more moving parts in local development
- one more component to supervise and debug

### B2. Node-level shared mount root without a separate helper container

Shape:

- the shared mount root is created outside `sandbox-manager`
- `sandbox-manager` still consumes it, but does not own the mount itself

Pros:

- avoids introducing another long-lived container into the app topology
- keeps `sandbox-manager` simpler at runtime

Cons:

- local bootstrap may become more environment-specific
- ownership and lifecycle can become less explicit if not documented carefully

## 3. Current implementation status

The codebase is **not** at final Option B yet.

What is already in place:

- `workspace` schema is storage-identity-based
- backend-to-manager contract uses `storage_backend + logical_path + mount_mode`
- `sandbox-manager` has a `WorkspaceRuntimeDriver` abstraction
- `SeaweedfsWorkspaceDriver` exists
- local compose already includes a SeaweedFS all-in-one service
- manager readiness already checks SeaweedFS filer reachability

What is still transitional:

- the actual `/workspace` attach path for `seaweedfs` still uses the phase-1
  compatibility bind route
- the final shared mount root strategy for Option B is not implemented yet
- the current local `compose_compat` cache is only a temporary local transport
  detail, not the intended long-term backend workspace-cache model

## 4. Pending decision to finalize next

The next implementation decision is no longer "B1 vs B2 for local development."
It is now firmly about how to realize true Option B for local development as
well:

- local development should also use shared mount root
- local development should no longer accept `server/workspace/` as a duplicate
  live workspace tree
- startup should be documented per-platform instead of assuming one universal
  helper script

## 5. Recommendation

Current recommendation:

- keep the high-level decision as **Option B**
- implement true shared mount root for local development too
- treat remaining `compose_compat` behavior as migration debt
- write explicit macOS / Windows / Linux startup instructions in `README.md`
  instead of introducing a Python-only bootstrap requirement

This keeps the runtime boundary explicit without forcing developers to install
an extra non-Podman toolchain.

## 6. Local environment findings

The current local environment already gives us one strong signal:

- Podman is running through `podman machine`
- the machine is `rootless`
- the current `sandbox-manager` mounts are `rprivate`
- the helper root volume currently resolves to a node-visible Podman volume
  mountpoint under:
  `/var/home/core/.local/share/containers/storage/volumes/pivot_seaweedfs_mount_root/_data`

### Implication

This makes one thing much clearer:

- mounting SeaweedFS inside `sandbox-manager` itself is unlikely to propagate
  reliably to sibling sandbox containers
- adding a second helper container **inside the same compose topology** does not
  magically solve that, because it would still face the same private mount
  namespace and propagation constraints unless it owns a node-level shared
  mount root

### Updated practical recommendation

For the current local Podman setup, the most realistic path now looks like:

- prefer **B2-style node-level shared mount root**
- treat the Podman volume mountpoint as the candidate shared-root anchor
- let `sandbox-manager` consume that prepared root rather than owning the
  actual SeaweedFS mount itself

In other words:

- **A** is risky because of propagation
- **B1 inside compose only** is not enough by itself
- **B2 node-level shared mount root** is the most credible local path
- the remaining work is making that local path practical across macOS,
  Windows, and Linux while keeping the developer dependency story Podman-first
