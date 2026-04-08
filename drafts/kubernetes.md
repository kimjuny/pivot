# Pivot Kubernetes Notes

This document tracks Kubernetes-specific architecture work around the shared
mount-root runtime. Local development now targets the same architectural shape,
but Kubernetes still has its own deployment and lifecycle concerns.

## 1. Filesystem runtime strategy

Local development no longer treats transitional attach paths as the desired end
state.

The current direction is:

- local development should also move toward a true shared mount root
- `server/workspace/` should not remain a duplicate live workspace tree
- platform-specific startup steps may be necessary and should be documented
  directly

## 2. Production / Kubernetes requirement

When we implement the Kubernetes production-grade filesystem runtime, we must
come back and finish the real **Option B** mount strategy.

That means:

- do **not** rely on container-private mounts inside `sandbox-manager`
- do **not** rely on mount propagation from `sandbox-manager` to sandbox pods as
  the primary design
- move to a node-level or dedicated trusted shared mount root
- let the runtime manager consume that prepared shared mount root

In practical Kubernetes terms, this likely means one of:

1. CSI-backed shared mount preparation
2. node-level trusted mount helper
3. another Kubernetes-native shared mount orchestration pattern with the same
   security properties

## 3. Explicit reminder

This remains a known gap, not an accident.

Even after local development moves to shared mount root, Kubernetes production
still needs an explicit implementation for:

- node-level mount ownership
- shared mount root lifecycle
- pod-level visibility and cleanup
- credential distribution and recovery

Before shipping a Kubernetes production version, we must explicitly revisit:

- SeaweedFS trusted attach ownership
- shared mount root lifecycle
- pod-level mount visibility
- cleanup and recovery behavior
- credential handling for the trusted mount owner
- sandbox isolation relative to the mount-capable control-plane component

## 4. Guiding principle

Local development and Kubernetes should converge on the same high-level mount
shape:

- trusted helper / node-level shared mount root
- sandbox consumes prepared workspace mounts

But Kubernetes still requires its own production-grade implementation details.
This should be treated as required follow-up work, not optional cleanup.
