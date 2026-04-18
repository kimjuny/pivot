# Pivot on Kubernetes

## Positioning

This note focuses on the long-term serving implications of surface extensions,
workspace preview, and publish flows when Pivot is deployed as a clustered
system rather than a single-node development setup.

The main architectural conclusion is:

- do not make raw port exposure the product contract
- do model preview and publish as separate resources

## Why raw port mapping is the wrong long-term abstraction

Local development often starts with a simple mental model:

- a sandbox runs a web server on `localhost:3000`
- Pivot opens that port in a preview iframe

This is acceptable as an implementation detail during local development, but it
does not scale as the public contract.

In Kubernetes, a sandbox preview may actually live behind:

- a pod IP and container port
- a sidecar
- a session-scoped service
- an internal gateway route
- a websocket-capable reverse proxy

So the product contract should not be "open port 3000". It should be "open a
Preview Endpoint".

## Preview Endpoint model

A `Preview Endpoint` is the right abstraction for session-scoped web rendering.

Suggested fields:

- `preview_id`
- `session_id`
- `sandbox_id`
- `transport`
- `target_port`
- `target_path`
- `state`
- `proxy_url`
- `created_at`
- `expires_at`

The important field for the surface is:

- `proxy_url`

The surface should consume a Pivot-managed URL and should not need to know
where the preview is actually running.

## Preview Gateway

Pivot should own a preview gateway layer.

Responsibilities:

- resolve a preview record to a concrete runtime target
- proxy HTTP traffic
- proxy websocket traffic
- enforce session-scoped authorization
- hide cluster topology from the surface runtime

This lets the same surface contract work across:

- local development
- containerized single-node deployment
- Kubernetes clusters

## Kubernetes routing model

In Kubernetes, the preview gateway should rely on service discovery and
internal routing rather than host-level port publishing.

Recommended direction:

- sandbox manager knows which pod or runtime owns the session
- preview gateway resolves `preview_id` to that runtime
- gateway proxies to the correct pod/service target

Avoid designing around:

- `hostPort`
- `NodePort`
- host-network assumptions

Those approaches are operational shortcuts, not good platform contracts.

## Session preview vs production publish

Session preview and production publish must be different lifecycles.

### Session preview

- temporary
- session-scoped
- tied to sandbox lifetime
- intended for development and validation

### Production publish

- durable
- release-scoped
- independently addressable
- intended for real external traffic

Do not turn a session preview server into the production deployment model.

## Publish pipeline

Production publish should use a dedicated pipeline and worker model.

Suggested lifecycle:

1. collect source or build input from the workspace
2. create a `Publish Job`
3. hand off the job to a dedicated worker
4. build release artifacts
5. copy artifacts into a production-oriented serving space
6. create a deployment record and public URL

This allows production traffic to scale independently from chat sandboxes.

Suggested concepts:

- `Publish Job`
- `Release Artifact`
- `Deployment Target`
- `Published URL`

## Workspace editor implications

`workspace-editor` should eventually support two browser-oriented targets:

- a preview URL for the active session
- a published deployment URL for release inspection

But it should never need to understand:

- pod addresses
- container ports
- host routing
- cluster topology

Its contract should remain:

- Pivot gives me a URL
- I render it in `web` view

## Recommended product contract

At the user and surface level:

- `Preview Endpoint` for session-scoped web preview
- `Published Deployment` for release-grade serving

At the infrastructure level:

- Preview Gateway for sandbox-backed preview
- Publish Worker for build-and-release handoff

This keeps local development simple while preserving a clean path to
multi-node, production-grade deployment.
