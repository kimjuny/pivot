# Pivot Desktop

## Positioning

Pivot Desktop is a native desktop application that wraps the Consumer web
experience, giving end users a dedicated window into their published agents
without needing a browser tab.

The first version should be a thin shell — not a second product. It should load
the same Consumer routes, reuse the same authentication, and render the same
chat runtime. The value of the desktop shell is presence, integration, and
future local capability, not a separate feature set.

## Why Desktop

The web-based Consumer already works. A desktop shell is justified only when
the browser boundary becomes a real limitation:

- **Always-on presence.** Users can keep the agent in the system tray instead of
  competing for browser tabs. Notifications reach the user even when the
  browser window is minimized or closed.
- **Local resource bridge.** Agents that need to read or write local files,
  access the clipboard, or interact with desktop applications cannot do this
  from a browser sandbox. A desktop shell opens this path.
- **Enterprise deployment.** IT departments can package, sign, and distribute a
  desktop application through standard software management pipelines. Browser
  bookmarks are harder to enforce and harder to de-provision.
- **Professional weight.** For paying enterprise customers, a dedicated
  application carries more perceived value than a web page.

## Product Principles

- Shell-first, not app-first. The desktop shell wraps the existing Consumer, it
  does not fork it.
- The web app remains the source of truth for all UI. Desktop-specific native
  elements are limited to chrome that cannot be done in a browser.
- Local capabilities are opt-in and permission-gated, not automatic.
- Desktop does not introduce a separate data model, API surface, or session
  type. Consumer sessions created from the desktop app are still `consumer`
  sessions.
- The desktop shell should degrade gracefully. If the backend is unreachable,
  the user should see a clear status indicator, not a blank window.

## Roles and User Flows

### Role 1: End User

The primary desktop user. They do not access Studio.

#### Flow 1A — First Launch

1. User downloads the Pivot Desktop installer from a distribution link or
   internal software portal.
2. User installs and launches the application.
3. The desktop entry (`web/src/desktop/main.tsx`) detects that no backend URL
   is stored, and renders the setup screen (`DesktopSetup.tsx`).
4. User enters the backend server URL (e.g. `https://pivot.example.com`).
5. The setup screen tests connectivity and stores the URL in localStorage.
6. The app then loads the Consumer login page using the shared authentication
   system.
7. After login, `/app` restores the latest `consumer` session or redirects to
   the agent list, exactly as it does in the browser.

#### Flow 1B — Daily Use

1. User launches Pivot Desktop (or restores from system tray).
2. The application opens directly into the last active session or the agent
  list.
3. User interacts with an agent through the same ReAct chat surface used in the
  browser Consumer.
4. When the user closes the window, the application minimizes to the system
  tray instead of quitting.
5. Agent responses that arrive while the window is minimized appear as native
  desktop notifications.

#### Flow 1C — Local Resource Access (future)

1. During a conversation, the agent needs to read a local file.
2. The desktop shell shows a native permission prompt: "Agent wants to read
   /Users/alice/report.xlsx".
3. User approves.
4. The desktop bridge reads the file and sends its content back through the
   normal tool-result channel.
5. The agent continues the conversation with the file content available.

#### Flow 1D — Multi-Agent Switching

1. User is in a conversation with Agent A.
2. User opens the sidebar and selects Agent B.
3. The application navigates to Agent B's chat surface, exactly as the browser
   Consumer does.
4. The session for Agent A remains in the recent session list.

### Role 2: Workspace Administrator (Studio User)

Uses Studio to manage agents, releases, and — eventually — desktop capability
policies.

#### Flow 2A — Agent Publishing for Desktop

1. Administrator builds and tests an agent in Studio.
2. Administrator publishes a release.
3. The agent immediately becomes available in both the browser Consumer and the
  desktop Consumer, because they share the same serving contract.
4. No separate "publish for desktop" step exists.

#### Flow 2B — Configuring Desktop Capabilities (future)

1. Administrator opens Studio → Connections → Desktop Connectors.
2. Administrator sees a list of desktop capability profiles.
3. Each profile defines what an agent can request from the user's desktop:
   file system scope, notification access, clipboard access, application
   launching.
4. Administrator assigns a capability profile to one or more agents.
5. When an end user interacts with that agent from the desktop app, the agent
  can request actions up to the limits defined in the profile.
6. End users still see a per-request permission prompt for sensitive
   operations.

### Role 3: IT Administrator

Manages desktop application deployment within an organization.

#### Flow 3A — Enterprise Deployment

1. IT administrator downloads the Pivot Desktop installer package.
2. IT administrator distributes it through the organization's software
   management tool (MDM, SCCM, etc.).
3. End users receive the application automatically or through an internal portal.
4. Auto-update keeps end users on the latest version.

## Desktop Shell Architecture

### Technology Choice: Tauri

Recommended: **Tauri** over Electron.

Reasons:

- Pivot's web frontend is already built. The desktop shell only needs to load
  it inside a WebView, not bundle a full Chromium instance.
- Tauri produces a binary approximately 10-15 MB, compared to Electron's
  150-200 MB. This matters for enterprise deployment and update bandwidth.
- Tauri's Rust backend provides a natural security boundary for local resource
  access. File system, clipboard, and notification operations can be
  individually permission-gated at the Rust layer.
- Tauri uses the operating system's native WebView (WebView2 on Windows,
  WebKit on macOS, WebKitGTK on Linux). This matches the "thin shell" goal.

Trade-off:

- WebView rendering differences across operating systems require testing.
- Tauri's ecosystem is smaller than Electron's. For the current scope this is
  acceptable because the shell is intentionally minimal.

### Shell Structure

```
┌─────────────────────────────────────────────┐
│            Pivot Desktop Shell               │
│                                             │
│  ┌───────────────────────────────────────┐  │
│  │         WebView Layer                 │  │
│  │                                       │  │
│  │   Loads Consumer /app/* routes        │  │
│  │   from the backend server             │  │
│  │                                       │  │
│  └───────────────────────────────────────┘  │
│                                             │
│  ┌───────────────────────────────────────┐  │
│  │         Native Layer (Rust)           │  │
│  │                                       │  │
│  │   - Window management                 │  │
│  │   - System tray                       │  │
│  │   - Native notifications              │  │
│  │   - Auto-update (Tauri updater)       │  │
│  │   - Local resource bridge (future)    │  │
│  │   - Single-instance lock              │  │
│  │                                       │  │
│  └───────────────────────────────────────┘  │
│                                             │
└─────────────────────────────────────────────┘
```

### How the WebView Connects to the Backend

There are two fundamentally different approaches, and the choice matters:

#### Approach A — Load remote pages from the backend

```
Desktop Shell → WebView → https://pivot.example.com/app/*
```

The WebView loads the fully rendered HTML from the backend server, exactly as a
browser would.

Pros:
- No cross-origin issues. The page origin is `https://pivot.example.com`, so
  `/api/*` requests are same-origin. This matches the current production setup
  where a reverse proxy serves both static files and API routes.
- No separate frontend build for desktop.
- Always serves the latest frontend version.

Cons:
- The desktop app shows nothing when offline — not even a login screen.
- Every UI interaction depends on the network.
- Cannot embed desktop-specific logic at build time.

#### Approach B — Bundle the frontend build, call remote API

```
Desktop Shell → WebView → tauri://localhost/index.html (local dist/)
                     └──► https://pivot.example.com/api/* (remote backend)
```

The desktop app ships with a pre-built copy of the Consumer frontend. API calls
go to the remote backend.

Pros:
- Login screen, agent list skeleton, and error states render instantly without
  network.
- Can embed desktop-specific behavior at build time (Tauri IPC bridge, native
  file picker hooks, etc.).
- Better perceived performance — shell chrome is always responsive.

Cons:
- Cross-origin requests. The WebView origin is `tauri://localhost` (or
  `https://tauri.localhost` on some platforms), so calling
  `https://pivot.example.com/api/*` is a cross-origin request that requires
  CORS or a local proxy.
- Frontend version is pinned to the desktop app version. Users must update the
  desktop app to get UI changes.
- Requires a separate build configuration for the desktop target.

#### Implemented: Approach B with `tauri-plugin-http`

Approach B is the right choice for an enterprise desktop product because:

1. The login screen and error states must render offline. An app that shows a
   blank window when the network blinks is not acceptable.
2. Local capabilities (Phase 4) require build-time integration of the Tauri IPC
   bridge. This is impractical with remotely loaded pages.
3. Enterprise deployments need predictable, versioned releases. Bundling the
   frontend makes the desktop app version the single source of truth for what
   UI the user sees.

The cross-origin problem is solved by a two-mode architecture:

**Dev mode** — Vite dev server proxies `/api` to the backend. No CORS needed
because requests are same-origin. Both web and desktop dev servers share this
mechanism.

**Prod mode** — `tauri-plugin-http` replaces the HTTP client with a Rust-side
`reqwest` client. Every `httpClient()` call is routed through the Tauri Rust
process, bypassing the WebView's CORS enforcement entirely:

```
┌────────────────────────────────────────────┐
│             Tauri Desktop Shell            │
│                                            │
│  ┌──────────────────────────────────────┐  │
│  │         WebView                      │  │
│  │   httpClient() (pluggable)           │  │
│  │        │                             │  │
│  └────────┼─────────────────────────────┘  │
│           │                                │
│  ┌────────▼─────────────────────────────┐  │
│  │   tauri-plugin-http (Rust/reqwest)   │  │
│  │   fetch → https://host:8003/api/*    │  │
│  │   (no CORS — Rust is the client)     │  │
│  └──────────────────────────────────────┘  │
└────────────────────────────────────────────┘
```

This approach means:

- The backend **never needs to allow the Tauri origin** in CORS. Only the
  web-dev origin (`http://localhost:3000`) is allowed.
- All `fetch()` calls go through a shared `httpClient()` abstraction. In dev
  mode this is the native `fetch` (Vite proxy handles routing). In prod mode
  the Tauri HTTP plugin overrides it via `setHttpClient()` before React mounts.
- No global `window.fetch` mutation — the override is explicit and controlled.
- The URL resolution (`getApiBaseUrl()`) returns `/api` in dev mode and the
  runtime-configured absolute URL in prod mode.

The backend CORS configuration is restricted:

```python
# server/app/main.py
_cors_origins = os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(CORSMiddleware, allow_origins=_cors_origins, ...)
```

Build configuration:

- The desktop build uses `web/vite.config.desktop.ts` which outputs to
  `web/dist-desktop/`.
- `VITE_API_BASE_URL` is set to an empty string in `.env.desktop`. The
  runtime adapter provides the real URL after the user completes the
  setup screen.

Configuration storage (current MVP):

- The backend URL is stored in `localStorage` under the key
  `pivot_desktop_backend_url`.
- This is sufficient for a pre-launch product. A future iteration should
  migrate to the OS-appropriate config directory via Tauri's store plugin:
  - macOS: `~/Library/Application Support/io.pivot.desktop/config.json`
  - Windows: `%APPDATA%/Pivot/config.json`
  - Linux: `~/.config/pivot/config.json`

Fallback behavior:

- If the backend URL is not yet configured (first launch), the desktop entry
  renders a React-based setup screen (`DesktopSetup.tsx`) where the user
  enters the server address. This is a WebView page, not a native Rust dialog.
- If the backend URL is configured but unreachable, the WebView still renders
  the local frontend, which shows a connection-error state with a retry button.
- Network failures surface as standard fetch errors that the frontend API layer
  handles gracefully.

### IPC Bridge

Tauri provides an `invoke` mechanism for JavaScript-to-Rust communication.

Direction:

```
WebView (JS)  ──invoke──►  Rust handler  ──►  OS / local resource
WebView (JS)  ◄──event───  Rust handler  ◄──  OS / local resource
```

The IPC bridge should start minimal and grow as local capabilities are added.

### Initial IPC Surface (MVP)

| Command | Direction | Purpose |
|---------|-----------|---------|
| `get_version` | JS → Rust | Show desktop app version in UI |
| `get_platform` | JS → Rust | Report OS for conditional UI |
| `open_external` | JS → Rust | Open a URL in the default browser |
| `get_server_status` | JS → Rust | Check if configured backend URL is reachable |

### Future IPC Surface (local resource bridge)

| Command | Direction | Purpose |
|---------|-----------|---------|
| `read_file` | JS → Rust | Read a local file after user approval |
| `write_file` | JS → Rust | Write a local file after user approval |
| `pick_file` | JS → Rust | Show native file picker dialog |
| `pick_folder` | JS → Rust | Show native folder picker dialog |
| `read_clipboard` | JS → Rust | Read clipboard content |
| `write_clipboard` | JS → Rust | Write to clipboard |
| `show_notification` | JS → Rust | Show native desktop notification |
| `list_directory` | JS → Rust | List contents of a local directory |

Each future command must:

- Check the agent's assigned desktop capability profile before executing.
- Show a native permission prompt for sensitive operations.
- Respect the end user's deny response by returning a permission-denied error.

## Relationship to Existing Architecture

### What the Desktop Shell Does Not Change

- The Consumer routes (`/app/*`) remain unchanged.
- The Consumer API layer (`web/src/consumer/api.ts`) remains unchanged.
- The chat runtime (`ReactChatInterface.tsx`) remains unchanged.
- Session model: desktop-created sessions are still `session.type = consumer`.
- Authentication uses the same JWT-based system as the web Consumer.
- The backend does not need to know whether a request came from a browser or
  the desktop shell.
- The shared API module (`web/src/utils/api.ts`) is unchanged in its
  `apiRequest()` interface — only the URL resolution changed from a static
  `API_BASE_URL` constant to a dynamic `getApiBaseUrl()` function.

### What the Desktop Shell Adds

- A bundled copy of the Consumer frontend that renders without network.
- A native window with system tray behavior (close-to-tray, single instance).
- `tauri-plugin-http` which replaces the HTTP client so all `httpClient()` calls
  route through Rust's `reqwest` client in production, bypassing CORS entirely.
  In dev mode the Vite proxy handles routing instead.
- Runtime-configurable backend URL via `setApiBaseUrl()` and the desktop
  setup screen.
- A thin platform adapter (`desktop-adapter.ts`) for feature detection.
- A connection-error state rendered by the local frontend when the backend is
  unreachable.
- Consumer-only routes: the desktop entry (`web/src/desktop/main.tsx`)
  mounts only `/app/*` routes, not Studio routes. This produces a smaller
  bundle by excluding Monaco Editor, XyFlow, and Studio pages.

### What This Means for the Consumer Frontend

The existing Consumer frontend should not grow desktop-specific code paths.

Instead:

- Any desktop-specific behavior (file access, notifications) should be exposed
  through a thin JavaScript adapter that calls `window.__TAURI__` when present
  and falls back to a no-op or browser alternative when not present.
- This adapter lives in `web/src/desktop/desktop-adapter.ts`, a single module.
- The adapter is typed but does not depend on Tauri types at build time — it
  uses dynamic feature detection (`"__TAURI__" in window`).

Actual implementation:

```typescript
// web/src/desktop/desktop-adapter.ts
const STORAGE_KEY = "pivot_desktop_backend_url";

/** Whether the app is running inside the Tauri desktop shell. */
export const isDesktop: boolean = "__TAURI__" in window;

/** Read the previously stored backend URL from localStorage. */
export function getStoredBackendUrl(): string | null {
  return localStorage.getItem(STORAGE_KEY);
}

/** Persist the backend URL after the user completes the setup screen. */
export function setStoredBackendUrl(url: string): void {
  localStorage.setItem(STORAGE_KEY, url);
}

/**
 * Build the full API base URL from the stored backend URL.
 * Returns null if no backend URL is stored (first launch).
 */
export function resolveApiBaseUrl(): string | null {
  const stored = getStoredBackendUrl();
  if (!stored) return null;
  const trimmed = stored.replace(/\/+$/, "");
  return `${trimmed}/api`;
}
```

The shared API module (`web/src/utils/api.ts`) exposes a pluggable HTTP client
(`httpClient` / `setHttpClient`) and dynamic URL resolution (`getApiBaseUrl()` /
`setApiBaseUrl()`). In dev mode `getApiBaseUrl()` returns `/api` (routed by the
Vite proxy). In prod mode the desktop adapter injects the runtime URL and the
Tauri HTTP plugin overrides the HTTP client.

In addition to the adapter above, the desktop entry dynamically loads the
Tauri HTTP plugin in production and injects it via `setHttpClient()`:

```typescript
// web/src/desktop/main.tsx — bootstrap()
if (!import.meta.env.DEV) {
  const { fetch: tauriFetch } = await import("@tauri-apps/plugin-http");
  setHttpClient(tauriFetch as typeof fetch);
}
```

This ensures every `httpClient()` call in the app — API requests, SSE streams,
login, setup connectivity test — is routed through Rust's `reqwest` client in
production. In dev mode the Vite proxy handles routing, so the Tauri plugin is
not loaded.

## Desktop Connectors — Studio Configuration Surface

### What Desktop Connectors Are

Desktop Connectors are capability profiles that define what an agent is allowed
to request from the end user's desktop environment.

They are not:
- Software installed on the end user's machine.
- Network connections or API integrations.
- A separate runtime environment.

They are:
- A named set of permission rules stored in the backend.
- Assigned to agents by administrators in Studio.
- Enforced at runtime by the desktop shell when an agent requests a local
  operation.

### Do We Need Desktop Connectors for the First Version?

No.

The first desktop version wraps the Consumer web experience without any local
resource access. Agents continue to use the same server-side sandbox tools they
use in the browser.

Desktop Connectors become relevant only when agents need local capabilities
(file access, notifications, clipboard, application launching).

Recommendation:

- Build the desktop shell first.
- Ship it without Desktop Connectors support.
- Gather usage data and user feedback.
- Introduce Desktop Connectors when there is a concrete need for local resource
  access.
- Keep the Studio navigation entry as a disabled placeholder until then.

### Future Desktop Connector Data Model

When the time comes, a Desktop Connector profile might look like:

```json
{
  "name": "Standard Workspace Access",
  "description": "Read-only access to user-selected folders",
  "capabilities": {
    "file_read": { "scope": "user_selected", "max_size_mb": 50 },
    "file_write": false,
    "clipboard_read": false,
    "clipboard_write": true,
    "notification": true,
    "app_launch": false
  }
}
```

Assignment:

- Each agent can be assigned zero or one desktop connector profile.
- If no profile is assigned, the agent has no desktop capabilities.
- If a profile is assigned, the desktop shell enforces its limits.

### Studio Integration (future)

When Desktop Connectors are ready for implementation:

- Studio → Connections → Desktop Connectors becomes an active surface.
- It shows a list of capability profiles.
- Administrators can create, edit, and delete profiles.
- In the agent workspace, a new "Desktop" section in the Connections module
  lets administrators assign a profile to the agent.
- This assignment is snapshotted into the release, just like tool and skill
  selections.

## MVP Scope

### In Scope — First Desktop Version

- Tauri shell that loads the Consumer `/app/*` routes.
- Login using the shared authentication system.
- System tray behavior: minimize to tray on close, restore on click.
- Native window management: title bar, minimize, maximize, close.
- Backend URL configuration on first launch.
- Connection-status screen when the backend is unreachable.
- Single-instance enforcement (only one Pivot Desktop window at a time).
- Auto-update through Tauri's updater mechanism.
- Platform detection so the Consumer frontend can adapt if needed.

### Explicitly Out of Scope — First Version

- Local file access for agents.
- Desktop capability profiles (Desktop Connectors in Studio).
- Native notification delivery.
- Clipboard access.
- Offline mode or local-first behavior.
- Local LLM execution.
- Multiple backend profiles or workspace switching.
- A separate session type or data model.
- Deep OS integration (context menus, file associations, URL scheme handlers).

## Project Structure

### Actual Directory Layout

The desktop frontend entry lives inside `web/` to reuse all existing
dependencies (React, Radix, Tailwind, etc.) without duplication. The Tauri
Rust shell lives in a separate `desktop/` directory.

```
pivot/
  web/                               ← Existing frontend project
    desktop.html                     ← HTML entry for desktop build
    vite.config.desktop.ts           ← Desktop Vite config → dist-desktop/
    .env.desktop                     ← VITE_API_BASE_URL= (empty sentinel)
    src/
      desktop/                       ← Desktop-specific modules
        main.tsx                     ← Consumer-only React entry
        DesktopSetup.tsx             ← First-launch backend URL setup screen
        desktop-adapter.ts           ← Platform detection + URL management
      utils/
        api.ts                       ← Shared API layer (getApiBaseUrl / setApiBaseUrl)

  desktop/                           ← Tauri Rust project (thin shell)
    package.json                     ← Build scripts + Tauri CLI
    src-tauri/
      Cargo.toml
      build.rs
      tauri.conf.json                ← frontendDist → ../../web/dist-desktop/
      capabilities/
        default.json                 ← Security permissions
      icons/                         ← Generated from web/public/pivot.png
      src/
        main.rs                      ← Desktop entry → calls app_lib::run()
        lib.rs                       ← Tray, single-instance, close-to-tray
```

Why the frontend entry is in `web/` rather than `desktop/`:

- The `desktop/` project does not have its own `node_modules` or Vite config.
  It only has `package.json` for Tauri CLI scripts.
- The desktop Vite config (`web/vite.config.desktop.ts`) reuses the same
  `@/` alias, Tailwind, and React plugins as the web build. This avoids
  duplicating configuration.
- The build command `cd ../web && npx vite build --config vite.config.desktop.ts`
  produces `web/dist-desktop/`, which Tauri bundles into the native binary.

Why the desktop entry mounts Consumer-only routes:

- `web/src/desktop/main.tsx` defines only `/`, `/app`, `/app/agents`,
  `/app/agents/:agentId` routes. It does not mount any Studio routes.
- This excludes Monaco Editor, XyFlow, and other Studio-only heavy
  dependencies from the desktop bundle, reducing it by roughly 30%.
- The desktop app has no address bar, so Studio routes are completely
  inaccessible even if the code were included.

### What Goes in `web/src/desktop/`

Three files, each with a clear purpose:

- `main.tsx`: React entry that checks for a stored backend URL, shows
  `DesktopSetup` if missing, then mounts Consumer-only routes.
- `DesktopSetup.tsx`: Full-screen form for entering and testing the backend
  URL on first launch. Renders inside the WebView, not as a native dialog.
- `desktop-adapter.ts`: Platform detection (`isDesktop`), localStorage URL
  storage (`getStoredBackendUrl` / `setStoredBackendUrl`), and API URL
  resolution (`resolveApiBaseUrl`).

The Consumer frontend (in `web/src/consumer/`) can optionally import from
`web/src/desktop/desktop-adapter.ts` through a dynamic import with feature
detection, but this is a runtime bridge, not a build-time dependency.

## Backend Changes

### None Required for MVP

The first desktop version does not require any backend changes.

The desktop shell loads the same Consumer web app and hits the same Consumer
API endpoints. The backend cannot distinguish between a browser request and a
desktop shell request, and it should not need to.

### Future Backend Additions (when Desktop Connectors ship)

When local capabilities are introduced:

1. **Desktop Connector profile CRUD** — A new model and service for capability
   profiles. Stored in a `desktop_connector` table. CRUD endpoints under
   `/api/studio/connections/desktop-connectors`.

2. **Agent-level assignment** — A foreign key from the agent draft/release
   snapshot to a desktop connector profile. This assignment follows the same
   draft-and-release model as tool and skill selections.

3. **Capability enforcement metadata** — The release snapshot includes the
   assigned desktop connector profile. The desktop shell fetches this as part
   of the agent detail response and enforces it locally.

4. **Permission audit log** — A log of local resource access approvals and
   denials, sent from the desktop shell to the backend for operations
   visibility.

## Implementation Phases

### Phase 0 — Tauri Shell Skeleton ✅

Goal: A window that loads the Consumer app from a configured backend URL.

Status: **Completed.**

1. ✅ Initialize the Tauri project in `desktop/`.
2. ✅ Configure the main window to load bundled Consumer frontend.
3. ✅ Implement first-launch backend URL configuration screen
   (`DesktopSetup.tsx`).
4. ✅ Implement single-instance lock (`tauri-plugin-single-instance`).
5. macOS tested; Windows and Linux pending CI.

### Phase 1 — System Tray and Window Management ✅

Goal: Desktop-app-level presence behavior.

Status: **Completed.**

1. ✅ System tray icon with context menu (Show Pivot, Quit).
2. ✅ Minimize-to-tray on window close (`prevent_close` + `window.hide()`).
3. Window state persistence (remember size and position) — **not yet
   implemented**.
4. Connection-status indicator in the tray or title bar — **not yet
   implemented**.

### Phase 2 — Auto-Update and Distribution

Goal: Shippable, auto-updating application.

1. Configure Tauri's updater with the backend or a CDN as the update source.
2. Code signing for macOS and Windows.
3. Installer packaging (DMG for macOS, MSI/NSIS for Windows, AppImage for
   Linux).
4. Test update flow end-to-end.

### Phase 3 — Desktop Bridge Foundation

Goal: IPC layer ready for future local capabilities.

1. Implement the JavaScript adapter module (`desktop-bridge.ts`).
2. Expose platform and version information to the WebView.
3. Add `open_external` command for opening links in the default browser.
4. Document the IPC extension pattern for future capabilities.

### Phase 4 — Local Resource Access (future, after Phase 3)

Goal: Agents can request local file and system operations.

1. Implement `read_file`, `write_file`, `pick_file`, `pick_folder` commands
   in Rust.
2. Implement native permission prompts for each operation.
3. Implement Desktop Connector profile model in the backend.
4. Implement Desktop Connectors configuration surface in Studio.
5. Implement agent-level profile assignment in the release snapshot.
6. Wire the desktop bridge through the tool execution pipeline:
   - Agent calls a tool → backend receives the tool call → backend sends a
     desktop bridge request to the client → desktop shell executes locally →
     result flows back through the same channel.

### Phase 4 Communication Pattern

When local tool execution is implemented, the flow looks like:

```
Agent (LLM)                  Backend                    Desktop Shell
    │                          │                            │
    │  tool_call(read_file)    │                            │
    │ ──────────────────────►  │                            │
    │                          │  WebSocket/SSE push         │
    │                          │  { type: "desktop_tool",   │
    │                          │    tool: "read_file",       │
    │                          │    args: { path: "..." } }  │
    │                          │ ──────────────────────────► │
    │                          │                            │
    │                          │                    [Permission Prompt]
    │                          │                    [User Approves]
    │                          │                    [Read File]
    │                          │                            │
    │                          │  HTTP callback              │
    │                          │  { result: "file..." }      │
    │                          │ ◄────────────────────────── │
    │                          │                            │
    │  tool_result             │                            │
    │ ◄──────────────────────  │                            │
    │                          │                            │
```

This pattern keeps the backend as the orchestration layer while delegating
execution to the desktop shell. The backend never directly accesses the user's
machine.

## Verification

### Phase 0 ✅

1. ✅ `cargo build` succeeds in `desktop/src-tauri/`.
2. ✅ `vite build --config vite.config.desktop.ts` produces `dist-desktop/`.
3. ✅ The web build (`vite build`) still passes — no regressions.
4. ✅ TypeScript type-check passes (`tsc --noEmit`).
5. Entering an invalid backend URL shows an error, not a crash — **needs
   manual testing with `tauri dev`**.
6. Entering a valid backend URL loads the Consumer login page — **needs
   manual testing with `tauri dev`**.
7. After login, `/app` redirects correctly (session restore or agent list) —
   **needs manual testing with `tauri dev`**.

### Phase 1 ✅ (partial)

1. ✅ Closing the window hides to tray instead of quitting (Rust
   `prevent_close` + `window.hide()`).
2. ✅ Clicking the tray "Show Pivot" menu item restores the window.
3. ✅ "Quit" from the tray context menu exits the application.
4. Window size and position do not persist across restarts — **not yet
   implemented**.
5. Disconnecting the network shows a status indicator — **not yet
   implemented**.

### Phase 2

1. Installing a new version triggers the auto-update flow.
2. The update applies correctly on restart.
3. Code-signed binaries pass Gatekeeper (macOS) and SmartScreen (Windows).

### Phase 3

1. `desktop.getPlatform()` returns correct OS information.
2. `desktop.openExternal("https://...")` opens in the default browser.
3. The adapter returns `isDesktop = false` when loaded in a regular browser.

## Non-Goals

- A full offline-first desktop application.
- Local LLM inference.
- A separate session or data model for desktop.
- Desktop-to-desktop agent communication.
- Screen sharing or remote desktop capabilities.
- A separate CI/CD pipeline that diverges from the web application.

## Summary

Pivot Desktop starts as a thin native shell around the existing Consumer web
experience. It does not introduce a new product, a new data model, or a new API
surface. It adds native OS integration (tray, window management, auto-update)
and establishes the IPC foundation for future local resource access.

The current implementation uses a dual-mode approach for API access:
- **Dev mode**: Vite dev server proxies `/api` to the backend (no CORS needed).
- **Prod mode**: `tauri-plugin-http` routes requests through Rust's reqwest
  (no CORS — Rust is the HTTP client, not the WebView).

Server CORS is restricted to `http://localhost:3000` by default, configurable
via the `CORS_ORIGINS` environment variable. The Tauri origin never needs to be
allowed because prod-mode requests go through Rust, not the WebView.

Desktop Connectors in Studio remain a placeholder until agents need local
capabilities. When that time comes, they become the configuration surface for
permission-scoped desktop operations.

The implementation order is deliberate:

1. Shell first (minimum viable presence). ✅
2. System tray and window management (desktop-native behavior). ✅
3. Auto-update (shippable product).
4. IPC foundation (extensibility).
5. Local resource access (the real differentiator, but not day one).
