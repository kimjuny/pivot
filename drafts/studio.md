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
- Progressive disclosure over forced workflow.
- Shared assets and per-agent assembly must stay clearly separated.
- Draft and published states must be explicit.
- Studio-only runtime diagnostics must never leak into the end-user product.
- The primary workflow is create -> configure -> test -> release -> operate.
- Studio structure can express the full lifecycle, but interaction should stay
  lightweight and IDE-like rather than wizard-like.

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
- Agent workspace
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
- Current direct entries: `Channels`, `Web Search`
- Planned direct entries: `Desktop Connectors`,
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

The agent builder should not become a step-by-step wizard. The current and
recommended direction is a single-page agent workspace with lightweight global
actions and optional modules.

### Current Interaction Model

Creation flow:
- User starts from `Agents`
- Clicks `New`
- Completes a lightweight modal
- Minimal requirement is effectively `name + primary LLM`
- Agent is created immediately and opened in the agent workspace

Why this model is correct:
- A beginner can create a usable agent with very little upfront knowledge
- Configuration and refinement stay decoupled
- Advanced capabilities are optional rather than blocking

### Agent Workspace

The current workspace is a single-page Studio surface rather than a multi-page
builder.

Layout:
- Left sidebar for agent modules
- Central tabbed work area
- Floating action cluster anchored at the top-right of the main work area

The action cluster contains:
- `Discard`
- `Save`
- `Test`
- `History`
- `Publish`

This is intentionally lighter than a full-width toolbar. The workspace should
feel like an IDE, not a form wizard.

### Sidebar Semantics

The sidebar preserves the familiar resource entry points, but adds clearer
product semantics through grouping.

Current grouping:
- `Workflow`
  - `Scenes`
- `Capabilities`
  - `Tools`
  - `Skills`
- `Connections`
  - `Channels`
  - `Web Search`

Important:
- These are not required steps
- They are optional modules inside one agent workspace
- There is currently no dedicated `Overview` entry in the sidebar

This is deliberate:
- Basic agent identity and runtime settings are still edited through the agent
  modal
- A separate `Overview` page would duplicate information without creating a
  stronger workflow

### Basics and Runtime

Basic agent configuration is still modal-driven.

Current editable basics:
- Name
- Description
- Primary model
- Skill resolution model
- Session idle timeout
- Sandbox timeout
- Compact threshold
- Active state

These settings participate in the agent draft and release model even though
they are edited through a modal instead of a dedicated page.

### Workflow

Purpose:
- Define the business flow and scene logic for the agent.

Current workspace behavior:
- Scene graph remains the primary editing surface
- Multiple scenes remain visible as sidebar items and content tabs
- Scene editing is part of the main single-page workspace

### Capabilities

Purpose:
- Define what the agent can do.

Current capabilities:
- Tool allowlist
- Skill allowlist

Current interaction:
- Tool and skill selection is edited inside the agent workspace
- These changes are staged into the current draft instead of bypassing draft
  state

### Connections

Purpose:
- Define where the agent can receive requests from and what external retrieval
  surfaces it can use.

Current connections:
- Channel bindings
- Web search provider bindings

Rule:
- Channel catalogs and web search catalogs are shared Studio inventory
- Agent-level bindings are part of the agent assembly layer

### Test

Purpose:
- Validate the current draft before release.

Current interaction:
- `Test` is a global workspace action, not a sidebar step
- It opens the current draft test surface from the top-right action cluster
- The old sidebar footer entry for chat has been removed in favor of this
  clearer Studio action

### Drafts and Releases

Draft and release behavior is now a first-class part of the agent workspace.

Saved draft:
- Each agent has one current saved draft baseline
- `Save` overwrites that baseline
- There is no draft history list

Release:
- `Publish` creates an immutable release snapshot
- Release history is separate from save history
- The publish flow compares `saved draft` against `latest release`
- This comparison survives page reload because it is backed by persisted
  snapshots, not only frontend session state

Implementation note:
- The backend now stores normalized JSON snapshots for:
  - current saved draft
  - immutable published releases
- Publish summaries and release history are generated from these snapshots

### Publish UX

The publish flow should stay lightweight but auditable.

Current behavior:
- `Publish` opens a compact confirmation dialog
- The dialog shows:
  - release version transition
  - grouped change summary
  - optional release note
- If there are no differences from the latest release, the dialog explicitly
  shows `No changes`

Release history:
- Release history is no longer embedded inside the publish dialog
- It is accessed from a separate `History` action next to `Publish`
- Each release record shows:
  - version
  - timestamp
  - publisher
  - release note
  - grouped summary of changes

This separation is intentional:
- `Publish` is a risky confirmation flow
- `History` is an audit and review flow
- They should not compete for attention inside one dialog

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
- Current saved draft
- Release history

Studio should make it obvious whether the administrator is editing shared
inventory or one agent instance.

Additional rule:
- Shared asset content changes are not the same thing as agent draft changes
- Agent draft changes should be based on the agent's own assembled snapshot
- Channel templates are treated as stable catalogs; agent-level binding changes
  are what matter inside the agent workspace

## Suggested Administrator Roles

Start with three roles:

- `Workspace Admin`: manages shared assets, connections, members, and releases.
- `Agent Builder`: edits agents and uses the test console.
- `Operator`: observes runtime behavior, cost, and failures.

Do not over-design fine-grained RBAC in the first Studio iteration.

## MVP Integration Plan

Current Studio integration status:

Completed or largely established:
1. Top navigation has been restructured around the Studio modules.
2. Existing resources remain reachable through second-level navigation.
3. Agent work is centered in a single-page workspace instead of a forced
   multi-step builder.
4. `Test` and `Publish` are explicit global actions in the agent workspace.
5. Draft and release concepts now exist as real persisted backend concepts.

Next priorities:
1. Continue refining the agent workspace interaction model rather than
   replacing it with a page-per-step builder.
2. Improve release audit depth using more structured snapshot diffs.
3. Decide which runtime and basics fields should remain modal-driven versus
   becoming more visible in the workspace.
4. Prepare the Studio model so the future end-user product can consume stable
   published releases rather than mutable working state.
