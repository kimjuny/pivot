# Pivot Mem0 Extension

This package is imported into Pivot and bound to one or more agents.

It does not import the `mem0` Python SDK directly. Instead, it calls an
external HTTP service so Pivot stays hot-pluggable and its server container
environment remains unchanged.

## What It Does

- `task.before_start`
  Recalls memory from the external service and injects it into the task
  bootstrap prompt.
- `task.completed`
  Builds a memory candidate from the finished task and sends it to the external
  service when `execution_mode` is `live`.

## Required Setup

After importing the extension in Pivot:

1. Open the package detail page.
2. Go to the `Setup` tab.
3. Fill `Mem0 Server URL`.
4. Bind the extension to an agent.

## Local Development

Run the companion service from:

- [service](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/extensions/mem0/service)

The default local address used in examples is:

- `http://localhost:8765`

## Runtime Isolation

This sample derives one logical memory namespace from both the current user and
agent at runtime:

- `user:{user_id}:{username}:agent:{agent_id}`

That namespace is sent to the external service on every recall and persist
request. Setup only configures where the service lives; it does not hard-code
the namespace.
