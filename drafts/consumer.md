# Pivot Consumer

## Positioning

Pivot Consumer is the end-user product for discovering, opening, and using
published enterprise agents.

It is not a reduced copy of Studio.

Studio exists for administrators to build, test, publish, and operate agents.
Consumer exists for end users to use stable released agents with minimal setup.

## Relationship to Studio

Studio and Consumer should live in the same product family, but they should not
share the same page structure or API contract.

They should follow this rule:

- Separate by audience at the shell, route, and API-contract layers.
- Share by domain at the chat-runtime, session, and service layers.

This means:

- Consumer should not directly reuse Studio pages.
- Consumer should not directly depend on Studio-oriented API semantics such as
  draft editing or publishing.
- Consumer should reuse the existing ReAct chat runtime and session system.
- Consumer and Studio Test should stay experience-aligned by sharing the same
  chat core.

## Product Principles

- Release-first, not draft-first.
- End users should see only what is ready to serve.
- The first Consumer version should prefer reuse over reinvention.
- One conversation session belongs to exactly one agent and one release.
- Studio-only diagnostics must stay outside the Consumer shell by default.
- Consumer should open directly into work, not into a dashboard detour.
- Shared code should be extracted into explicit cross-audience modules rather
  than copied between Studio and Consumer.

## MVP Product Direction

The first Consumer version should intentionally reuse the existing Studio Test
chat experience.

Why this is correct:

- The current ReAct chat flow is already the most mature interactive surface in
  the product.
- Rebuilding it for Consumer would create unnecessary behavior drift and a high
  regression risk.
- Matching the Consumer chat to the Studio Test chat makes draft validation
  more meaningful.

Important nuance:

- Reuse does not mean Consumer should render the same page container as Studio.
- Consumer should reuse the chat core and session behavior while using its own
  routes, layouts, and API-facing contracts.

## Current Consumer Information Architecture

The current Consumer MVP intentionally has only three user-facing surfaces:

1. `Entry`
2. `Agents`
3. `Chat Workspace`

### Entry

Purpose:

- Restore the user into work as quickly as possible.

Current behavior:

- `/app` immediately checks the latest Consumer session for the signed-in user
- If a recent Consumer session exists, the user is redirected straight into that
  agent chat workspace
- If no Consumer session exists yet, the user is redirected to the agent list
- Loading should render only a centered spinner, without cards or explanatory
  copy

### Agents

Purpose:

- Provide the only current browsing surface in Consumer.

Current behavior:

- Show all Consumer-visible agents
- Reuse the same sidebar frame as the chat workspace
- Keep navigation minimal; `Agents` is the only top-level navigation entry in
  the current MVP

### Chat Workspace

Purpose:

- Be the product itself.

Current behavior:

- Render the shared ReAct chat surface full screen
- Keep the chat area uncompressed instead of embedding it inside a dashboard
  card layout
- Reuse the session sidebar for recent sessions and agent switching entry
- Hide Studio-only runtime diagnostics by default

## Session Model

Consumer should support a unified recent-session list across agents.

This means:

- A single user can see recent sessions created from multiple agents.
- Each session row still belongs to exactly one agent.
- Opening a session returns the user to that specific agent conversation.

This does not mean:

- One session can switch between multiple agents.
- One session can silently change to a different release.

Core session rules:

- A session is bound to one `agent_id`.
- A session is bound to one `release_id` at creation time.
- A session never switches release in the middle of a conversation.
- A disabled agent should not accept new sessions.
- Existing session history may remain visible even when interaction is disabled.

Session typing:

- Consumer sessions use `session.type = consumer`
- Studio validation sessions use `session.type = studio_test`
- App surfaces must filter to `consumer` sessions only
- Studio Test must filter to `studio_test` sessions only
- A `studio_test` session appearing in Consumer is a bug, not a supported state

## Authentication and Roles

Consumer and Studio should share one user system and one authentication system.

Future access should be role-driven rather than product-driven.

Example future role outcomes:

- Some users can access only Consumer.
- Some users can access both Consumer and Studio.
- Some users may later gain Studio sub-roles such as Builder or Operator.

Implication for architecture:

- Do not build a separate login stack for Consumer.
- Do not encode Studio-only assumptions into the global auth model.

## Frontend Architecture

The current MVP keeps the audience split lightweight instead of introducing a
large new folder system.

Current structure:

```text
web/src/
  consumer/
    ConsumerEntryPage.tsx
    ConsumerAgentsPage.tsx
    ConsumerAgentPage.tsx
    ConsumerUserMenu.tsx
    api.ts

  pages/chat/
    ChatContainer.tsx
    ChatPage.tsx
    components/

  components/
    ReactChatInterface.tsx
```

Current boundary rule:

- `web/src/consumer/*` owns Consumer-specific routes and shell decisions
- `web/src/pages/chat/*` and `ReactChatInterface.tsx` remain the shared chat
  runtime UI used by both Studio Test and Consumer
- This keeps reuse high without introducing a premature large-scale directory
  migration

### Chat Shell Strategy

The current `ReactChatInterface.tsx` is close to a shared shell, but it still
contains audience-specific switches.

Current behavior:

- Consumer reuses the same `ReactChatInterface.tsx` and chat runtime as Studio
  Test
- Consumer passes `showCompactDebug = false` so Studio-only diagnostics stay
  hidden
- Consumer routes now present that chat core as a full-screen workspace rather
  than embedding it inside an extra page shell

### Routing Strategy

Consumer should have its own route namespace.

Recommended route split:

- `/studio/*` for administrator-facing surfaces
- `/app/*` for end-user-facing surfaces

Initial Consumer route examples:

- `/app`
- `/app/agents`
- `/app/agents/:agentId`

Important:

- Do not keep using Studio-oriented legacy routes such as `/agent/:agentId`
  for Consumer expansion.
- The current MVP does not need a separate `/app/home` surface.

## Frontend API Layer

The current MVP keeps the split similarly lightweight.

Current structure:

- `web/src/consumer/api.ts` for Consumer-specific list/detail/session entry
  calls
- `web/src/utils/api.ts` for the shared chat/session/task runtime

Current rule:

- Consumer-specific browsing surfaces should not call Studio-oriented endpoints
- Shared chat runtime calls can continue to live in the common API module while
  the product is still pre-launch

## Backend API Architecture

The current backend split is intentionally narrow.

Current audience-specific routes:

- `/api/consumer/agents`
- `/api/consumer/agents/{agent_id}`
- `/api/consumer/sessions`

Current rule:

- Consumer-specific browsing and recent-session entry points use explicit
  Consumer routes
- Shared chat runtime endpoints are still reused while honoring `session.type`
  and release/session boundaries under the hood

## Backend Service Architecture

Services should remain domain-oriented and reusable.

They should not be split into `studio_*` and `consumer_*` services unless the
domain truly differs.

Recommended domain-oriented service set:

- `agent_service.py`
- `agent_snapshot_service.py`
- `session_service.py`
- `react_runtime_service.py`
- `react_task_supervisor.py`
- `agent_release_runtime_service.py` as a new service

### Release Runtime Resolution

This service now exists as a first-class backend concept.

Current responsibility of `agent_release_runtime_service.py`:

- Load the published release snapshot referenced by `session.release_id`
- Resolve runtime fields needed for execution and context estimation
- Provide a stable released view of:
  - primary LLM
  - skill-resolution LLM
  - tool allowlist
  - skill allowlist
  - bindings and runtime settings

This service now bridges:

- Studio release snapshots
- Consumer serving behavior
- Session-level release pinning

## Current Consumer API Surface

Current routes used by the MVP:

- `GET /api/consumer/agents`
- `GET /api/consumer/agents/{agent_id}`
- `GET /api/consumer/sessions`

Shared chat runtime still uses the existing session/task endpoints, with these
rules enforced underneath:

- Consumer creates `session.type = consumer`
- Consumer sessions always bind `release_id`
- Consumer session list surfaces must filter to `consumer` only

## Current Implementation Notes

Completed or largely established:

1. Consumer uses its own `/app/*` route namespace.
2. `/app` restores the latest Consumer session instead of opening a Home page.
3. Consumer chat is now a full-screen workspace rather than a nested dashboard
   card.
4. Consumer loading states have been simplified to a centered spinner.
5. Consumer session lists are filtered by `session.type = consumer`.
6. Release-resolved runtime execution is in place for Consumer sessions.
7. Consumer continues to reuse the Studio Test chat core instead of forking a
   second chat implementation.

## Non-Goals for the First Consumer Version

- A separate authentication stack
- A brand-new chat implementation
- Multi-agent switching inside one conversation session
- Full assignment and audience targeting
- A separate Home/dashboard surface
- A fully independent design language from Studio

## Summary

The long-term structure should be:

- separate product shells for Studio and Consumer
- separate route namespaces
- separate API contracts
- shared chat core
- shared runtime engine
- shared domain services
- release-resolved execution for Consumer sessions

This gives Pivot a clean audience boundary without throwing away the most
mature part of the current product: the existing ReAct chat system.
