# Pivot Extensions

## Positioning

Pivot should expose one unified extension system that can participate in the
full agent lifecycle:

- Build time in Studio
- Runtime execution in Consumer and Studio Test
- Release publishing and version pinning
- Session, task, and iteration level orchestration
- Post-release operations and debugging

An extension is the primary packaging unit for heavier, versioned integrations.
One extension is one folder on disk with a required `manifest.json` file at its
root. The folder may contain multiple contribution types, such as tools,
skills, lifecycle hooks, channel providers, and web-search providers.

This model should not force every capability in Pivot into package form.
Instead, Pivot should support two valid integration styles:

- Lightweight direct registration for standalone tools and skills
- Package-based registration for extension-shaped integrations, especially
  providers and multi-capability bundles

The extension system therefore complements existing resource models instead of
replacing every one of them.

Developer-facing implementation guidance should stay in
[docs/extensions.md](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/docs/extensions.md).
That document should explain the concrete package contract for:

- `manifest.json`
- `configuration.installation` and `configuration.binding`
- lifecycle hooks
- channel providers
- web-search providers
- packaged skills
- packaged tools

This draft should stay focused on product and runtime design, while the docs
page should explain how an extension author actually builds one.

## Why Extensions Should Be Folder Packages

A folder-based package model is the best fit for Pivot's current architecture
and future product direction.

Benefits:

- A single installation unit can contain multiple related capabilities.
- Local development stays simple because contributors can edit normal files
  instead of publishing into a binary format too early.
- Versioning is coherent. One extension version can freeze one compatible set of
  tools, skills, providers, and hooks.
- Permission review is coherent. Operators review one package-level permission
  declaration instead of reasoning about many scattered files.
- Release pinning is simpler. Sessions can pin one resolved extension bundle
  rather than many independent resource rows that may drift over time.
- Uninstall and upgrade become manageable because the system tracks one package
  identity with multiple contributions beneath it.

This also matches how many developer ecosystems think about integrations:
folder-based packages with a manifest, optional source files, and declared
entrypoints.

## Product Goals

- Introduce one coherent package model for integrations that benefit from
  versioning, permissions, bundling, and release pinning.
- Let one extension contribute to multiple lifecycle phases without forcing all
  extensions to implement all phases.
- Preserve Pivot's release model so runtime behavior is version-pinned and
  replayable.
- Keep persistence behind service-layer APIs. Extensions must not directly touch
  the database, file storage, or cache backends.
- Support gradual rollout. Existing tools and skills should continue to work as
  lightweight standalone assets, while providers and richer integrations move
  into packages over time.

## Non-Goals

- Do not design a fully general third-party code execution environment on day
  one.
- Do not introduce frontend UI plugins as a first milestone.
- Do not allow extensions to mutate arbitrary internal runtime objects.
- Do not let sessions dynamically switch to newer extension versions after the
  session has started.

## Product Principles

- Package-first, not resource-first.
- Version-pinned runtime over live mutable runtime.
- Declarative manifest over convention-only discovery.
- Least privilege by default.
- Service-mediated persistence only.
- Replayable and observable execution.
- Fail-soft by default, fail-closed only for explicit policy hooks.
- Incremental migration over big-bang replacement.
- Dual-path extensibility: lightweight assets for simple tools and skills,
  packaged extensions for providers and heavier integrations.

## Core Vocabulary

### Extension

One installable package identified by a stable package id such as
`@acme/providers`.

### Extension Version

One immutable published artifact of an extension. Different versions of the same
extension may coexist because existing sessions may still reference older
versions.

### Contribution

One capability exposed by the extension, such as:

- A tool
- A skill
- A lifecycle hook
- A channel provider
- A web-search provider
- A prompt block provider
- A policy module

### Binding

The per-agent configuration that enables an installed extension and provides
runtime configuration, priority, and permission approval decisions.

### Resolved Bundle

The full set of extension versions and contribution metadata resolved for one
agent runtime. A session must pin this bundle at creation time.

## Package Layout

The following layout is recommended:

```text
acme-crm/
  manifest.json
  README.md
  assets/
  skills/
    crm_research/
      SKILL.md
      examples/
  tools/
    enrich_contact.py
    search_accounts.py
  hooks/
    lifecycle.py
  channel_providers/
    chat.py
  web_search_providers/
    search/
      provider.py
  tests/
```

Rules:

- `manifest.json` is required.
- Each skill directory must contain a `SKILL.md` file. This should not be
  configurable.
- Contribution source code should live in dedicated top-level directories by
  type.
- The package may contain shared assets and test fixtures.

The directory names are part of the package contract and should stay stable. A
stable layout reduces loader complexity and makes documentation predictable.

## Manifest

`manifest.json` is the canonical declaration of package identity, version,
compatibility, permissions, and contributed entrypoints.

Recommended example:

```json
{
  "schema_version": 1,
  "scope": "acme",
  "name": "providers",
  "display_name": "ACME CRM",
  "version": "0.1.0",
  "description": "CRM-oriented tools, skills, and lifecycle integrations.",
  "api_version": "1.x",
  "license": "Apache-2.0",
  "homepage_url": "https://example.com/acme-crm",
  "repository_url": "https://example.com/acme-crm.git",
  "contributions": {
    "skills": [
      {
        "name": "crm_research",
        "path": "skills/crm_research"
      }
    ],
    "tools": [
      {
        "name": "search_accounts",
        "entrypoint": "tools/search_accounts.py"
      },
      {
        "name": "enrich_contact",
        "entrypoint": "tools/enrich_contact.py"
      }
    ],
    "hooks": [
      {
        "event": "task.before_start",
        "entrypoint": "hooks/lifecycle.py",
        "callable": "before_task_start",
        "mode": "sync"
      },
      {
        "event": "iteration.after_tool_result",
        "entrypoint": "hooks/lifecycle.py",
        "callable": "after_tool_result",
        "mode": "async"
      }
    ],
    "channel_providers": [
      {
        "entrypoint": "channel_providers/chat.py"
      }
    ],
    "web_search_providers": [
      {
        "entrypoint": "web_search_providers/search/provider.py"
      }
    ]
  },
  "permissions": {
    "network": {
      "allow_hosts": ["api.acme.com"]
    },
    "secrets": ["ACME_API_KEY"],
    "workspace": {
      "read_paths": ["data/acme"],
      "write_paths": ["data/acme/cache"]
    },
    "sandbox": {
      "required": true
    }
  },
  "compatibility": {
    "min_pivot_version": "0.1.0",
    "max_pivot_version": "0.x"
  }
}
```

## Manifest Responsibilities

The manifest must declare:

- Stable package identity
- Human-readable metadata
- Package version
- Supported Pivot extension API version
- Contributed entrypoints
- Declared permissions
- Compatibility requirements

The manifest should not contain:

- Secrets
- Agent-specific configuration
- User-specific configuration
- Runtime mutable state

Those belong in bindings or service-managed storage.

## Identity Model

Pivot should align extension package naming with npm-style scopes.

Recommended identity fields:

- `scope`
- `name`
- `version`

Derived identity:

- Canonical package id: `@scope/name`
- Versioned package reference: `@scope/name@version`

Important rules:

- Version should not be embedded into the package name.
- Folder names are not canonical identity. `manifest.json` is authoritative.
- The older style of a single global package name such as `acme.crm` should be
  treated as transitional, not the target model.

## Scope Ownership And Trust

Before Pivot has a public Hub or Market, scope claims should be treated as
self-claimed identity, not verified identity.

Recommended trust states:

- `unverified`
- `trusted-local`
- `verified`

Recommended interpretation:

- Local import can claim `scope: "acme"`, but Pivot should treat that as
  unverified until the operator explicitly trusts the package.
- Future Hub-installed packages can become `verified` once Hub ownership checks
  exist.

Recommended local import flow:

1. Import folder or bundle
2. Preview `manifest.json` without creating an installation row
3. Show claimed package id `@scope/name`
4. Show contributions and permissions
5. Mark the preview as `unverified`
6. Ask the operator whether they trust the extension
7. Only allow installation and runtime use after trust is granted

Repository sample:

- A concrete local-import sample package should live in the repository under
  `server/examples/extensions/acme-providers`
- That sample should expose provider keys `acme@chat` and `acme@search`
- The sample package should stay runnable so docs and QA share the same source
  of truth
- A concrete mutable sample package should live in the repository under
  `server/examples/extensions/acme-memory`
- That sample should show the preferred boundary for external memory:
  recall at `task.before_start`, persist at `task.completed`, and skip writes
  when `execution_mode = replay`

Current implementation direction:

- Preview result should carry `trust_status = unverified`
- Local install should require explicit trust confirmation
- Persisted local installs should be recorded as
  `trust_status = trusted_local`
- Future Hub-installed packages should be recorded as
  `trust_status = verified`

## Future Hub Ownership Model

Pivot should align with npm-style scope ownership, but the source of truth
should live inside Pivot Hub rather than inside any one external login
provider.

Recommended Hub entities:

- `account`: one authenticated Hub identity
- `organization`: one optional team identity
- `scope`: one globally unique namespace owned by an account or organization
- `package`: one extension package under `@scope/name`

Key rule:

- GitHub, Google, and other providers should be treated as authentication
  methods, not as the direct owner of package namespaces

That means future GitHub login should help users sign in, but it should not be
the canonical identity of a scope. Scope ownership should be granted and
enforced by Pivot Hub.

Recommended scope rules:

- A scope is globally unique
- A scope is owned by exactly one Hub account or organization at a time
- A package publish to `@scope/name` is allowed only when the publishing actor
  owns that scope
- Local import may claim a scope string, but does not prove scope ownership
- Official Hub install may mark that same scope as verified

Recommended terminology:

- `claimed scope`: from local manifest
- `owned scope`: scope registered in Hub
- `verified scope`: scope on a package installed from official Hub

This keeps the public package identity simple:

- package identity: `@scope/name`
- versioned reference: `@scope/name@version`

And it avoids leaking an implementation-specific internal publisher identifier
into the package contract.

## Future Hub Data Model Sketch

The runtime extension system does not need all of this on day one, but the Hub
should likely evolve around entities like these:

- `hub_account`
  - stable internal id
  - display name
  - login methods
- `hub_organization`
  - stable internal id
  - display name
- `hub_scope`
  - stable internal id
  - scope name
  - owner type: `account | organization`
  - owner id
  - status: `active | reserved | suspended`
- `hub_scope_membership`
  - account permissions within an organization-owned scope
- `hub_package`
  - scope id
  - package name
  - canonical id `@scope/name`
- `hub_package_version`
  - package id
  - version
  - manifest hash
  - artifact metadata
  - verification metadata

Recommended responsibility split:

- Hub owns namespace allocation and publish authorization
- Runtime workspace owns local installation rows, bindings, and release pinning
- Runtime should consume verified package metadata from Hub, not re-decide scope
  ownership itself

## Hub And Runtime Boundary

The Hub and the runtime should be separate systems with a narrow handoff.

### Hub Responsibilities

Hub should own:

- Accounts and organizations
- Scope registration and transfer policy
- Publish authorization for `@scope/name`
- Package metadata and version history
- Artifact storage
- Verification metadata and future signing
- Marketplace review, listing, and discovery

Hub should answer questions like:

- Who owns scope `acme`?
- Is `@acme/providers@1.2.0` an officially published package?
- What artifact corresponds to that published version?

### Runtime Workspace Responsibilities

The runtime workspace should own:

- Local import preview and trust confirmation
- Local installation rows
- Artifact extraction into the workspace
- Enable/disable and uninstall semantics
- Agent bindings
- Release pinning
- Session and task execution
- Operational observability

Runtime should answer questions like:

- Which extension versions are installed in this workspace?
- Which version is bound to this agent?
- Which session pinned which extension bundle?
- Is this local package trusted enough to install?

### Key Boundary Rule

Runtime execution should not depend on a live Hub lookup.

The handoff should happen at installation time, not at task execution time.

That means:

- Hub may authenticate, authorize, and serve package artifacts
- Workspace installs a local copy of the artifact
- Workspace persists verified metadata on the local installation row
- Session runtime reads only local installation data and pinned snapshots

This is important for:

- Reproducibility
- Offline tolerance
- Performance
- Operational isolation
- Historical replay

### Official Hub Install Flow

Recommended flow:

1. A publisher account or organization owns a scope in Hub
2. The publisher releases `@scope/name@version`
3. Hub stores package metadata and artifact metadata
4. A workspace requests installation from Hub
5. Workspace downloads the artifact and verifies the Hub response
6. Workspace creates a local installation row
7. The local row is marked with:
   - `source = official_hub`
   - `trust_status = verified`
   - `trust_source = official_hub`
8. Agents bind that local installation
9. Releases and sessions pin the resolved local bundle

### Local Import Flow

Local import should remain a separate path:

1. User selects a folder or bundle
2. Workspace previews the manifest locally
3. Workspace shows claimed package identity and permissions
4. User grants trust
5. Workspace creates a local installation row
6. The local row is marked with:
   - `source = manual | bundle`
   - `trust_status = trusted_local`
   - `trust_source = local_import`

### Why This Split Matters

This separation prevents several long-term problems:

- Runtime does not need market availability to execute tasks
- Hub can evolve independently from agent orchestration internals
- Workspace keeps a complete audit trail of what was actually installed
- Verified Hub packages and trusted local packages can share one installation
  model without pretending they have the same provenance

## Artifact Storage And Runtime Materialization

Pivot should separate persisted extension artifacts from runtime extraction
directories.

Recommended model:

- Persisted artifact: the long-lived source of truth for one installed version
- Runtime materialization: a local extracted directory used for Python loading

Important rule:

- The extracted runtime directory should not be treated as the canonical stored
  package

Instead, installation should follow this shape:

1. Validate the local folder or bundle
2. Normalize the manifest
3. Build one archived artifact from the package contents
4. Persist that artifact through a storage backend
5. Materialize the archived artifact into a runtime directory
6. Persist installation metadata that points to both:
   - the artifact identity
   - the materialized runtime directory

Recommended persisted metadata:

- `artifact_storage_backend`
- `artifact_key`
- `artifact_digest`
- `artifact_size_bytes`
- `install_root`

Where:

- `artifact_*` identifies the persisted package bytes
- `install_root` identifies the current extracted runtime directory

Runtime services should be able to recreate `install_root` from the persisted
artifact whenever the local cache is missing. That keeps pod restarts and local
cache cleanup from breaking provider loading or extension runtime resolution.

This keeps the system compatible with:

- local development
- Kubernetes multi-replica deployment
- future object storage backends

### Development Backend

For local development, Pivot can persist artifacts to a local filesystem
backend under the workspace root.

Recommended development layout:

```text
server/workspace/
  extensions/
    acme/
      providers/
        1.0.0/
          artifact/
            <manifest_hash>.tar.gz
          runtime/
            manifest.json
            ...
```

Meaning:

- `extensions/.../artifact/` stores the persisted package archive
- `extensions/.../runtime/` stores the extracted runtime copy

Why this layout is preferable in local development:

- one package version lives under one obvious directory
- operators do not need to guess whether cleanup belongs under `artifacts/`
  or `extensions/`
- the runtime copy still remains a cache that can be recreated from the
  adjacent artifact when needed

### Production Backend

For production, Pivot should depend on an S3-compatible object storage backend.

The exact vendor does not need to be part of the extension contract.
Ceph, MinIO, RustFS, or any other S3-compatible backend should be acceptable as
long as the runtime depends only on object-storage semantics.

Recommended abstraction:

- `StorageBackend`
- `ArtifactStorageService`

Recommended built-in implementations:

- `LocalFilesystemStorageBackend` for development
- a future `S3CompatibleStorageBackend` for production

### Runtime Cache Rule

In multi-replica deployment:

- pods may materialize artifacts locally
- pods may discard and recreate materialized directories
- runtime should be able to rebuild the extracted directory from the persisted
  artifact at any time

This is one reason the artifact, not the extracted directory, should be the
source of truth.

## Supported Contribution Types

### Skills

Skills remain markdown-first assets. Each skill contribution points to a
directory containing a required `SKILL.md`.

Why this should stay strict:

- `SKILL.md` is the emerging common convention across agent tooling.
- Fixed naming simplifies editor, importer, validator, and packaging logic.
- It avoids unnecessary degrees of freedom that do not create product value.

Rules:

- `path` must point to a directory.
- That directory must contain `SKILL.md`.
- Additional files may exist as examples, templates, references, or helper
  scripts.

### Tools

Tool contributions point to Python entrypoints that expose tool metadata through
Pivot's tool decorator or a future extension-aware tool adapter.

Pivot should continue to support direct, lightweight tool registration outside
the extension package system. Package-based tools are optional and should be
used when a tool is part of a broader integration that benefits from shared
versioning, permissions, or release pinning.

This means Pivot supports two valid tool forms:

- Standalone tools registered the current lightweight way
- Tool contributions packaged inside an extension when bundling is useful

### Lifecycle Hooks

Hooks let extensions observe or influence execution at predefined lifecycle
events. Hooks must return structured effects instead of mutating runtime objects
directly.

### Channel Providers

Channel providers should move under the extension model, while still preserving
their provider manifest and protocol contract. This allows a channel adapter to
ship together with related tools or skills, and it gives provider integrations
the versioning and permission model they need.

### Web-Search Providers

Web-search providers should also become extension contributions so they can be
versioned, permissioned, and released consistently with the rest of the system.

## Dual Integration Model

Pivot should explicitly support two integration paths:

### Lightweight Asset Path

Best for:

- Small standalone tools
- Small standalone skills
- User-local or workspace-local experimentation
- Fast iteration with minimal packaging overhead

Characteristics:

- No package install step required
- Existing built-in, shared, and private resource patterns can remain valid
- Best suited to assets that do not need shared versioned release management

### Package Extension Path

Best for:

- Channel providers
- Web-search providers
- Lifecycle hooks
- Multi-capability integrations that combine providers, tools, and skills
- Integrations that need explicit permissions, release pinning, and upgrade
  management

Characteristics:

- Installed and versioned as one package
- Bound to agents through package-aware bindings
- Resolved into release/session snapshots as pinned bundles

This split is intentional. Pivot should not package simple things just because
packaging exists.

### Prompt Blocks

Prompt blocks are optional future contributions that inject reusable prompt
sections into the system prompt or task bootstrap prompt.

### Policies

Policy contributions are optional future modules that validate or constrain
runtime behavior, such as tool access, network usage, or output redaction.

## Lifecycle Model

Pivot already has a clear runtime hierarchy:

- Session
- Task
- Iteration

The extension system should align with these levels rather than inventing a new
parallel lifecycle.

### Session-Level Hooks

Recommended initial events:

- `session.created`
- `session.resumed`
- `session.closed`

Typical use cases:

- Initialize integration-specific session context
- Register session-scoped audit metadata
- Restore external conversation identifiers

### Task-Level Hooks

Recommended initial events:

- `task.before_start`
- `task.after_start`
- `task.waiting_input`
- `task.completed`
- `task.failed`
- `task.cancelled`

Typical use cases:

- Add task-specific prompt context
- Start external workflow tracking
- Persist integration-side checkpoints
- Trigger asynchronous follow-up actions

### Iteration-Level Hooks

Recommended initial events:

- `iteration.before_llm`
- `iteration.after_llm`
- `iteration.before_tool_call`
- `iteration.after_tool_result`
- `iteration.plan_updated`
- `iteration.answer_ready`
- `iteration.error`

Typical use cases:

- Add contextual annotations
- Validate tool calls before execution
- Enrich tool results after execution
- Produce structured audit events
- Attach answer metadata before the answer is emitted

## Hook Contract

Hooks should receive a structured, read-only context object instead of internal
ORM models or service instances.

Example context payload:

```json
{
  "session_id": "uuid",
  "task_id": "uuid",
  "trace_id": "uuid",
  "iteration": 3,
  "agent_id": 12,
  "release_id": 7,
  "extension": {
    "package_id": "@acme/providers",
    "version": "0.1.0"
  },
  "runtime": {
    "session_type": "consumer",
    "task_status": "running"
  },
  "event_payload": {},
  "deadline_ms": 5000
}
```

Hooks should return a list of effects.

Example:

```json
[
  {
    "type": "append_prompt_block",
    "payload": {
      "target": "task_bootstrap",
      "position": "head",
      "content": "Relevant account memory: prefers quarterly billing."
    }
  },
  {
    "type": "emit_event",
    "payload": {
      "type": "integration_notice",
      "data": {
        "vendor": "acme"
      }
    }
  }
]
```

## Effects Instead of Direct Mutation

This is a core architectural rule.

Extensions should not:

- Mutate ORM objects
- Call `db.commit()`
- Write arbitrary files under persistent storage
- Reach into supervisor internals
- Modify runtime messages in-place without mediation

Extensions should instead emit typed effects, and Pivot should apply those
effects through service-layer handlers.

Recommended initial effects:

- `append_prompt_block`
- `emit_event`
- `register_task_artifact`
- `request_user_action`
- `attach_answer_metadata`
- `schedule_async_followup`
- `block_action`
- `replace_action`

This keeps the extension ABI stable even if Pivot's internal implementation
changes.

Current implementation notes:

- `append_prompt_block` is now available for `task.before_start`
- The current supported target is `task_bootstrap`
- The current supported positions are `head` and `tail`
- This is the intended hook surface for external memory extensions to inject
  retrieved memory without mutating runtime state directly

## Runtime Resolution

### Installation

Installing an extension should:

1. Read and validate `manifest.json`
2. Validate the package folder layout
3. Validate all declared contribution entrypoints
4. Compute package hash and normalized contribution metadata
5. Register the installed package version
6. Make it available for agent bindings

### Binding

Installing a package must not automatically expose it to all agents.

Agent owners should create bindings that specify:

- Whether the extension is enabled
- Optional agent-local configuration
- Optional contribution allowlist override
- Priority ordering when multiple extensions contribute the same hook event
- Approved permissions if human confirmation is required

### Resolution

At runtime, Pivot should resolve the active extension set for an agent by
combining:

- Installed extension versions
- Agent bindings
- Release snapshot pinning
- Compatibility checks

The resolved result should become one immutable bundle description.

## Release Pinning

This is one of the most important requirements.

When a session is created, Pivot should pin:

- Extension package names
- Exact extension versions
- Resolved contribution metadata
- Effective permissions
- Agent binding configuration snapshot

This pinning should happen inside the session's release-bound runtime snapshot,
not as a best-effort lookup against the live extension registry.

Why this matters:

- Existing sessions must stay reproducible.
- Upgrading or uninstalling an extension must not silently alter historical
  sessions.
- Studio test sessions and published consumer sessions should behave similarly
  with respect to version freezing.

Recommended rule:

- New sessions use the latest extension versions permitted by the current agent
  release or draft.
- Existing sessions continue using their pinned extension bundle.

## Conflict Rules

Conflicts must be explicit.

Recommended rules:

- Tool names must be globally unique within one resolved bundle.
- Skill names must be globally unique within one resolved bundle.
- Channel provider keys should follow `scope@provider_name`.
- Web-search provider keys should follow `scope@provider_name`.
- Only one active version may provide the same provider key at runtime.
- Hook ordering must be deterministic when multiple extensions subscribe to the
  same event.

Suggested resolution order:

1. Binding priority
2. Explicit extension order on the agent
3. Extension name as a stable tie-breaker

If conflicts remain unresolved, runtime resolution should fail before session
creation or before publishing a release.

## Permissions Model

Permissions should be declared by the package and approved by the operator.

Recommended permission domains:

- Network host allowlist
- Secret access by key name
- Workspace read paths
- Workspace write paths
- Sandbox requirement
- Channel delivery access
- Web-search provider execution access

Two rules are important:

- Permissions are declared by the extension version.
- Effective permissions are granted by bindings and frozen into the resolved
  bundle.

This keeps security review package-centric while still allowing per-agent
approval.

## Service-Layer Persistence Rule

Pivot already has an important project rule: persistence access must go through
the service layer.

The extension system should preserve this rule by not exposing Pivot internals
directly to third-party code.

Pivot should not hand extension hooks raw database sessions or internal
services. Hook code should instead interact through:

- Lifecycle hook context
- Typed hook effects
- Optional narrow capability APIs when Pivot truly owns the underlying resource

For memory-style extensions, the preferred model is even cleaner:

- The extension reads runtime context from hooks
- The extension decides what memory to store or retrieve
- The extension persists memory in its own external system
- Pivot only receives a typed effect such as `append_prompt_block` to inject the
  retrieved memory into the task bootstrap prompt

This keeps the boundary clear:

- Pivot owns orchestration, effect application, and observability
- The extension owns memory extraction, recall, ranking, and storage strategy

## Development Workflow

Extension development should feel close to normal local development.

Recommended workflow:

1. Create an extension folder with `manifest.json`
2. Add contribution files under the standard directories
3. Run local validation against the manifest schema
4. Use Studio to install the local package into the workspace
5. Bind the extension to an agent draft
6. Run a Studio test session
7. Publish the agent release after validation

For external-service packages, the recommended layout is:

- `extensions/<name>/extension`
- `extensions/<name>/service`

Where:

- `extension` is the importable Pivot package
- `service` is the independently deployable HTTP backend

### Local Validation

Pivot should eventually provide validation commands for:

- Manifest schema validation
- Package layout validation
- Contribution entrypoint resolution
- Tool metadata validation
- `SKILL.md` validation
- Permission declaration validation
- Compatibility checks

### Studio Test

Studio Test should be the main debugging environment for extension behavior
before release. A test session should pin the draft-time resolved extension
bundle exactly the same way a release pins a production bundle.

## Debugging and Observability

Extension execution must be observable.

Each hook execution should record:

- Session ID
- Task ID
- Iteration
- Extension name and version
- Hook event name
- Historical hook context
- Start and end timestamps
- Duration
- Status
- Returned effects
- Error payload if any

This should support:

- Live debugging during Studio tests
- Post-failure inspection in Operations
- Replay of historical sessions and iterations

Studio should separate extension management from extension debugging:

- The workspace-level `Extensions` page should behave like an inventory and
  lifecycle management surface
- Each package `@scope/name` should have its own detail page
- Package detail should introduce the extension, list its contributions, and
  host extension-specific debugging tabs such as Hook Replay
- Operations should continue to expose session-first diagnostics and deep links
  into related hook executions

This keeps package browsing readable while preserving a clear home for
extension-level observability.

### Replay

Replay is especially valuable for lifecycle hooks.

Pivot should eventually support replaying a historical event such as:

- `task.before_start` from a failed task
- `iteration.after_tool_result` from a problematic recursion

The replay environment should use:

- The pinned extension bundle
- The historical event payload
- A safe replay mode that does not re-emit destructive side effects

Current implementation direction:

- Hook execution logs should persist the structured hook context so replay does
  not depend on reconstructing state from unrelated task rows
- Replay should target one exact hook callable, not rerun every hook subscribed
  to the same event
- Replay should remain read-only: it may return normalized effects for
  inspection, but it should not publish them back into the live event stream
- Hook context should declare `execution_mode = live | replay` so extensions
  can skip external writes during replay

## Install, Uninstall, Upgrade

### Install

Install registers one new package version. It should not overwrite prior
versions.

### Uninstall

Uninstall should be conservative.

Rules:

- If the package version is still referenced by a live session or published
  release, physical deletion should be blocked or deferred.
- The system may mark the extension version as inactive for future bindings
  while still retaining the artifact for pinned historical runtimes.

### Upgrade

Upgrade is install-plus-rebind, not in-place mutation.

Rules:

- Old versions remain available for pinned runtimes.
- New agent releases may opt into the new extension version.
- Existing sessions do not auto-upgrade.

## Publishing and Marketplace

The extension package model should support a future marketplace, but the local
workspace installer should come first.

Recommended extension lifecycle:

1. `draft`
2. `validated`
3. `submitted`
4. `approved`
5. `published`
6. `deprecated`
7. `yanked`

Recommended package checks before publication:

- Manifest and layout validation
- Compatibility validation
- Static lint and type validation
- Permission review
- Contribution conflict review
- Malware and unsafe-call scanning if external distribution is supported later

## Data Model Direction

The exact schema can evolve, but the package system likely needs these concepts:

- Installed extension package
- Installed extension version
- Extension contribution record
- Agent-extension binding
- Resolved extension bundle snapshot
- Extension execution log

One possible direction:

- `extension_package`
- `extension_version`
- `extension_contribution`
- `agent_extension_binding`
- `extension_hook_execution`

The key idea is more important than the exact table names:

- Installation records should be separate from agent bindings.
- Agent bindings should be separate from session-level pinned snapshots.
- Runtime execution logs should be append-only and queryable by session, task,
  iteration, and extension.

## Migration Strategy

Pivot should not migrate everything at once.

### Phase 1

Introduce the package model and local installer.

Scope:

- `manifest.json`
- Folder layout validation
- Package registry
- Agent bindings
- Release and session pinning

Existing built-in resources can remain implemented as they are, while being
represented in the new registry.

### Phase 2

Migrate provider-shaped integrations into extension packages.

Scope:

- Channel providers
- Web-search providers
- Provider-aware bindings and runtime resolution through packages

### Phase 3

Add packaged hooks and optional packaged tools/skills.

Scope:

- Lifecycle hooks
- Optional packaged tool bundles
- Optional packaged skill bundles

Tools and skills should still keep their standalone lightweight path after this
phase. Packaging remains additive, not mandatory.

### Phase 4

Add marketplace and richer governance.

Scope:

- Scope ownership and publisher identities
- Review workflows
- Package signing
- Public and private catalogs

## Design Decisions

### Decision 1: The manifest filename should be `manifest.json`

Reason:

- It is simple, familiar, and ecosystem-neutral.
- The directory itself already gives Pivot-specific context.
- A generic name is easier to explain and friendlier to future tooling.

### Decision 2: Skill entry files should be fixed to `SKILL.md`

Reason:

- A fixed convention is more valuable than configurable naming here.
- It matches broader agent-tooling expectations.
- It simplifies validation and editor behavior.

### Decision 3: One extension package may contain multiple contribution types

Reason:

- Real integrations often need multiple related capabilities.
- Packaging them together makes release management coherent.

Constraint:

- Contributions inside one extension should still form one logical product
  surface, not an arbitrary bundle of unrelated features.

### Decision 4: Tools and skills keep a lightweight standalone path

Reason:

- Many tools and skills are simple enough that packaging would add unnecessary
  friction.
- User-authored experimentation should stay cheap and fast.
- Packaging is most valuable for providers and richer integrations, not for
  every asset by default.

Constraint:

- Standalone tools and skills remain valid first-class assets.
- Packaged tools and skills are optional, additive forms.

### Decision 5: Providers should standardize on the extension package model

Reason:

- Providers have stronger needs around permissions, versioning, binding,
  release pinning, and operational governance.
- Standardizing providers reduces special-case runtime loading logic over time.

### Decision 6: Package identity should align with npm-style scopes

Reason:

- `@scope/name` is easier for developers to understand than a custom package
  naming scheme.
- Scope ownership maps cleanly to a future Hub or Market model.
- Keeping version separate from package name simplifies upgrade and release
  lineage.

### Decision 7: Local imports are trustable, not automatically verified

Reason:

- Before Hub exists, extensions will primarily arrive through local import.
- Operators need a clear trust boundary for self-claimed scopes.
- Future verified packages should build on the same identity model without a
  redesign.

### Decision 8: Sessions must pin resolved extension bundles

Reason:

- Reproducibility and debugging are more important than automatic drift to the
  latest extension version.

### Decision 9: Extensions return effects, not direct mutations

Reason:

- This preserves service-layer boundaries and keeps the extension ABI stable.

## Open Questions

- Should package configuration support JSON Schema-defined config forms in the
  manifest, or should binding config stay free-form in the first version?
- Should hooks be allowed to run asynchronously after the main task finishes, or
  should all first-version hooks be in-band only?
- Should extension artifacts live only on disk at first, or should the database
  also store compressed package snapshots for stronger reproducibility?
- Should built-in extensions be represented through the same installer and
  registry tables as third-party extensions from the beginning, or should that
  normalization happen in a second step?

## Recommended First Implementation Slice

The first production-worthy slice should be:

1. Package folder + `manifest.json`
2. Required `SKILL.md` convention for skill contributions
3. Installed package registry
4. Agent-extension bindings
5. Release/session bundle pinning
6. Optional tool and skill contribution loading from packages
7. Validation and conflict detection

This slice is enough to establish the right platform shape without forcing a
full rewrite of lightweight tools and skills in the same phase.
