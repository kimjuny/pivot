# Pivot Mem0 Extension

This package is imported into Pivot and bound to one or more agents.

It does not import the `mem0` Python SDK directly. Instead, it calls an
external HTTP service so Pivot stays hot-pluggable and its server container
environment remains unchanged.

## Scope

This example is designed to be easy to start locally:

- the extension stays lightweight and only calls HTTP
- the companion Mem0 service is a single-instance deployment by default
- high availability and horizontal scaling are intentionally out of scope for
  this example

If you need a production-grade Mem0 deployment, treat this package as the Pivot
integration layer and deploy your memory service separately with your own
replicas, ingress, and storage operations.

## What It Does

- `task.before_start`
  Recalls memory from the external service and injects it into the task
  bootstrap prompt.
- `task.completed`
  Builds a memory candidate from the finished task and sends it to the external
  service when `execution_mode` is `live`.

## Quick Start

Follow these steps after downloading this extension package.

### 1. Import the extension into Pivot

Import the `extension/` folder through Pivot's Extensions UI.

### 2. Start the companion Mem0 service

This extension needs the external service in `../service`.

If you downloaded this extension from a repository or market listing, make sure
you also download the companion service files:

- [extensions/mem0/service](https://github.com/kimjuny/pivot/tree/main/extensions/mem0/service)

Then follow that service README to:

1. copy `.env.example` to `.env`
2. fill in your Mem0 LLM and embedder configuration
3. start the service with Podman Compose

The provided compose file publishes the service on host port `8765` by default.

### 3. Configure the extension in Pivot

Open the extension detail page in Pivot, go to the `Setup` tab, and fill
`Mem0 Server URL`.

Use one of these values depending on how Pivot itself is running:

- `http://host.containers.internal:8765`
  when Pivot backend runs inside a container and the Mem0 service is published
  on your host machine with the provided compose file
- `http://localhost:8765`
  when Pivot backend itself runs directly on your host machine

### Why `localhost` often fails

If Pivot backend runs in a container, `localhost` points to the backend
container itself, not to your host machine. In that setup, the default local
Mem0 service address should be:

- `http://host.containers.internal:8765`

If you changed the host port in the service compose file, keep the same host
name but replace `8765` with your custom published port.

### 4. Bind the extension to an agent

Open `Agent Detail`, add this extension in the sidebar, then either:

- use `Test Session` to verify memory recall and persistence immediately
- or `Publish` and test it in the app session path

## Runtime Isolation

This sample derives one logical memory namespace from both the current user and
agent at runtime:

- `user:{user_id}:{username}:agent:{agent_id}`

That namespace is sent to the external service on every recall and persist
request. Setup only configures where the service lives; it does not hard-code
the namespace.

## Expected Verification

Once everything is configured:

- a completed task should send one memory candidate to the external service
- a later task with the same `user + agent` pair should recall related memory
- hook logs in Pivot should show `memory_recalled` or `memory_persisted`
  observation events
