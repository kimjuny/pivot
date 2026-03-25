# Pivot Studio

## Positioning

Pivot Studio is the administrator-facing control plane for building, testing,
publishing, and operating enterprise agents.

It is not only a resource console. It should help administrators move through a
clear lifecycle:

1. Prepare reusable assets and external connections.
2. Assemble one agent from those building blocks.
3. Validate the draft in a test console.
4. Publish a stable release.
5. Observe quality, risk, and cost over time.

## Product Principles

- Lifecycle-first, not resource-first.
- Shared assets and per-agent assembly must stay clearly separated.
- Draft and published states must be explicit.
- Studio-only runtime diagnostics must never leak into the end-user product.
- The primary workflow is configure -> test -> release -> operate.

## Top-Level Information Architecture

Studio should expose five top-level modules:

1. `Dashboard`
2. `Agents`
3. `Assets`
4. `Connections`
5. `Operations`

This structure replaces the current flat navigation where `LLMs`, `Tools`,
`Skills`, and `Channels` all compete at the same level.

Current implementation note:
- The five modules exist as top-level navigation categories.
- `Assets`, `Connections`, and `Operations` are currently expressed as
  top-level navigation groups with second-level entries.
- `Assets` and `Connections` do not have standalone aggregation pages in the
  current Studio build.
- `Operations` does not yet have a standalone page in the current Studio build.

## Module Responsibilities

### Dashboard

Purpose:
- Eventually provide a workspace-level overview of Studio activity.

Content:
- Current state: explicit "under construction" placeholder
- Future: recently active agents
- Future: drafts waiting for release
- Future: runtime failures and unhealthy integrations
- Future: usage and cost summaries

### Agents

Purpose:
- Serve as the primary entry point for agent creation and management.

Content:
- Agent list
- Agent builder
- Test console
- Release history
- Audience assignment

### Assets

Purpose:
- Manage reusable building blocks that can be attached to multiple agents.

Navigation:
- Top-level category with second-level destinations
- Current direct entries: `Models`, `Tools`, `Skills`
- Planned direct entries: `MCPs`, `Prompt Kits`

Content:
- Models
- Tools
- Skills
- Future: prompts, MCP servers, knowledge sources

Rule:
- Assets are shared inventory, not per-agent runtime instances.
- The current Studio build enters Assets through second-level navigation rather
  than a standalone Assets landing page.

### Connections

Purpose:
- Manage external reachability and external data access.

Navigation:
- Top-level category with second-level destinations
- Current direct entry: `Channels`
- Planned direct entries: `Web Search Providers`, `Desktop Connectors`,
  `Internal APIs`

Content:
- Channels
- Web search providers
- Future: desktop connectors, internal APIs, OAuth apps

Rule:
- Connections are reusable connection surfaces and templates.
- Agent-level binding details belong inside the agent builder.
- The current Studio build enters Connections through second-level navigation
  rather than a standalone Connections landing page.

### Operations

Purpose:
- Observe runtime quality, safety, and cost after deployment.

Navigation:
- Top-level category with second-level planned views
- No standalone Operations landing page in the current Studio build

Content:
- Session history
- Tool execution logs
- Release audit trail
- Usage and cost analytics
- Future: alerts and approval queues

## Agent Builder

The agent builder is the core Studio workspace. It should be structured as a
step-based product surface instead of a resource accordion.

Recommended sections:

1. `Overview`
2. `Workflow`
3. `Runtime`
4. `Capabilities`
5. `Connections`
6. `Test`
7. `Releases`

### Overview

Purpose:
- Define the business identity of the agent.

Content:
- Name
- Description
- Avatar
- Intended audience
- Welcome copy
- Draft or published status

### Workflow

Purpose:
- Define the business flow and scene logic for the agent.

Content:
- Scene graph
- Multi-scene or multi-workflow orchestration in the future

### Runtime

Purpose:
- Control model and execution behavior.

Content:
- Primary model
- Skill resolution model
- Thinking and cache policies
- Session idle timeout
- Context compact threshold
- Sandbox timeout

This is where the current advanced runtime configuration should become a
first-class page instead of staying buried inside a modal.

### Capabilities

Purpose:
- Define what the agent can do.

Content:
- Tool allowlist
- Skill allowlist
- Future MCP capability selection
- Dependency and permission visibility

### Connections

Purpose:
- Define where the agent can receive requests from and what external retrieval
  surfaces it can use.

Content:
- Channel bindings
- Web search bindings
- Future desktop and local-device connectors

### Test

Purpose:
- Validate the draft agent before publishing.

Content:
- Chat playground
- Tool traces
- Runtime compaction status
- Plan and recursion traces

The existing chat runtime surface should become the Studio test console, with
draft status made explicit.

### Releases

Purpose:
- Turn a draft into a stable, auditable deliverable.

Content:
- Draft vs published diff
- Release notes
- Publish
- Rollback
- Assignment visibility

## Asset Layer vs Agent Layer

This distinction is critical.

Global assets:
- LLM configurations
- Shared tools
- Shared skills
- Channel catalogs
- Web search catalogs
- Future secrets and policies

Agent-specific assembly:
- Selected runtime model
- Enabled tools and skills
- Bound channels and search providers
- Workflow and runtime settings
- Release history

Studio should make it obvious whether the administrator is editing shared
inventory or one agent instance.

## Suggested Administrator Roles

Start with three roles:

- `Workspace Admin`: manages shared assets, connections, members, and releases.
- `Agent Builder`: edits agents and uses the test console.
- `Operator`: observes runtime behavior, cost, and failures.

Do not over-design fine-grained RBAC in the first Studio iteration.

## MVP Integration Plan

For the first Studio integration pass:

1. Restructure the top navigation into the five top-level modules.
2. Route concrete resources through second-level navigation instead of adding
   aggregation pages for every module.
3. Keep existing resource pages reachable under `Assets` and `Connections`.
4. Promote the existing chat runtime into a formal `Test Console`.
5. Introduce draft and release concepts before building the end-user product.

This gives Pivot a coherent Studio identity without forcing a full rewrite of
all existing pages in one step.
