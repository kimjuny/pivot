# Extensions Externalization Design

## Background

Pivot now has two overlapping capability models:

1. Core-managed built-ins inside `/pivot`
2. Package-managed extensions inside `/extensions/extensions`

This overlap is acceptable for `Tool`, but it is increasingly confusing for provider-style capabilities such as:

- `Channel`
- `Web Search Provider`
- `Media Provider`
- `Skill`

The product direction for this initiative is:

- `Tool` is the only capability family that may remain built-in in Pivot core.
- All other capability families should converge toward extension ownership.
- Studio should show extension-origin capabilities in the corresponding top-level lists.
- Studio must not allow direct editing of extension-origin capabilities.

This document turns that direction into a phased implementation plan.

## Product Decisions

### 1. Studio top-level lists are inventory surfaces

The corresponding Studio pages should represent the currently available capability inventory, not only "things authored inside Pivot":

- `Channels`
- `Web Search Providers`
- `Media Providers`
- `Tools`
- `Skills`

If an installed extension contributes a capability that can actually be bound or used, the user should be able to see it in the relevant top-level list.

This is especially important because:

- `Media Providers` already follows this mental model.
- `Channels` and `Web Search Providers` already largely follow this model.
- If future `Channel` and `Web Search` providers are all externalized, hiding extension items would make those pages misleading or empty.

### 2. Extension-origin capabilities are read-only in Studio

Extension-managed rows must not be editable from Studio capability pages.

Allowed:

- inspect metadata
- search/filter
- view provenance
- bind/unbind to agents
- jump to owning extension package

Not allowed:

- inline source edits
- direct rename
- direct delete from capability page
- mutating configuration schema from Studio

Required editing workflow:

1. Modify extension source under `/extensions/extensions/...`
2. Test locally
3. Bump extension version
4. Import/install the new version into Pivot
5. Re-verify bindings and runtime behavior

This rule is important because otherwise the same capability would have two conflicting sources of truth:

- the installed extension artifact
- the mutable Studio state

That would quickly create version drift and make debugging impossible.

### 3. Only Tool remains built-in long-term

Target ownership model:

- `Tool`
  - may be `Built-in`
  - may be `Builder`
  - may be `Extension`
- `Skill`
  - may be `Builder`
  - may be `Extension`
- `Channel Provider`
  - target state: `Extension` only
- `Web Search Provider`
  - target state: `Extension` only
- `Media Provider`
  - target state: `Extension` only

Important transition note:

- existing non-tool built-ins may temporarily remain during migration
- existing non-tool builder-managed flows may temporarily remain if they already exist
- but we should not invest further in expanding those paths

The target architecture should be clear even if the transition takes multiple phases.

## Ownership Model

### Built-in

Definition:

- shipped inside `/pivot`
- upgraded only by updating Pivot itself

Long-term scope:

- `Tool` only

### Builder

Definition:

- created or imported by a builder inside Pivot and stored by Pivot services

Notes:

- `builder written` and `builder imported` share the same permission model
- they should be treated as one ownership source in the data model
- if we need provenance detail in UI later, that should be an `origin`-style display detail rather than a separate permission source

Long-term scope:

- `Tool` only
- `Skill` may continue to use this source during transition, but the target direction for Skills still prefers extension ownership

### Extension

Definition:

- loaded from an installed extension package
- versioned by the extension package
- source of truth lives in `/extensions/extensions/...`

Long-term scope:

- `Skill`
- `Channel Provider`
- `Web Search Provider`
- `Media Provider`
- extension-contributed `Tool`

## UI Model

## Capability Provenance

Every Studio inventory row/card for a capability should expose provenance explicitly.

Recommended fields:

- `Name`
- `Source`
- `From`
- `Description`

Where:

- `Source`
  - `Built-in`
  - `Builder`
  - `Extension`
- `From`
  - `Platform`
  - extension package name or display name
  - optional author/workspace origin for builder-owned assets

`Source` answers "what ownership bucket is this in?"  
`From` answers "who actually owns this specific thing?"

### Why not use `normal`?

`normal` does not communicate anything actionable.

The user needs to know at a glance:

- can I edit this here?
- if not, where do I go to change it?

`Built-in / Builder / Extension` answers that immediately.

## Page-by-Page Behavior

## Channels

Page role:

- inventory/catalog

Behavior:

- show all installed channel providers
- keep source filter
- show provenance on cards
- extension rows/cards are read-only
- actions should favor:
  - bind/configure usage
  - open owning extension

Long-term:

- no built-in channels remain

## Web Search Providers

Page role:

- inventory/catalog

Behavior:

- show all installed web-search providers
- keep source filter
- show provenance on cards
- extension rows/cards are read-only

Long-term:

- no built-in web-search providers remain

## Media Providers

Page role:

- inventory/catalog

Behavior:

- keep the current "installed providers are visible" model
- add any missing provenance/read-only consistency if needed

Long-term:

- extension-only family

## Tools

Page role:

- mixed inventory + authoring

Behavior:

- show all visible tools
- keep built-in and builder tools visible
- also show extension-origin tools
- expose `Source` and `From`
- allow editing only for editable rows

Edit rules:

- `Built-in`: read-only
- `Builder`: editable
- `Extension`: read-only

Rationale:

- Tool is the only family that still needs native Pivot authoring semantics
- but extension-contributed tools must still be visible and bindable from the same product surface

## Skills

Page role:

- inventory first, with external ownership as the target model

Behavior:

- show all visible skills, including extension-origin skills
- expose `Source` and `From`
- make extension-origin skills read-only
- allow builder-owned skills to remain editable by users who hold `edit`

Target direction:

- no new built-in skills
- no long-term investment in manual skill authoring
- skills should converge to extension ownership

If current builder-owned skills still exist during transition:

- keep them visible
- mark them clearly
- do not deepen that path further unless product direction changes

## Agent Configuration Surfaces

This includes:

- sidebar capability summaries
- bind dialogs
- selector modals such as `Configure Agent Tools` and `Configure Agent Skills`

Behavior:

- extension-origin capabilities must be visible and selectable
- provenance should be visible in selectors
- read-only source ownership does not block binding
- editing must never happen from these surfaces

In practice this means:

- sidebar summaries should include extension-contributed capabilities when bound
- selectors should include extension-contributed capabilities in the same list
- columns should include:
  - `name`
  - `type` or `source`
  - `description`

Recommended naming:

- prefer `source` semantics over vague `type`
- if UI copy must say `Type`, the values should still map to provenance:
  - `Built-in`
  - `Builder`
  - `Extension`

## Extension Auth and Lifecycle

## Resource permissions

Extension installations follow the same two Studio-side resource permissions as the rest of the user system:

- `use`
- `edit`

For extensions specifically:

- `use`
  - controls whether a builder can see, select, bind, and use the installed extension and its contributed capabilities in Studio
- `edit`
  - controls whether a builder can update the extension, import-overwrite it, pause it, resume it, uninstall it, or change its Auth settings

Important boundary:

- child capabilities contributed by an extension do not become directly editable just because the extension has an `edit` grant
- extension `edit` means "manage the installed extension"
- it does not mean "edit the child Tool/Skill/Provider definition inline from Studio"

If a builder wants to change an extension-contributed Tool, Skill, Channel Provider, Web Search Provider, or Media Provider, they must:

1. update the extension source
2. bump the version
3. import or update the extension installation

## Default Auth on import

Recommended default on first import/install:

- `use`: importer only
- `edit`: importer only

Reason:

- extension packages may carry secrets, provider schemas, hooks, and trusted runtime behavior
- conservative defaults are safer
- sharing can happen intentionally later via the `Auth` tab

## Single active version rule

Within one workspace, an extension package should have only one active installed version at a time.

Rules:

- upgrades are in-place
- runtime does not support long-lived multi-version coexistence
- Pivot should continue to evolve against the latest active extension version

This keeps the system simple and avoids dragging historical version compatibility rules into everyday runtime behavior.

## Upgrade and Uninstall Semantics

## Upgrade

An extension may be upgraded even when Agents already bind its contributed capabilities.

Upgrade is allowed as long as the builder explicitly confirms the impact.

After a successful in-place upgrade:

- the extension installation keeps its existing `use/edit` Auth settings
- existing Agent bindings remain attached as long as their stable capability keys still exist
- bindings that survive key-wise but no longer satisfy the new schema move into `needs_reconfiguration`

Upgrade should not be blocked just because:

- some Agent currently binds the extension
- some historical session once used the extension

## Uninstall

Uninstall should be stricter than upgrade.

Recommended rule:

- uninstall is blocked when any saved Agent binding still depends on the extension

Rationale:

- upgrade preserves continuity by replacing the existing installed artifact
- uninstall removes the capability family entirely and is therefore a much harder break

## Impact check

Every upgrade should run an explicit impact check before execution.

Impact check should inspect at least two layers:

1. configuration impact
2. runtime impact

### Configuration impact

The primary dependency signal is saved Agent configuration, not transient runtime activity.

In this design, "currently used by an Agent" means:

- the Agent has a saved binding or saved capability reference that depends on the extension

It does not mean:

- a historical session once used it
- a user is merely online
- a task happened to use it in the past

### Runtime impact

Upgrade must also inspect currently running tasks for affected Agents.

Reason:

- a task must not lose a capability halfway through execution because the extension changed underneath it

## Runtime snapshot rule

Pivot should not do long-lived multi-version runtime coexistence, but each running task should keep the environment snapshot it started with.

Rules:

- a running task keeps using the capability resolution snapshot captured at task start
- extension upgrade affects only later requests and later tasks
- this avoids mid-task capability disappearance

This is a task-level stability rule, not a general multi-version support model.

## Upgrade modes

Two upgrade execution modes are acceptable:

- `safe upgrade`
- `force upgrade`

## Upgrade interaction entrypoint

The primary choice between `safe upgrade` and `force upgrade` should happen in the extension import/install flow, not as a standalone action buried inside Extension detail.

Recommended interaction:

1. builder imports an extension package
2. Pivot parses the manifest
3. Pivot detects whether this is:
   - a new install
   - a reinstall of the same version
   - a higher-version upgrade
   - a lower-version downgrade
   - an invalid/conflicting package
4. if it is a higher-version upgrade, the install confirmation dialog becomes an upgrade decision dialog

In that upgrade decision dialog, Pivot should show at least:

- current installed version -> incoming version
- affected Agent count
- currently running task count
- bindings that will need reconfiguration
- removed capabilities
- added capabilities
- any explicit breaking schema/config changes

Actions in that dialog:

- `Cancel`
- `Safe upgrade`
- `Force upgrade`

In upgrade scenarios, the primary action label should not remain a generic `Install`.  
The dialog should present an explicit upgrade choice.

## Upgrade progress surface

After the builder chooses `safe upgrade`, the original import/install decision step is complete.

At that point, progress observation and later escalation to `force upgrade` should move to a dedicated upgrade-progress surface, rather than keeping the original confirm dialog open as a long-lived control panel.

Recommended surfaces:

- Extension detail top banner/panel
- or a dedicated upgrade progress screen

That progress surface should show:

- elapsed waiting time
- affected Agent count
- remaining running task count
- per-Agent draining visibility
- `Force upgrade now`
- `Cancel draining`

### Safe upgrade

Recommended default.

Behavior:

- after confirmation, affected Agents immediately stop accepting new client-side work
- let already-running tasks drain using their startup snapshot
- switch the extension only after the drain point is reached

Additional interaction rules:

- the upgrade should execute automatically once the running-task count reaches `0`
- Studio-side test chat should not start new work during `draining_for_upgrade`
- if the builder cancels draining before the version switch happens, affected Agents return to their prior client-serving state

### Force upgrade

Allowed, but explicitly risky.

Behavior:

- builder may proceed without waiting for full drain
- Pivot must warn that currently running work may fail or be interrupted

## Affected Agent state

After impact check completes, if the builder proceeds with either safe or force upgrade, all affected Agents should immediately enter a visible upgrade-related state.

This design intentionally separates Agent state into two dimensions rather than one giant `status` enum.

## Agent state model

### Dimension 1: release state

Agent release state answers:

- does this Agent currently have a published release for end users?

Recommended representation:

- existing `active_release_id`

Interpretation:

- `active_release_id = null` -> draft-only / not published
- `active_release_id != null` -> published

### Dimension 2: client serving state

Client serving state answers:

- can this Agent currently accept new client-side work?

Recommended dedicated field:

- `client_state`

Recommended values:

- `open`
- `paused`
- `draining_for_upgrade`
- `upgrade_required`

Why this split matters:

- release state and serving state describe different concerns
- combining them into a single flat status enum quickly becomes hard to reason about
- the current system already hints at this split through `active_release_id` plus `serving_enabled`

### Recommended combinations

Common combinations:

- draft-only + `open`
  - Studio can work with the Agent, but Client cannot because nothing is published yet
- published + `open`
  - normal client-serving state
- published + `paused`
  - published, but manually closed to new client work
- published + `draining_for_upgrade`
  - safe upgrade is waiting for running tasks to finish
- published + `upgrade_required`
  - upgrade finished, but builder review is still required before reopening to clients

`upgrading` itself should usually be treated as an extension-upgrade job state, not a long-lived persisted Agent serving state.

Recommended state name:

- `upgrade_required`

Meaning:

- this Agent depends on an extension that has changed
- builder review and validation is required before the Agent is reopened to client traffic

Behavior while `upgrade_required`:

- Client side does not accept new tasks
- Client side should surface a clear "Agent is being upgraded" notice
- Studio `AgentDetail` remains available
- Studio-side test chat and debugging remain available
- builder may repair bindings, fill new config fields, and validate behavior

Behavior while `draining_for_upgrade`:

- Client side does not accept new tasks
- Client side should surface a clear "Agent is preparing for an upgrade" notice
- already-running tasks continue using their startup snapshot
- Studio `AgentDetail` remains available
- Studio-side test chat should not create new runtime work during the drain window

This state is important because it prevents a half-upgraded Agent from appearing usable to end users.

## AgentDetail behavior after extension change

AgentDetail does not own extension version switching, but it must surface the consequences of an extension upgrade.

Required behaviors:

- show that the Agent is currently in `upgrade_required`
- show which bindings or capabilities are affected
- provide entry points to reconfigure those bindings

If a provider schema changes, for example from two required fields to three:

- the existing binding remains attached to the Agent
- the binding becomes `needs_reconfiguration`
- AgentDetail shows a clear warning
- the relevant configuration dialog renders the new schema
- the binding cannot be used for new runtime work until the configuration is completed again

## Publish flow after upgrade

`upgrade_required` should not be cleared by a draft save or by successful Studio-side test chat alone.

The intended recovery flow is:

1. extension upgrade finishes
2. affected Agent enters `upgrade_required`
3. builder repairs configuration and validates behavior inside Studio
4. builder publishes a new Agent release through the existing publish flow
5. successful publish reopens the Agent to client traffic

This means:

- a new release is required before the Agent can serve clients again
- reopening client traffic should remain tied to the normal publish model
- the Agent should not have a separate "resume without publish" shortcut for this case

Recommended Studio cue:

- place a gentle, dismissible tooltip or hint next to the `Publish` action
- example message:
  - `A new release is required before this agent can serve clients again.`

Important detail:

- dismissing the tooltip only hides the hint
- it does not remove `upgrade_required`
- it does not restore client traffic

Even after the tooltip is dismissed, Publish should still carry a light persistent state cue such as:

- `Republish required`

## Publish gating rule

When an Agent is `upgrade_required`, a successful publish should become the only path back to `client_state = open`.

Minimum publish gate:

- no remaining `needs_reconfiguration` bindings

Recommended publish result:

- create a new Agent release version
- move `active_release_id` to the new release
- clear upgrade-related review flags
- set `client_state = open`

## Session impact and migration

Session continuation should follow Agent release version strictly.

### Latest-release-only rule

Once an extension upgrade causes an affected Agent to be repaired and republished, only sessions created from the latest published Agent release may continue starting new tasks.

In other words:

- a session is allowed to start a new task only when its Agent release version matches the Agent's latest published release version
- if the session belongs to an older Agent release version, it must migrate

This intentionally simplifies compatibility handling by making release version the hard boundary.

### Stale session rule

A session becomes `stale` when its Agent release version is no longer the latest published release for that Agent.

Recommended behavior:

- stale sessions cannot continue normal client-side conversation
- client should show a blocking dialog
- dialog actions:
  - `Close`
  - `Migrate`

### Migrate action

First version of migration should stay simple:

1. create a new session
2. copy the old session sandbox `/workspace/` contents into the new session
3. attach the new session to the current environment
4. keep the old session as read-only history

Optional future enhancement:

- compact and carry forward selected conversational context

### Client messaging

Client should not merely say "this session is old."

It should explain that:

- the Agent has been republished with a newer release
- a new session is required to continue safely

## Current Architecture Notes

From current codebase inspection:

- provider extension loading infrastructure already exists in `provider_registry_service.py`
- `Channels`, `Web Search Providers`, and `Media Providers` are already close to inventory semantics
- `Tools` and `Skills` are still more editor-oriented than inventory-oriented
- built-in channel providers currently live in `pivot/server/app/channels/providers.py`
- built-in web-search providers currently live in:
  - `pivot/server/app/orchestration/web_search/providers/baidu/provider.py`
  - `pivot/server/app/orchestration/web_search/providers/tavily/provider.py`

This means the highest-value work is not "invent extension loading", but:

1. align Studio semantics
2. move concrete providers into extension packages
3. retire core registrations only after the extension path is proven

## Externalization Scope

The first concrete migrations requested are:

- `Baidu` as a `Web Search Provider`
- `Tavily` as a `Web Search Provider`
- `Work WeChat` as a `Channel`
- `Feishu` as a `Channel`
- `Telegram` as a `Channel`
- `DingTalk` as a `Channel`

Target directories:

- `/extensions/extensions/baidu`
- `/extensions/extensions/tavily`
- `/extensions/extensions/wechat`
- `/extensions/extensions/feishu`
- `/extensions/extensions/telegram`
- `/extensions/extensions/dingtalk`

Recommended package ids:

- `@pivot/baidu`
- `@pivot/tavily`
- `@pivot/wechat`
- `@pivot/feishu`
- `@pivot/telegram`
- `@pivot/dingtalk`

Recommended stable provider keys:

- `baidu`
- `tavily`
- `work_wechat`
- `feishu`
- `telegram`
- `dingtalk`

The stable key should not change during migration.  
The ownership source changes; the runtime identity should not.

## Target Package Layout

## Web Search Provider packages

```text
extensions/extensions/baidu/
  manifest.json
  README.md
  logo.svg
  web_search_providers/
    baidu/
      provider.py
```

```text
extensions/extensions/tavily/
  manifest.json
  README.md
  logo.svg
  web_search_providers/
    tavily/
      provider.py
```

Each package contributes exactly one provider.

## Channel packages

```text
extensions/extensions/wechat/
  manifest.json
  README.md
  logo.svg
  channel_providers/
    work_wechat.py
```

```text
extensions/extensions/feishu/
  manifest.json
  README.md
  logo.svg
  channel_providers/
    feishu.py
```

```text
extensions/extensions/telegram/
  manifest.json
  README.md
  logo.svg
  channel_providers/
    telegram.py
```

```text
extensions/extensions/dingtalk/
  manifest.json
  README.md
  logo.svg
  channel_providers/
    dingtalk.py
```

Each package contributes exactly one provider.

## Phased Implementation Plan

## Phase 1: Inventory and Read-Only Semantics

### Objective

Make Studio represent extension ownership correctly before more built-ins are moved out of core.

### Scope

- top-level capability lists
- agent selector dialogs
- backend source/read-only semantics

### Frontend work

1. Show extension-origin tools and skills in their top-level pages.
2. Add provenance fields to Tools and Skills lists.
3. Ensure existing provider pages consistently display extension provenance.
4. Hide or disable edit/delete actions for extension-origin rows.
5. Add an "Open Extension" or equivalent affordance where useful.
6. Ensure agent binding dialogs list extension-origin tools/skills/providers.

### Backend work

1. Provide inventory endpoints that return visible capabilities plus provenance metadata.
2. Distinguish "visible in inventory" from "editable in Studio".
3. Enforce server-side immutability for extension-origin capabilities.
4. Return enough metadata for Studio to render provenance cleanly:
   - `source`
   - `from`
   - `read_only`
   - `extension_package_id`
   - `extension_version`

### Acceptance criteria

- installed extension capabilities appear in the correct top-level Studio lists
- extension-origin rows are visibly read-only
- selector dialogs show the same extension-origin rows
- API mutation attempts against extension-origin capabilities are rejected

## Phase 2: Externalize Baidu and Tavily

### Objective

Move the two built-in web-search providers into extension packages while preserving behavior.

### Source code to migrate

- `pivot/server/app/orchestration/web_search/providers/baidu/provider.py`
- `pivot/server/app/orchestration/web_search/providers/tavily/provider.py`

### Work

1. Create `/extensions/extensions/baidu`.
2. Create `/extensions/extensions/tavily`.
3. Add `manifest.json`, `README.md`, and `logo.svg` to each package.
4. Move or copy the provider implementation into each extension package.
5. Ensure each package exports its provider in the format expected by the current extension loader.
6. Import/install the package into Pivot.
7. Verify:
   - extension appears in Extensions page
   - provider appears in Web Search Providers page
   - provider appears in agent binding flows
   - provider can execute runtime requests

### Migration rule

Do not delete the built-in provider registration in the same first extraction step unless the extension path has already been proven in a running environment.

Recommended order:

1. package exists
2. package imports cleanly
3. package appears in inventory
4. package executes successfully
5. built-in registration is retired

## Phase 3: Externalize Work WeChat, Feishu, Telegram, DingTalk

### Objective

Move the built-in channel providers into extension packages while preserving runtime behavior.

### Source code to migrate

Primary source:

- `pivot/server/app/channels/providers.py`

Additional Work WeChat helper code:

- `pivot/server/app/channels/work_wechat_socket.py`

### Work

1. Create the four extension packages.
2. Move each provider implementation into its own package entrypoint.
3. Keep provider-specific helper code package-local where possible.
4. Preserve provider schema:
   - stable provider key
   - display name
   - auth fields
   - validation rules
   - setup instructions
   - runtime capabilities
5. Import/install each package.
6. Verify:
   - inventory listing
   - binding flows
   - credential validation
   - inbound/outbound runtime behavior

### Special note for Work WeChat

`work_wechat_socket.py` is provider-specific enough that the first migration should prefer packaging that logic with the Work WeChat extension, instead of inventing a shared abstraction too early.

The default bias should be:

- duplicate a little
- keep ownership obvious
- avoid cross-extension shared runtime unless it is clearly justified later

## Phase 4: Retire Built-In Non-Tool Providers

### Objective

Make extension packages the only source of non-tool providers.

### Work

1. Remove built-in channel provider registrations from core runtime registries.
2. Remove built-in web-search provider registrations from core runtime registries.
3. Keep tool built-ins intact.
4. Update empty-state and help text to reflect the new model:
   - "install an extension" instead of "feature unavailable"

### Acceptance criteria

- normal operation no longer requires built-in non-tool providers
- all supported non-tool providers are resolved from installed extensions
- Studio copy matches the new mental model

## Phase 5: Skills Convergence

### Objective

Align `Skill` with the same external-only direction as providers.

### Scope

- stop treating built-in/builder skill authoring as a strategic path
- keep skills visible in inventory
- make extension ownership explicit

### Work

1. Audit whether any built-in skills remain in active product use.
2. Keep them working only as a transition measure if necessary.
3. Make extension-origin skills first-class in list and binding surfaces.
4. Avoid expanding builder/built-in skill investment further unless product direction changes.

This phase is intentionally separate because the current conversation named concrete provider migrations first, and those have a clearer operational path.

## Data and API Design

## Inventory response shape

For any capability surfaced in Studio inventory, the response should be able to express:

- stable id
- capability key or name
- description
- source
- from
- read_only
- extension package id
- extension version

This should be standardized as much as possible across:

- tools
- skills
- channels
- web-search providers
- media providers

## Mutation rules

Server-side services must reject writes to extension-origin capabilities.

The UI should not be the only guardrail.

Examples of actions that should fail for extension-origin capabilities:

- update metadata
- rename
- delete
- mutate auth/config schema definition

The error should clearly instruct the user to update the owning extension package instead.

## Migration Safety Rules

## Stable keys must not drift

When moving built-ins into extension packages, the provider key should stay the same.

Examples:

- `work_wechat` stays `work_wechat`
- `baidu` stays `baidu`

This reduces rebinding risk and keeps agent/runtime references stable.

## No silent duplicate resolution

During migration, a built-in and extension item may temporarily want the same stable key.

We should not rely on silent precedence.

Recommended rule:

- detect the conflict explicitly
- guide the operator through migration
- keep final runtime ownership singular

## Tests and Verification

Each migration phase should verify three levels:

1. Inventory
   - capability appears in Studio list
   - provenance is correct
   - extension-origin row is read-only

2. Binding
   - capability appears in agent configuration dialog
   - capability can be selected and persisted

3. Runtime
   - provider/tool/skill actually executes as expected

For the named providers:

- `Baidu` and `Tavily` must pass runtime web-search verification
- `Work WeChat`, `Feishu`, `Telegram`, and `DingTalk` must pass connection and send/receive verification appropriate to their transport mode

## Risks

### Risk: duplicate registrations during migration

If both built-in and extension variants of the same provider key are active, resolution may become ambiguous.

Mitigation:

- explicit conflict handling
- phased rollout
- one provider family at a time

### Risk: UI says read-only but API still mutates

Mitigation:

- enforce source-based immutability in services and API

### Risk: Tools page and Skills page become conceptually inconsistent

Mitigation:

- make provenance explicit
- separate inventory semantics from edit semantics
- accept that `Tools` is mixed-mode while `Skills` moves toward extension-only

## Recommended Delivery Order

1. Phase 1: inventory and read-only semantics
2. Phase 2: Baidu and Tavily extensionization
3. Phase 3: channel provider extensionization
4. Phase 4: built-in non-tool provider retirement
5. Phase 5: skill model convergence

## Recommendation

This work should be implemented in phases, not as one large cutover.

The best immediate path is:

1. make Studio ownership semantics correct
2. externalize `Baidu` and `Tavily`
3. externalize `Work WeChat`, `Feishu`, `Telegram`, and `DingTalk`
4. retire built-in non-tool providers only after the extension path is proven

That sequence matches your long-term architecture while keeping the migration understandable, testable, and reversible at each step.
