# Channel Integration Design

## Purpose

This document defines the product and technical design for `Channel` in Pivot.

`Channel` means an external conversation entrypoint or delivery surface, such as
Work WeChat, Feishu, DingTalk, and Telegram. A channel allows users to talk to a
Pivot agent from a third-party platform while preserving Pivot's existing
scene-driven and ReAct-style interaction model.

This design focuses on two goals:

1. Third-party developers should be able to integrate and share a new channel in
   a standardized way.
2. End users should be able to bind a prebuilt channel to an agent with minimal
   setup effort.

---

## Current Target Channels

### Work WeChat

- Docs: <https://developer.work.weixin.qq.com/document/path/101463>
- Transport for V1: official websocket long connection
- Agent binding fields: `bot_id`, `secret`
- Notes: no callback URL, `corp_id`, `agent_id`, `corp_secret`, `token`, or
  `encoding_aes_key` should be required for this integration path

### Feishu

- Receive: <https://open.feishu.cn/document/server-docs/im-v1/message/events/receive>
- Send: <https://open.feishu.cn/document/server-docs/im-v1/message/create?appId=cli_a925547c1b7a9cef>

### DingTalk

- Enterprise bot via websocket
- Stream mode: <https://github.com/open-dingtalk/dingtalk-stream-sdk-python?spm=ding_open_doc.document.0.0.1a5d4a97DMmV9A>

### Telegram

- Polling via `getUpdates`
- Docs: <https://core.telegram.org/bots/api#getupdates>

These four channels are enough to shape the first version of the abstraction
because they cover webhook, websocket, and polling transport patterns.

---

## Product Goals

### User-facing goals

- Add `Channel` to the top navigation as a first-class catalog page, similar to
  `Agents`, `Tools`, and `Skills`.
- Show channels as cards because channels are preset integrations, not freeform
  code artifacts.
- Add `Channels` to the `AgentDetail` sidebar so one agent can bind one or more
  concrete channel configurations.
- Let users configure secrets and channel-specific settings without editing code.
- Let one channel definition be reused by many agents through separate bindings.

### Platform goals

- Make channel integration pluggable instead of hardcoding each provider into
  the agent runtime.
- Standardize inbound events, outbound messages, auth schema, capability
  discovery, and delivery semantics.
- Keep channel transport differences outside the core ReAct loop.
- Support future channel sharing and publishing, not only built-in channels.

### Non-goals for V1

- Full no-code marketplace with payments and ratings.
- Arbitrary multi-step workflow authoring inside the channel itself.
- A rich visual editor for channel payload templates before the base abstraction
  is stable.

---

## Core Design Principle

The most important split is:

1. `Channel Definition`: what a provider is and how it behaves.
2. `Agent Channel Binding`: how one specific agent uses one specific provider.

This split is required for extensibility.

If we only store "Feishu config" directly on the agent, every new channel will
force product, API, database, and UI changes. Instead, Pivot should treat a
channel like a provider plugin with metadata and a standard runtime adapter,
while the agent only stores bindings to that provider plus secrets/settings.

---

## Core Concepts

### 1. Channel Definition

A reusable provider definition shared by the system or by developers.

Suggested fields:

- `key`: globally unique stable identifier, such as `feishu_bot`
- `name`: display name
- `description`: short human-readable summary
- `icon`: icon URL or local asset path
- `status`: `active | beta | deprecated | disabled`
- `visibility`: `builtin | shared | private`
- `auth_schema`: form schema for required credentials
- `config_schema`: form schema for optional behavior settings
- `capabilities`: normalized capability flags
- `transport_mode`: `webhook | websocket | polling`
- `docs_url`: provider docs
- `provider_version`: semantic version of the adapter package
- `runtime_constraints`: retry, rate-limit, timeout, attachment support, and so on

### 2. Agent Channel Binding

A concrete configured connection between one agent and one channel definition.

Suggested fields:

- `id`
- `agent_id`
- `channel_key`
- `name`: user-facing alias such as `Sales Feishu Bot`
- `enabled`
- `auth_config`: encrypted secret payload
- `runtime_config`: non-secret behavior config
- `capability_overrides`: optional per-binding overrides
- `routing_rules`: optional future extension for scene-based routing
- `created_at`
- `updated_at`
- `last_health_status`
- `last_health_check_at`

Important rule:

- A single agent may have multiple bindings for the same channel definition.
  Example: one Feishu bot for production and another for internal testing.

### 3. Channel Session

A runtime conversation session mapped from a third-party thread or chat into a
Pivot conversation context.

Suggested fields:

- `channel_binding_id`
- `external_conversation_id`
- `external_user_id`
- `external_message_id`
- `pivot_conversation_id`
- `last_cursor`
- `session_state`

This layer is what keeps Telegram polling updates, Feishu message events, and
DingTalk stream events consistent from Pivot's point of view.

---

## Capability Model

Every provider should declare normalized capabilities so the product and runtime
can decide what is portable and what requires degradation.

Suggested baseline capabilities:

- `receive_text`
- `send_text`
- `receive_image`
- `send_image`
- `receive_file`
- `send_file`
- `receive_audio`
- `send_audio`
- `streaming_reply`
- `message_edit`
- `message_delete`
- `threading`
- `mention`
- `interactive_card`
- `button_callback`
- `user_profile_lookup`
- `webhook_verification`
- `history_pull`
- `typing_indicator`

Rules:

- Pivot core should rely only on baseline portable capabilities.
- Provider-specific rich features must be exposed as optional extensions.
- If a capability is unavailable, the adapter must degrade gracefully to plain
  text or no-op instead of leaking provider-specific behavior into the core loop.

---

## Product UX Design

### Top Navigation

Add `Channels` as a top-level navigation item.

Expected behavior:

- Clicking `Channels` opens a card-based catalog page.
- Each card shows icon, name, description, transport mode, auth type, and
  capability badges.
- Cards should clearly distinguish `Built-in`, `Shared`, and later `Private`
  definitions.
- Cards should expose quick actions such as `View`, `Bind to Agent`, and
  `Docs`.

Recommended page sections:

- `Official Channels`
- `Shared Channels`
- `Installed Private Channels` in a later phase

### Channel Detail Drawer or Page

Each catalog item should show:

- Provider overview
- Required credentials
- Supported capabilities
- Delivery mode
- Setup guide
- Supported ReAct compatibility notes
- Health check requirements

This is important because "connect channel" should feel operationally safe,
especially when credentials and callback URLs are involved.

### AgentDetail Sidebar

Add a new collapsible section: `Channels`.

Expected behavior:

- The section lists bound channel instances for the current agent, not the whole
  catalog.
- Each row represents one binding instance, not one channel type.
- Users can add a new binding from the preset catalog.
- Users can edit secrets and settings for an existing binding.
- Users can enable or disable a binding without deleting it.
- Users can test connection from the sidebar flow.

Recommended row content:

- Channel icon
- Binding name
- Channel type
- Enabled or disabled status
- Last health status
- Quick actions: `Edit`, `Test`, `Disable`, `Remove`

### Binding Flow

Recommended flow for users:

1. Open `AgentDetail`.
2. Open `Channels`.
3. Click `Add Channel`.
4. Select a preset channel definition from the catalog dialog.
5. Fill in an auto-generated config form from `auth_schema` and `config_schema`.
6. Run `Test Connection`.
7. Save the binding.

This should be materially easier than editing source files or adding custom
logic in prompt text.

---

## Standardized Developer Integration Model

Third-party developers should not need to patch the Pivot core each time they
add a channel. The recommended model is a provider package with two artifacts:

1. `manifest`
2. `adapter`

### Manifest

The manifest is declarative metadata used by the catalog page and the config UI.

Recommended manifest shape:

```json
{
  "key": "feishu_bot",
  "name": "Feishu",
  "description": "Receive and send direct messages through Feishu bot APIs.",
  "icon": "/channel-icons/feishu.svg",
  "visibility": "builtin",
  "transport_mode": "webhook",
  "docs_url": "https://open.feishu.cn/...",
  "capabilities": [
    "receive_text",
    "send_text",
    "interactive_card",
    "button_callback",
    "webhook_verification"
  ],
  "auth_schema": {
    "fields": [
      { "key": "app_id", "type": "text", "label": "App ID", "required": true },
      { "key": "app_secret", "type": "secret", "label": "App Secret", "required": true }
    ]
  },
  "config_schema": {
    "fields": [
      { "key": "verification_token", "type": "secret", "label": "Verification Token", "required": false }
    ]
  }
}
```

### Adapter Interface

The adapter is executable code that translates provider-specific behavior into
Pivot's channel contract.

Recommended Python interface:

```python
class BaseChannelAdapter(Protocol):
    def validate_binding(
        self, auth_config: dict[str, Any], runtime_config: dict[str, Any]
    ) -> None: ...

    async def healthcheck(
        self, binding: AgentChannelBinding
    ) -> ChannelHealthResult: ...

    async def register_endpoint(
        self, binding: AgentChannelBinding
    ) -> ChannelEndpointInfo | None: ...

    async def receive_event(
        self, request: ChannelInboundRequest
    ) -> list[ChannelInboundEnvelope]: ...

    async def send_actions(
        self,
        binding: AgentChannelBinding,
        actions: list[ChannelOutboundAction],
    ) -> list[ChannelDeliveryResult]: ...

    async def ack_event(
        self, envelope: ChannelInboundEnvelope
    ) -> None: ...
```

This interface keeps provider-specific logic isolated in one place:

- signature verification
- webhook challenge responses
- polling cursor handling
- websocket lifecycle
- outbound API formatting
- retry classification

### Developer Packaging and Sharing

Recommended long-term model:

- `builtin`: official channel providers shipped with Pivot
- `shared`: reusable channel providers published into a shared workspace catalog
- `private`: developer-local providers for experimentation

Recommended filesystem direction:

- Built-in providers: `server/app/channels/providers/<channel_key>/`
- User/shared providers later: `server/workspace/<username>/channels/<channel_key>/`

A provider package should contain:

- `manifest.json` or `manifest.py`
- `adapter.py`
- `README.md`
- optional `icon.svg`
- optional `tests/`

This makes channels closer to skills and tools conceptually, but with a stronger
runtime contract because channels own ingress and egress transport.

---

## Standardized User Integration Model

Users should not think in terms of provider code. They should think in terms of:

1. choose a channel
2. enter credentials
3. bind it to an agent
4. test it

To support this, the system should auto-generate the configuration experience
from provider metadata.

### Config Form Rules

- `auth_schema` renders secret-aware inputs
- `config_schema` renders normal settings
- secrets are masked after save
- fields can declare validation rules and help text
- fields can declare whether they are required only for certain transport modes

### Quality-of-life Features

- `Paste from provider console` friendly forms
- `Copy callback URL` for webhook providers
- `Test Connection`
- `Last event received`
- `Last message delivered`
- `Re-authorize` if credentials rotate

These features reduce channel setup friction much more than raw flexibility
alone.

---

## ReAct Compatibility Design

The core requirement is that a channel must not break Pivot's existing ReAct
interaction model.

The right approach is to standardize a channel message envelope and keep channel
adapters outside the reasoning loop.

### Inbound Envelope

All inbound provider events should be normalized into a common structure before
they enter the agent runtime.

Recommended shape:

```json
{
  "channel_key": "telegram_bot",
  "channel_binding_id": 12,
  "delivery_mode": "polling",
  "external_event_id": "8934234",
  "external_message_id": "8934234",
  "external_conversation_id": "chat_998",
  "external_user_id": "user_123",
  "message_type": "text",
  "text": "Help me book a demo",
  "attachments": [],
  "mentions": [],
  "timestamp": "2026-03-11T12:00:00Z",
  "raw_event": {}
}
```

### Runtime Mapping

The channel router should convert the inbound envelope into Pivot runtime input:

- identify the agent through `channel_binding_id`
- map provider thread to Pivot conversation/session
- convert message content into the same user-turn format that the current ReAct
  engine already consumes
- attach channel metadata as structured context, not as prompt-only text

Recommended contextual metadata available to the agent runtime:

- `channel.name`
- `channel.capabilities`
- `channel.user_id`
- `channel.conversation_id`
- `channel.message_id`
- `channel.is_group_chat`
- `channel.reply_constraints`

This allows scenes or tools to branch on channel metadata when necessary without
forcing provider-specific logic into the prompt itself.

### Outbound Action Model

The ReAct loop should not emit Feishu payloads or Telegram payloads directly.
It should emit provider-neutral actions.

Recommended baseline actions:

- `reply_text`
- `reply_image`
- `reply_file`
- `reply_audio`
- `show_typing`
- `request_human_handoff`
- `no_visible_reply`

Optional richer actions:

- `reply_card`
- `reply_buttons`
- `edit_reply`
- `delete_reply`

Adapter responsibility:

- map supported actions to native provider APIs
- degrade unsupported actions to supported equivalents
- return delivery status back to Pivot

Example:

- If an agent emits `reply_buttons` on Telegram and the adapter supports it,
  send native inline keyboard markup.
- If the same action is sent to a channel without button support, degrade to a
  numbered plain-text list.

This keeps ReAct portable while still allowing channel richness.

### Important Constraint

The agent should never be responsible for transport details such as:

- webhook verification handshake
- polling offsets
- websocket reconnects
- provider-specific message IDs
- API signing

Those belong to the channel adapter layer only.

---

## Backend Architecture

Recommended server modules:

- `server/app/channels/catalog.py`
- `server/app/channels/registry.py`
- `server/app/channels/base.py`
- `server/app/channels/router.py`
- `server/app/channels/providers/...`

Recommended responsibilities:

- `catalog`: load manifests for UI and APIs
- `registry`: resolve `channel_key -> adapter instance`
- `base`: shared types and abstract interfaces
- `router`: dispatch inbound events to the proper agent and runtime session
- `providers`: concrete Feishu, Telegram, Work WeChat, DingTalk adapters

### Recommended Database Additions

Use dedicated tables instead of overloading `agent.tool_ids` style fields.

Suggested tables:

#### `channel_definition`

Stores reusable metadata for installed providers.

Key columns:

- `key`
- `name`
- `description`
- `visibility`
- `manifest_json`
- `provider_version`
- `is_active`

#### `agent_channel_binding`

Stores one configured binding between an agent and a channel definition.

Key columns:

- `id`
- `agent_id`
- `channel_key`
- `name`
- `enabled`
- `auth_config_encrypted`
- `runtime_config_json`
- `health_status`
- `health_message`
- `created_at`
- `updated_at`

#### `channel_session`

Stores thread/session mapping.

Key columns:

- `id`
- `channel_binding_id`
- `external_conversation_id`
- `external_user_id`
- `pivot_session_key`
- `last_cursor`
- `last_seen_at`

#### `channel_event_log`

Optional but strongly recommended for observability and idempotency.

Key columns:

- `id`
- `channel_binding_id`
- `external_event_id`
- `direction`
- `status`
- `payload_json`
- `error_message`
- `created_at`

This table is valuable for debugging provider issues and preventing duplicate
delivery on webhook retries.

---

## API Design

Recommended catalog APIs:

- `GET /api/channels`
- `GET /api/channels/{channel_key}`

Recommended agent binding APIs:

- `GET /api/agents/{agent_id}/channels`
- `POST /api/agents/{agent_id}/channels`
- `PATCH /api/agent-channels/{binding_id}`
- `DELETE /api/agent-channels/{binding_id}`
- `POST /api/agent-channels/{binding_id}/test`
- `POST /api/agent-channels/{binding_id}/enable`
- `POST /api/agent-channels/{binding_id}/disable`

Recommended inbound event APIs:

- `POST /api/channel-endpoints/{binding_id}/webhook`
- `GET /api/channel-endpoints/{binding_id}/webhook` for providers with URL
  verification challenges

Recommended internal runtime APIs or services:

- `ChannelRouter.handle_inbound_event(...)`
- `ChannelDispatcher.send_outbound_actions(...)`

Important API rule:

- Catalog data and agent binding data must stay separate.

Why:

- Catalog data is public product metadata.
- Binding data includes secrets and operational health.

---

## Security and Secret Management

Channel integration introduces significantly higher operational risk than skills
or tools because the system accepts inbound traffic from external providers.

Minimum requirements:

- Encrypt `auth_config` at rest
- Mask secret fields in API responses
- Never inject raw secrets into prompts
- Verify provider signatures for webhook channels
- Store webhook challenge and verification metadata explicitly
- Add idempotency checks for retried events
- Log delivery failures without leaking tokens
- Scope credentials to binding instances, not global agent fields

Recommended future addition:

- Secret rotation support with `updated_by` and audit history

---

## Reliability and Observability

Channel systems are integration-heavy, so observability must be part of the
design rather than an afterthought.

Recommended features:

- binding-level health check
- event delivery logs
- retry status
- last successful inbound event time
- last successful outbound delivery time
- dead-letter queue or failure bucket in a later phase

Recommended adapter behavior:

- classify errors into `retryable` and `non_retryable`
- keep provider rate-limit details out of the agent logic
- standardize timeout and retry semantics per adapter

---

## UI and Data Modeling Recommendations for V1

To keep V1 implementable, the following choices are recommended:

### V1 Catalog Scope

- Only built-in preset channels are shown in the top-level `Channels` page.
- No user-authored channel provider editor yet.
- Channel detail is mostly metadata plus setup instructions.

### V1 Agent Binding Scope

- Support add, edit, delete, enable, disable, and test connection.
- Support one or more bindings per agent.
- Support secret fields and normal config fields.

### V1 Runtime Scope

- Standardize inbound text first.
- Standardize outbound text first.
- Add image/file/card support only after the base abstraction is stable.
- Support webhook and polling first if websocket support adds too much initial
  complexity.

This sequence reduces risk while keeping the design extensible.

---

## Recommended Rollout Phases

### Phase 1: Product and Metadata

- Add `Channels` navigation entry and card list page
- Add built-in channel catalog metadata
- Add `Channels` section in `AgentDetail` sidebar
- Add agent-channel binding CRUD

### Phase 2: Runtime Foundation

- Implement channel registry and adapter interface
- Implement session mapping and event log
- Support one webhook provider and one polling provider end to end

### Phase 3: Rich Capability Layer

- Add buttons, cards, attachments, and message edits where supported
- Add graceful degradation rules
- Add health dashboard improvements

### Phase 4: Ecosystem

- Add shared/private provider packaging
- Add developer publishing flow
- Add install/import flow for third-party channel packages

---

## Recommended Decisions

To keep the architecture clean, the following decisions are recommended now:

1. Treat `Channel Definition` and `Agent Channel Binding` as separate models.
2. Use schema-driven config forms instead of hardcoded per-channel forms.
3. Use a provider adapter interface so transport logic stays outside the ReAct
   engine.
4. Standardize inbound and outbound envelopes before they reach agent logic.
5. Store channel bindings in dedicated tables rather than on the `agent` record.
6. Start with built-in channels, but design the registry so shared/private
   channels can be added later without changing the core product model.

---

## Open Questions

These questions do not block the design, but should be settled before
implementation starts:

1. Should one external message always map to one Pivot conversation, or can one
   binding route into multiple scene-specific sessions?
2. Do we want channel-level access control by workspace, user, or both when
   shared channels arrive?
3. Should channel bindings support environment presets such as `dev`, `staging`,
   and `prod`?
4. Should provider packages be filesystem-based first, database-based first, or
   both?
5. Should rich provider features be exposed as optional tools, optional
   capabilities, or both?

---

## Summary

The right long-term model is not "add Feishu fields to agent". The right model
is a standardized channel platform:

- a reusable provider catalog
- schema-driven agent bindings
- a unified runtime adapter contract
- a provider-neutral message/action envelope compatible with ReAct

With this design, Pivot can add the current four target channels now and still
remain open for future third-party channel integrations without repeatedly
changing the product foundation.
