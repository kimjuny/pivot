# Pivot Surface Extensions

## Positioning

Surface extensions are visual extensions that can participate in the chat
workspace, especially the right-side workbench beside
`ReactChatInterface`-backed conversations.

They should not be treated as arbitrary frontend plugins that mutate Pivot's
React tree. Instead, Pivot should expose a controlled chat-surface host that can
load an extension-owned frontend application inside an isolated runtime and let
that application interact with the active workspace through service-mediated
APIs.

The target use cases include:

- A coding workspace with a source tree, editor, terminal-like diagnostics, and
  web preview.
- A canvas workspace similar to Lovart-style image and layout editing.
- A pixel-agent or visualization surface that renders the current agent's
  runtime state from task events or transcript files.

## Core Consensus

Surface extensions should build on the existing package-based extension system.
They should add a new contribution type instead of creating a separate plugin
registry.

The most important architectural distinction is:

- Surface code belongs to the extension package.
- Surface data belongs to the workspace.

For installed extensions, the visual application code should be versioned and
pinned with the extension package. The workspace should contain the files that
the surface renders and edits, such as source files, canvas JSON documents,
images, exports, or transcript JSONL files.

This keeps extension versioning, trust review, release pinning, and uninstall
behavior coherent while still letting the agent and the surface collaborate
through the same workspace files.

## Preview and Publish Model

Surface-hosted web preview should be treated as a first-class product concept,
but it should not be modeled as "open some localhost port directly inside the
surface".

The right abstraction is:

- `Preview Endpoint` for session-scoped development and validation
- `Published Deployment` for durable production hosting

This distinction matters because raw ports are only one possible
implementation detail. They work in local development, but they are not the
right long-term contract for clustered or gateway-based environments.

### Preview Endpoint

A preview endpoint is tied to the active chat session and sandbox lifecycle.

It is:

- Temporary
- Session-scoped
- Backed by a sandbox runtime
- Intended for iterative development and inspection
- Allowed to disappear when the sandbox disappears

The agent may still discover that a preview server is listening on a sandbox
port, but the public Pivot contract should convert that into a Pivot-owned
preview endpoint record and proxy URL.

### Published Deployment

A published deployment is a different resource.

It is:

- Release-scoped
- Durable
- Independently addressable
- Backed by a production serving target
- Not coupled to the chat session's sandbox lifetime

Preview and publish should therefore use different data models, different job
lifecycles, and different serving assumptions.

## Non-Goals

- Do not let extension code directly mutate Pivot Web's internal React state.
- Do not require surface authors to understand Pivot's iframe bootstrap or
  postMessage details.
- Do not expose raw POSIX paths or browser filesystem access as the primary
  persistence contract.
- Do not make framework-specific SDKs the foundation of the system.
- Do not make development mode bypass the surface permission model entirely.

## Product Principles

- Workspace files are the business-state source of truth.
- Installed surface code is package-pinned, not workspace-mutated.
- Persistence must remain service-mediated.
- The host owns layout, lifecycle, permissions, and shell controls.
- The surface owns its own UI and domain rendering.
- Developer experience should feel like normal frontend development.
- Production security can be complex internally, but the public authoring API
  must stay simple.
- Development mode may simplify bootstrap, but should not erase the underlying
  authorization model.

## Manifest Contribution

Add a `chat_surfaces` contribution section under `manifest.json`.

Example:

```json
{
  "schema_version": 1,
  "scope": "acme",
  "name": "workspace-tools",
  "display_name": "ACME Workspace Tools",
  "version": "0.1.0",
  "api_version": "1.x",
  "contributions": {
    "chat_surfaces": [
      {
        "key": "workspace-editor",
        "display_name": "Workspace Editor",
        "description": "A source tree, code editor, and preview surface.",
        "entrypoint": "ui/workspace/index.html",
        "placement": "right_dock",
        "preferred_width": 720,
        "min_width": 420,
        "capabilities": [
          "workspace.read",
          "workspace.write",
          "workspace.watch",
          "task.events.read",
          "shell.controls"
        ],
        "allowed_path_prefixes": ["**"]
      }
    ]
  }
}
```

Recommended first milestone:

- Support `placement: "right_dock"` only.
- Support iframe-hosted surfaces only.
- Support package-local static entrypoints for installed extensions.
- Support dev-server proxied entrypoints for local development.
- Treat the right-side dock as the stable shell primitive and any standalone
  dock button as development-only UI.

## Runtime Model

The chat page should host a controlled workbench:

- Left side: existing session/project sidebar.
- Center: existing conversation and composer.
- Right side: extension dock.

The extension dock is responsible for:

- Opening and closing surfaces.
- Managing active tabs or one active surface.
- Managing width, resize, and collapsed state.
- Rendering development/installed badges.
- Creating the iframe runtime container.
- Providing shell-level communication to the surface.

The surface iframe is responsible for:

- Rendering its own UI.
- Calling surface-scoped APIs.
- Displaying and editing workspace-backed data.
- Subscribing to task events or workspace changes when allowed.

## Entry Model

The long-lived product primitive is the right-side dock, not a permanently
visible debug button labeled "Extension Dock".

Surface entry should use two coordinated paths:

- Official entry through surface icons in the chat header.
- Development entry through the existing chat debug affordance.

### Header Surface Icons

When the active agent has one or more enabled `chat_surfaces`, the chat header
should render a corresponding surface icon for each eligible surface.

Expected behavior:

- Icons appear only when the surface is installed and configured for the active
  agent.
- Clicking an icon opens the corresponding right-side dock surface.
- Clicking the active icon again may focus, collapse, or close the dock based
  on the final shell behavior, but the interaction should stay within the same
  dock model.
- The icon row is the primary user-facing entrypoint for installed surfaces.

This makes surface capabilities visible and directly controllable without
forcing the user to wait for an agent-triggered action.

### Debug Attach via the Existing Chat Debug Entry

For local development, Pivot should reuse the existing chat debug entry instead
of keeping a separate permanent "Extension Dock" button in the main UI.

The debug panel should expose a `Surface Dev` section that can:

- Accept a `surface_key`.
- Accept a `runtime_url`.
- Validate or ping the runtime.
- Attach a temporary development surface to the current chat context.

After a successful attach:

- Pivot should surface a temporary icon in the same chat-header icon area.
- That icon should use a visible development marker such as `DEV`.
- Clicking that icon should open the same right-side dock flow used by
  installed surfaces.

The debug entry should therefore register a temporary surface into the normal
host model rather than acting as a second standalone surface launcher.

### Temporary Development Scope

Development-attached surfaces should be scoped narrowly:

- Prefer current chat session scope first.
- Optionally fall back to current page lifetime scope.
- Do not make temporary debug-attached surfaces look identical to installed
  surfaces.
- Do not persist them as if they were fully installed extension bindings.

This keeps the mental model clear:

- Installed and agent-bound surfaces show up naturally in the chat header.
- Debug-attached surfaces are intentionally marked and temporary.
- Both still open through the same dock mechanism.

## Workspace-Native Data Model

The main data exchange channel between agents and surfaces should be workspace
files, not large postMessage payloads.

### Coding Surface

The coding surface should treat the active workspace as the project directory.

Example files:

```text
/workspace/
  package.json
  src/
  public/
  README.md
```

The agent can continue to use sandbox tools such as `list_files`, `read_file`,
`write_file`, `edit_file`, and `run_bash`. The surface should use
surface-scoped workspace APIs that internally call service-layer operations.

### Canvas Surface

A canvas surface can use a file-backed document model.

Example files:

```text
/workspace/.pivot/apps/canvas/
  document.json
  nodes/
    node-1.json
    node-2.json
  assets/
    image-1.png
    texture-1.webp
  exports/
    final.png
```

The surface renders the JSON and assets as an interactive canvas. The agent can
modify the same files to generate, arrange, or revise visual artifacts.

### Pixel Agent Surface

A pixel-agent surface has two useful data sources:

- Real-time task events for live animation.
- Workspace transcript files for replay, export, and recovery.

Example transcript path:

```text
/workspace/.pivot/transcripts/session.jsonl
```

The transcript is useful as a durable artifact, but it should not be the only
real-time channel. Pivot already has a reconnectable task-event stream, and the
surface should be able to subscribe to that stream when it has
`task.events.read`.

## Workspace Editor Web Preview

`workspace-editor` should evolve toward a dual-view coding surface rather than
remaining only a source editor.

Recommended top-left view modes:

- `code`
  A source-tree and editor-focused view.
- `web`
  A browser-style preview view that renders the current session preview
  endpoint.

The first view-switch affordance can be lightweight:

- `chevrons-left-right` for source/code mode
- `globe` for web preview mode

The surface should not know how to expose ports directly. Instead, it should
receive a Pivot-managed preview URL and switch to `web` mode when that preview
becomes available.

### Why not expose raw sandbox ports directly to the surface

Direct port exposure has the wrong lifetime and scaling semantics:

- It leaks an implementation detail into the author contract.
- It assumes single-node or host-port style networking.
- It couples the surface to sandbox topology.
- It makes future clustered routing and publish flows harder to reason about.

So the preferred contract is:

- agent/tool discovers or requests a preview target
- Pivot creates a `Preview Endpoint`
- Pivot returns a `proxy_url`
- `workspace-editor` opens that `proxy_url` in `web` mode

The surface should consume preview URLs, not raw ports.

### Suggested Preview Tool Shape

The tool should not be "open port 3000 in the iframe". The tool should be
closer to:

```json
{
  "tool": "create_preview_endpoint",
  "port": 3000,
  "path": "/",
  "title": "App Preview"
}
```

Suggested result:

```json
{
  "preview_id": "pv_123",
  "proxy_url": "/api/previews/pv_123/",
  "surface": {
    "surface_key": "workspace-editor",
    "initial_view": "web"
  }
}
```

Then the host is responsible for:

- opening or focusing `workspace-editor`
- switching it to the `web` view
- passing the preview URL into the surface runtime

This keeps tool invocation, host behavior, and surface rendering cleanly
separated.

### Suggested Lifecycle

1. The agent launches or detects a web server inside the current sandbox.
2. The agent calls a preview tool that references a port and optional path.
3. Pivot validates the preview target against the current session sandbox.
4. Pivot creates a `Preview Endpoint` record and a stable `proxy_url`.
5. The host opens or focuses `workspace-editor`.
6. The host tells `workspace-editor` to switch into `web` mode.
7. `workspace-editor` renders the Pivot-managed `proxy_url`.

This gives the user a consistent chat-to-preview experience while keeping
networking details out of the surface author contract.

## Surface APIs

Surface iframes should not use the user's full Pivot auth token and should not
call broad internal APIs directly. They should call surface-scoped APIs with a
surface-scoped authorization context.

Recommended API groups:

```text
POST /api/chat-surfaces/sessions
GET  /api/chat-surfaces/sessions/{surface_session_id}/bootstrap
GET  /api/chat-surfaces/sessions/{surface_session_id}/files/tree
GET  /api/chat-surfaces/sessions/{surface_session_id}/files/content
PUT  /api/chat-surfaces/sessions/{surface_session_id}/files/content
POST /api/chat-surfaces/sessions/{surface_session_id}/files/directory
DELETE /api/chat-surfaces/sessions/{surface_session_id}/files/path
GET  /api/chat-surfaces/sessions/{surface_session_id}/files/watch
GET  /api/chat-surfaces/sessions/{surface_session_id}/events
```

These endpoints should enforce:

- Current user owns or may access the session and workspace.
- The agent has the extension enabled.
- The resolved session bundle includes the requested surface.
- The requested operation is included in the surface capabilities.
- The path stays inside the allowed prefixes.
- All filesystem access goes through a service such as `WorkspaceFileService`.

## Authorization Model

Opening a surface should create a narrow surface session.

Surface session metadata should include:

- Surface session id.
- User id or username.
- Agent id.
- Session id.
- Workspace id.
- Extension installation id.
- Package id and extension version.
- Surface key.
- Capabilities.
- Allowed path prefixes.
- Expiration timestamp.

Installed production surfaces can use a short-lived surface access token or a
server-side same-origin session. The exact transport is an implementation
detail, but the important product guarantee is that the iframe only receives a
surface-scoped capability set.

Avoid these production shortcuts:

- Do not pass the user's full auth token into the iframe.
- Do not put sensitive tokens in iframe URLs.
- Do not allow a surface to read arbitrary workspace paths unless its
  contribution declares that scope and the user has approved it.

## Bootstrap Model

The earlier low-level model was:

```text
surface -> parent: ready
parent -> server: create/get surface session
server -> parent: bootstrap
parent -> surface: bootstrap
surface -> server: surface API calls
```

This remains a valid internal protocol, but it should not be the author-facing
integration model.

For better developer experience, prefer server-injected bootstrap:

1. Parent chat host asks Pivot server to create a surface session.
2. Server returns a surface iframe URL.
3. Parent opens the iframe URL.
4. Server serves the runtime page and injects bootstrap data.
5. `@pivot/surface-core` reads the bootstrap data automatically.

Example injected global:

```html
<script>
  window.__PIVOT_SURFACE_BOOTSTRAP__ = {
    "mode": "installed",
    "surfaceSessionId": "surf_123",
    "apiBaseUrl": "/api/chat-surfaces/sessions/surf_123",
    "surfaceKey": "workspace-editor",
    "workspaceId": "workspace-1",
    "capabilities": ["workspace.read", "workspace.write"],
    "allowedPathPrefixes": ["**"]
  };
</script>
```

`postMessage` should still exist, but only for shell coordination such as:

- `surface.ready`
- `shell.setTitle`
- `shell.setBadge`
- `shell.requestResize`
- `surface.dirtyStateChanged`

It should not be the primary channel for file contents, large canvas documents,
or image assets.

## SDK Strategy

Pivot should provide one official framework-neutral SDK:

```text
@pivot/surface-core
```

Do not make framework-specific SDKs the foundation of the system. Official
React, Vue, Svelte, or vanilla experiences should be delivered through starter
templates, examples, and recipes rather than separate long-lived SDK packages.

Rationale:

- One SDK avoids framework maintenance sprawl.
- React/Vue/other framework integrations can evolve as templates.
- Surface authors can use any browser frontend stack.
- The core package remains focused on Pivot protocol stability.

`@pivot/surface-core` should provide:

- Bootstrap discovery.
- Context access.
- Surface-scoped fetch.
- Workspace file primitives.
- Task-event subscription primitives.
- Shell-control primitives.

Example:

```ts
import { createSurface } from "@pivot/surface-core";

const surface = await createSurface();

surface.shell.setTitle("Workspace Editor");

const directory = await surface.workspace.listDirectory(".");
const file = await surface.workspace.readTextFile("src/App.tsx");
await surface.workspace.writeTextFile("src/App.tsx", file.content);
await surface.workspace.createDirectory("src/components");
await surface.workspace.deletePath("src/legacy");

surface.events.subscribe((event) => {
  console.log(event.type, event.data);
});
```

The SDK should also expose a raw request escape hatch:

```ts
await surface.fetch("/custom-endpoint", { method: "POST" });
```

This prevents every server-side API addition from requiring an immediate SDK
release.

## Publish Pipeline

Publishing should not be implemented as "keep the sandbox preview server alive
and call it production".

Instead, publishing should create a separate release lifecycle:

1. Build or collect deployable artifacts from the workspace
2. Persist those artifacts into a release-oriented storage location
3. Create a publish job or deployment record
4. Hand the work to a dedicated publish worker
5. Produce a durable production URL or deployment target

This separation is important because production traffic, concurrency, scaling,
and failure modes differ from a session-scoped sandbox preview.

Recommended building blocks:

- `Publish Job`
- `Release Artifact`
- `Deployment Target`
- `Published URL`

The `workspace-editor` `web` mode can later support both:

- session preview URLs
- published deployment URLs

But the underlying resources should remain distinct.

## Repository Responsibilities

Surface extensions span multiple repositories, but each repository should have
one clear responsibility.

### `/pivot/`

`/pivot/` is the platform runtime implementation repository.

It owns:

- Surface host behavior in Pivot Web.
- Surface dock layout and iframe lifecycle.
- Surface session creation and authorization.
- Surface-scoped workspace file APIs.
- Task-event APIs and stream exposure.
- Dev server proxy implementation.
- Manifest parsing and runtime bundle resolution.

In short, `/pivot/` is the protocol implementation side.

### `/extensions/`

`/extensions/` is the extension ecosystem and authoring repository.

It should own:

- Official extension samples and demos.
- Author SDKs and author tooling.
- Starter templates and example surfaces.
- The future extension hub frontend.

In short, `/extensions/` is the protocol consumer side and the developer
experience side.

### `/docs/`

`/docs/` remains the platform documentation site and primarily serves Pivot
users. Extension authoring guidance can be linked from there, but the primary
authoring assets should live with the extension ecosystem itself.

## SDK Placement

Because `@pivot/surface-core` is consumed by surface extensions rather than by
Pivot Web directly, the preferred early placement is inside `/extensions/`, not
inside `/pivot/`.

Recommended layout:

```text
/extensions/
  sdk/
    surface-core/
  extensions/
    workspace-editor/
    transcript-viewer/
  hub/
```

Rationale:

- Surface authors should find the SDK, samples, and hub assets in one place.
- Official surface extensions can dogfood `surface-core` directly.
- The SDK should be shaped by author workflows, not by Pivot internal
  implementation habits.
- Pivot Web does not need to depend on `surface-core`; it only needs the host
  runtime and a small shared protocol contract when necessary.

This repository split does not conflict with protocol coupling. Many extension
types are inherently coupled to Pivot runtime contracts, yet still belong in the
extension ecosystem repository rather than the platform runtime repository.

The practical division is:

- `/pivot/` defines and implements the runtime contract.
- `/extensions/` packages and validates the author-facing SDK and sample
  consumers of that contract.

## Framework Developer Experience

Pivot should provide high-quality templates instead of framework SDKs.

Recommended templates:

```text
create-pivot-surface --template vanilla
create-pivot-surface --template react-vite
create-pivot-surface --template vue-vite
```

React template behavior:

- Initialize `createSurface()` before rendering.
- Provide a small local context wrapper inside the template.
- Include example hooks such as `useWorkspaceFile` in template code, not in the
  core package.

Vue template behavior:

- Initialize `createSurface()` in app bootstrap.
- Provide/inject the surface client.
- Include example composables in template code, not in the core package.

This keeps official protocol support centralized while still giving framework
authors a comfortable starting point.

## Dev Server Proxy

The first development milestone should prioritize dev server proxy support.

The goal is:

1. A developer starts a normal frontend dev server, such as Vite.
2. Pivot Web registers that dev server as a development surface.
3. Pivot Server proxies the dev server through a Pivot-owned URL.
4. Pivot Server injects bootstrap into the HTML entrypoint.
5. The chat surface iframe loads the proxied URL.
6. Hot module replacement continues to work.

This gives developers normal frontend workflows without making them recreate
Pivot's parent iframe environment by hand.

### Recommended Author Flow

Developer commands:

```bash
cd my-surface
npm install
npm run dev
```

Pivot UI flow:

1. Open Surface Dev tools.
2. Click "Attach Dev Server".
3. Enter `http://127.0.0.1:5173`.
4. Enter a surface key and label.
5. Choose the target agent.
6. Choose a capability preset.
7. Optionally auto-open it in the current chat.

After registration, the chat host opens:

```text
/api/dev-surfaces/{dev_surface_id}/proxy/
```

Pivot Server proxies this to:

```text
http://127.0.0.1:5173/
```

### Dev Surface Registration

Suggested endpoint:

```text
POST /api/dev-surfaces
```

Request:

```json
{
  "agent_id": 1,
  "surface_key": "workspace-editor",
  "label": "Workspace Editor Dev",
  "dev_url": "http://127.0.0.1:5173",
  "capabilities": ["workspace.read", "workspace.write", "workspace.watch"],
  "allowed_path_prefixes": ["**"],
  "auto_open": true
}
```

Response:

```json
{
  "id": 42,
  "surface_key": "workspace-editor",
  "label": "Workspace Editor Dev",
  "proxy_url": "/api/dev-surfaces/42/proxy/",
  "status": "active"
}
```

### Proxy Behavior

The proxy should:

- Allow localhost dev URLs first.
- Validate that the current user owns the dev surface record.
- Proxy HTML, JavaScript, CSS, source maps, and static assets.
- Proxy HMR websocket traffic for Vite-compatible development.
- Rewrite or inject the HTML entrypoint with
  `window.__PIVOT_SURFACE_BOOTSTRAP__`.
- Mark the iframe visibly as a development surface.

First milestone should optimize for Vite dev servers. Other dev servers can be
treated as future compatibility work.

### Why Proxy Instead of Direct iframe to localhost

The proxy avoids forcing surface authors to solve:

- Cross-origin bootstrap.
- Token transport.
- Parent/iframe origin checks.
- HMR URL mismatches.
- API base URL configuration.

It also lets Pivot keep development and production loading behavior similar:
the surface still reads injected bootstrap and calls Pivot-owned APIs.

## Development Authorization

Development mode may simplify token handling, but should not remove the surface
authorization model.

Recommended approach:

- Dev server proxy is only enabled by explicit local configuration, such as
  `PIVOT_ENABLE_SURFACE_DEV_MODE=true`.
- Dev URLs are restricted to localhost in the first milestone.
- Dev surfaces are associated with the current authenticated user.
- Dev surfaces still declare capabilities and allowed path prefixes.
- The same surface-scoped API checks are used for dev and installed surfaces.

This lets developers avoid manual token plumbing while preventing dev mode from
becoming a completely different security model.

## Workspace-Hosted Surface Code

Running surface code directly from workspace files is possible, but should not
be the installed-extension model.

Problems:

- Surface executable code and document data become mixed.
- Agents could accidentally or intentionally mutate the UI runtime.
- Trust review and package signing become unclear.
- Version pinning and session replay become weaker.
- Web and Desktop behavior diverge.

Workspace-hosted code can be useful in future development workflows, but the
first milestone should focus on dev server proxy. Installed surfaces should keep
code in the extension package and data in the workspace.

## Desktop Direct Filesystem Access

Desktop direct filesystem access can be considered a future optimization, not
the core model.

Potential benefits:

- Lower latency for large workspaces.
- More native-feeling coding and canvas experiences.

Risks:

- Web and Desktop behavior diverge.
- Authorization shifts to the desktop shell capability model.
- Surface-specific path scoping becomes harder if all surfaces share one broad
  webview capability.

If implemented later, it should be an adapter behind `@pivot/surface-core`, not
an author-facing fork of the programming model.

## Recommended First Milestone

Build the smallest complete loop:

1. In `/pivot/`, add `chat_surfaces` manifest normalization and runtime bundle
   exposure.
2. In `/pivot/`, add the right-side `ExtensionDock` host in chat.
3. In `/pivot/`, add surface-session authorization and service-mediated
   workspace file APIs.
4. In `/pivot/`, add dev surface registration plus a Vite-oriented dev server
   proxy with bootstrap injection.
5. In `/extensions/sdk/`, create the first version of `surface-core`.
6. In `/extensions/extensions/`, create one sample React/Vite coding surface
   that consumes `surface-core`.
7. Use that sample surface to validate the full dev flow from "Attach Dev
   Server" to live iframe rendering in chat.
8. After the coding sample is stable, add one transcript or pixel-agent sample
   to validate task-event and transcript-driven rendering.

The implementation order should intentionally start with dev server support
before installed package polish. The first goal is to make local surface
development pleasant enough that protocol and SDK design can be iterated using a
real author workflow.

Do not build these in the first milestone:

- Multiple placement zones.
- Full marketplace review workflow for UI extensions.
- Desktop direct filesystem adapter.
- Official React/Vue SDK packages.
- General-purpose arbitrary frontend plugin mutation APIs.

## Implementation Phases

The roadmap should intentionally optimize for real author workflows before
platform polish. The first complete loop should make it possible for one
developer to run a local dev server, attach it in Pivot, open it inside the
chat dock, and read or write workspace files through the intended runtime
contract.

### Phase 1: Minimal Development Loop

Goal:

- Prove that a surface can be developed locally and rendered in the chat dock
  through Pivot-owned runtime primitives.

Scope:

- Add `chat_surfaces` manifest contribution parsing in `/pivot/`.
- Add a minimal right-side dock in the chat UI with single-surface support.
- Add chat-header surface icons for installed or agent-bound surfaces.
- Add surface session creation plus the minimum bootstrap payload.
- Add minimal surface-scoped file APIs for:
  - list tree
  - read file
  - write file
- Add dev surface registration UI inside the existing chat debug entry and
  backend records.
- Add Vite-oriented dev server proxy with HTML bootstrap injection.
- Create `/extensions/sdk/surface-core` with the smallest usable API surface.
- Create one `/extensions/extensions/workspace-editor` sample.

Success criteria:

- A developer runs `npm run dev` in the sample surface.
- Pivot can attach that dev server from the debug UI.
- A temporary `DEV` icon appears in the chat header after attach.
- The sample surface loads in the right dock when the header icon is clicked.
- The sample surface can list files, open a file, and save a file.
- The developer never needs to handcraft iframe bootstrap or token plumbing.

Out of scope:

- Installed extension packaging polish.
- Multi-tab docking.
- Canvas-specific APIs.
- Transcript replay UX.

### Phase 2: Stable Authoring Contract

Goal:

- Turn the Phase 1 development loop into a stable author-facing contract.

Scope:

- Harden `surface-core` bootstrap handling and error states.
- Add explicit capability presets and allowed-path-prefix validation.
- Add raw `surface.fetch()` escape hatch and typed workspace primitives.
- Add better dev-surface lifecycle handling:
  - reconnect
  - health checks
  - clearer proxy errors
- Add starter templates for:
  - vanilla
  - react-vite
  - vue-vite
- Add example recipes and author documentation in `/extensions/`.

Success criteria:

- Official samples and templates all use the same `surface-core`.
- A new author can start from a template instead of reverse-engineering the
  sample implementation.
- Surface APIs can evolve without forcing a framework-specific SDK strategy.

Out of scope:

- Marketplace publishing.
- Installed extension management UI for surfaces beyond minimal support.

### Phase 3: Installed Surface Runtime

Goal:

- Support real installed surface extensions with package-pinned runtime assets.

Scope:

- Extend manifest normalization and runtime bundle building for installed
  surfaces.
- Serve installed surface runtime pages from extension package assets.
- Unify installed bootstrap generation with dev bootstrap semantics.
- Add installed-surface permission review and operator-facing metadata.
- Validate that one installed sample surface works without dev proxy.

Success criteria:

- One installed surface can be enabled for an agent and opened in chat.
- Installed runtime pages use the same author-facing SDK contract as dev
  surfaces.
- Session-pinned extension versions produce stable surface behavior.

Out of scope:

- Full extension hub publishing workflow.
- Rich dock layouts or advanced shell orchestration.

### Phase 4: Multi-Surface Use Cases

Goal:

- Expand beyond the first coding surface and validate other visual patterns.

Scope:

- Add one transcript or pixel-agent sample to validate task-event rendering.
- Add one canvas-oriented sample to validate file-backed document workflows.
- Add task-event APIs or transcript helpers where needed.
- Add better shell controls for title, badge, resize, and dirty-state hints.

Success criteria:

- The platform can support at least three distinct surface categories:
  - coding workspace
  - transcript or pixel visualization
  - canvas or visual document editing
- The same file- and event-centric architecture remains viable across them.

Out of scope:

- Advanced collaboration or multi-user editing.
- Desktop-native direct filesystem optimization.

### Phase 5: Ecosystem Packaging and Hub

Goal:

- Turn the surface system from an internal capability into a reusable extension
  ecosystem feature.

Scope:

- Formalize authoring and publishing guidance in `/extensions/`.
- Add hub-facing surface metadata, previews, and installation flows.
- Add more complete compatibility signaling between `/pivot/` and
  `/extensions/sdk/surface-core`.
- Improve sample coverage and extension author onboarding.

Success criteria:

- Surface extensions feel like a documented, reusable part of the broader
  Pivot extension ecosystem.
- SDK, samples, and hub assets are coherently organized under `/extensions/`.

Out of scope:

- Arbitrary frontend mutation APIs.
- Fully general third-party UI sandboxing beyond declared surface capabilities.

### Phase N: Optional Future Enhancements

Possible later work:

- Desktop-only filesystem adapters behind `surface-core`.
- Rich multi-tab or multi-pane docking.
- Workspace-hosted development flows beyond dev server proxy.
- More advanced watch semantics across non-local storage backends.
- Collaborative editing and shared runtime sessions.

## Open Questions

- Should installed surface runtime pages use short-lived bearer tokens, signed
  same-origin cookies, or server-side surface sessions only?
- How should workspace file watching be implemented across local POSIX,
  external POSIX, and future object-storage-backed workspaces?
- Should task-event streaming be exposed through the same surface session API or
  through a dedicated event subscription endpoint?
- How much of the extension permission review UI should be shared with tools,
  hooks, and providers?
- Should dev surface records be persisted in the database or kept as local
  process state during early development?
