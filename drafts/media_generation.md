# Image Generation Design

## Goal

Add image-generation and image-editing capabilities that agents can call at
runtime, while keeping Pivot's existing architectural boundaries intact:

- agents call tools, not raw vendor APIs
- persistence stays behind service-layer APIs
- provider secrets stay under platform-managed bindings
- generated images land in the agent workspace and can be returned as answer
  attachments
- usage and cost-related metadata can be tracked in one consistent place

This draft captures the current design consensus before implementation.

## Current Consensus

### Primary runtime model

Image generation should be integrated as:

- agent-facing tools
- platform-managed image providers and provider bindings
- provider-specific adapters contributed by extensions

The preferred runtime chain is:

```text
Agent
  -> image tool
  -> ImageGenerationService
  -> provider binding resolution
  -> provider adapter
  -> vendor API
  -> workspace artifact persistence
  -> answer attachments
```

### What image generation is not

Image generation should **not** be modeled as a new protocol on the existing
`LLM` entity.

Why:

- the current `LLM` abstraction is chat-oriented and built around
  `chat/chat_stream`
- ReAct already expects external side effects to happen through tools
- image generation needs secret injection, vendor task orchestration, usage
  tracking, and workspace artifact persistence, which are not natural
  responsibilities of the existing chat-LLM transport layer

This means the platform should keep:

- `LLM`: chat reasoning transport
- `Image Provider`: image capability transport

They are sibling concepts, not one overloaded concept.

## Design Principles

- Agent-facing invocation should be tool-first.
- Provider configuration should be platform-managed, not buried inside tool
  source files.
- Extension packages may contribute provider-specific tools and provider
  adapters in the same package.
- Tool parameters should match the intended capability level:
  vendor-specific tools may expose vendor-specific parameters.
- Secret handling, binding resolution, usage logging, and workspace writes
  should stay in Pivot server services.
- Async vendor task orchestration should be owned by service-layer policy, not
  hidden inside provider adapters.

## Core Vocabulary

### Image Provider

One runtime capability implementation that knows how to call one vendor image
 API or one vendor image capability family.

Examples:

- `wan2_7`
- `qwen_image_edit`
- `jimeng_v4`

### Provider Adapter

Python implementation that translates Pivot's internal request objects into one
vendor's API calls and translates responses back into Pivot's internal result
objects.

### Provider Binding

The per-agent persisted configuration that enables an image provider and stores:

- secret auth config
- runtime config
- priority and enablement
- optional health metadata

### Vendor Tool

An agent-facing tool exposed by one extension. Vendor tools may expose strong,
vendor-specific parameters.

Examples:

- `wan2_7_generate_image`
- `wan2_7_edit_image`

### ImageGenerationService

Platform-owned orchestration service that:

- resolves bindings
- injects provider config
- executes provider operations
- handles async polling strategy
- stores generated artifacts into the workspace
- records usage

## Recommended Product Shape

## Option Summary

The platform should support both of the following, but the first one is the
recommended first milestone:

- vendor-specific extension tools plus provider adapters
- later, optional generic cross-provider image tools if product demand appears

## First milestone

The first milestone should prioritize vendor-specific packages.

Example:

- one `wan2_7` extension contains:
  - vendor-specific image tools
  - one provider adapter implementation

This avoids pretending that all vendors share one stable parameter surface.

## Why vendor-specific tools are acceptable

For image generation, vendors often differ in:

- async vs sync execution
- supported operations
- width and height controls
- aspect ratio controls
- watermark or no-watermark options
- masks, reference images, background generation, style presets, and edit modes

If a tool is explicitly vendor-specific, exposing that vendor's stronger
parameter surface is acceptable and often desirable.

The tool name should make the scope clear.

Good:

- `wan2_7_generate_image`
- `jimeng_v4_generate_image`

Not recommended as the first step:

- one giant `generate_image(...)` tool with every vendor parameter mixed in

## Extension Model

One extension package may contribute both:

- tools
- image providers

That is a good fit for Pivot's existing extension model because one package is
already the versioned unit of runtime capability.

Recommended direction for a future manifest shape:

```json
{
  "schema_version": 1,
  "scope": "aliyun",
  "name": "wan2_7",
  "display_name": "Alibaba Wan 2.7",
  "version": "0.1.0",
  "description": "Wan 2.7 image generation and editing tools.",
  "contributions": {
    "image_providers": [
      {
        "provider_key": "wan2_7",
        "name": "Wan 2.7",
        "entrypoint": "providers/wan2_7.py"
      }
    ],
    "tools": [
      {
        "name": "wan2_7_generate_image",
        "entrypoint": "tools/wan2_7_generate_image.py"
      },
      {
        "name": "wan2_7_edit_image",
        "entrypoint": "tools/wan2_7_edit_image.py"
      }
    ]
  }
}
```

Notes:

- `provider_key`, not `extension_key`, should be the runtime identifier for the
  provider capability
- the extension remains the packaging and versioning unit
- the provider remains the runtime capability unit

## Runtime Boundaries

## Tool layer

Image tools should be registered as `tool_type="normal"`.

They should **not** be `sandbox` tools because they need:

- provider binding resolution
- access to server-side services
- secret injection
- usage persistence
- vendor network calls

`tool_type` should continue to mean execution environment, not capability
category.

Therefore:

- `normal`: server-side execution
- `sandbox`: workspace/sandbox-side execution

If the product later needs a UI/category distinction for image tools, add a
separate metadata field such as:

- `capability = "image_generation"`
- or `categories = ["image"]`

Do **not** overload `tool_type` with values such as `image`.

## Service layer

The image invocation chain should be explicit in tool code, not discovered via
`tool_type`.

In other words:

- a normal image tool should call `ImageGenerationService`
- the service should handle the rest of the chain

The system should not rely on a magic `tool_type=image` dispatch rule.

## Provider adapter layer

Provider adapters should not own database access, usage logging, or workspace
artifact persistence.

They should focus on vendor protocol translation only.

## Persistence layer

Persistence should stay inside platform services under `server/app/services`.

Tools should not pass ORM rows or database sessions into provider code.

Tools should only pass plain values and execution context.

## Recommended Data Model

## Provider binding

Add a new persisted model similar in spirit to channel and web-search bindings.

Suggested name:

- `AgentImageProviderBinding`

Suggested fields:

- `id`
- `agent_id`
- `provider_key`
- `extension_installation_id`
- `enabled`
- `priority`
- `auth_config`
- `runtime_config`
- `last_health_status`
- `last_health_message`
- `last_health_check_at`
- `created_at`
- `updated_at`

### Why this should not reuse extension binding config directly

Extension installation and binding config are good package-level configuration
surfaces, but image provider runtime needs platform-level behavior around:

- auth secret handling
- health checks
- usage tracking
- provider-level routing

That is closer to channel/web-search provider bindings than to a generic
extension config blob.

### Secret handling

The platform should not treat extension `secret` fields as sufficient long-term
secret infrastructure.

Current extension config fields may render as password inputs in the UI, but the
backend still persists config as normal JSON text. That is not the final target
for provider secrets.

The image provider binding model should mirror the channel/web-search pattern:

- `auth_config` for secrets
- `runtime_config` for non-secret options

Release snapshots and history UIs should store secret hashes and key names, not
raw secret values.

## Usage log

Add a dedicated usage log model.

Suggested name:

- `ImageGenerationUsage`

Suggested fields:

- `id`
- `task_id`
- `session_id`
- `agent_id`
- `user`
- `provider_key`
- `model`
- `operation`
- `status`
- `provider_request_id`
- `provider_task_id`
- `image_count`
- `output_width`
- `output_height`
- `latency_ms`
- `usage_json`
- `billing_units`
- `estimated_cost`
- `error_json`
- `created_at`
- `updated_at`

This log should be owned by the service layer, not by tool code or provider
adapters.

## Workspace artifact output

Generated images should be persisted into the task workspace by server-side
services, then returned to the agent as `/workspace/...` paths.

Recommended behavior:

- server receives image bytes or result URLs
- server downloads or materializes the artifact
- server writes the artifact into the bound workspace backend
- the returned artifact path is a stable sandbox-visible path such as:
  `/workspace/.pivot/generated/images/...png`

This lets the agent:

- inspect the file later through normal file tools
- attach it in `ANSWER.output.attachments`
- keep one consistent artifact story with the existing task attachment pipeline

## Interface Design

## Tool interface

Vendor-specific tools may expose vendor-specific arguments.

Example shape:

```python
@tool(tool_type="normal")
def wan2_7_generate_image(
    prompt: str,
    width: int | None = None,
    height: int | None = None,
    watermark: bool | None = None,
    output_path: str | None = None,
) -> str:
    ...
```

Guidelines:

- the tool name must clearly communicate that it is vendor-specific
- the tool may expose stronger vendor parameters
- the tool should remain thin and should not own persistence or routing logic

## Tool input to service

Tools should pass plain values only.

Recommended service call inputs:

- `agent_id`
- `workspace_id`
- `username`
- `workspace_backend_path`
- `provider_key`
- `operation`
- `arguments`

Tools should not:

- query the database directly
- pass ORM entities into the service
- resolve bindings on their own

## Provider adapter interface

Provider adapters should declare:

- `provider_key`
- `supported_operations`
- optional capability metadata

Recommended adapter shape:

```python
class AbstractImageProvider(ABC):
    provider_key: str

    @abstractmethod
    def start(self, request: ImageProviderRequest) -> ImageProviderTaskHandle:
        ...

    @abstractmethod
    def poll(
        self,
        task_handle: ImageProviderTaskHandle,
    ) -> ImageProviderTaskStatus:
        ...

    @abstractmethod
    def collect(
        self,
        task_handle: ImageProviderTaskHandle,
    ) -> ImageProviderResult:
        ...
```

This interface supports both sync-like and async-like vendors.

### Sync vendor handling

For a synchronous vendor:

- `start(...)` may return an already-completed handle
- `poll(...)` may immediately report `succeeded`
- `collect(...)` returns the final artifact payload

### Async vendor handling

For an asynchronous vendor:

- `start(...)` returns the vendor task id
- `poll(...)` checks vendor state
- `collect(...)` obtains final image payload or result URLs

### Why sync and async providers should share one task model

The platform should not require different service branches for sync and async
vendors.

Instead, Pivot should normalize both kinds of providers into the same internal
job-oriented contract:

- `start(...)`
- `poll(...)`
- `collect(...)`

A synchronous vendor is simply a provider whose job finishes immediately:

- `start(...)` performs the vendor request
- `poll(...)` reports `succeeded` on the first check
- `collect(...)` returns the already available result

An asynchronous vendor is a provider whose job requires later polling:

- `start(...)` returns a pending job handle with vendor task metadata
- `poll(...)` returns `pending`, `running`, `succeeded`, or `failed`
- `collect(...)` is called only after the provider reports completion

This keeps the service layer simple and future-proof:

- one orchestration flow
- one timeout model
- one retry model
- one future background-job evolution path

## Service orchestration

The service layer should orchestrate provider adapters, not the tool and not
the adapter itself.

Recommended service:

- `ImageGenerationService`

Recommended public methods:

- `invoke_vendor_operation(...)`
- `generate(...)`
- `edit(...)`

Possible request object:

```python
@dataclass(slots=True)
class ImageInvocationRequest:
    agent_id: int
    workspace_id: str
    username: str
    workspace_backend_path: str
    provider_key: str
    operation: str
    arguments: dict[str, Any]
```

Recommended flow:

1. resolve the provider binding for `(agent_id, provider_key)`
2. load `auth_config` and `runtime_config`
3. resolve the provider adapter implementation
4. call `start(...)`
5. poll with `poll(...)`
6. on success, call `collect(...)`
7. persist image artifacts into the workspace
8. record usage log
9. return a normalized result object to the tool

## Async Vendor Strategy

Many image vendors expose async-first APIs:

- submit job
- receive vendor task id
- poll until completed
- fetch final result

The platform should represent this explicitly.

### Important boundary

Provider adapters should expose task-oriented methods, but should **not**
contain the platform's polling loop policy.

The polling loop should live in the service layer because it owns:

- timeout policy
- retry policy
- cancellation behavior
- future background job evolution
- usage and observability

### First implementation milestone

For the first implementation milestone, Pivot should provide a synchronous
facade over async vendors:

- tool calls service
- service submits the job
- service polls in-process for a bounded timeout window
- if the vendor finishes in time, return the final result immediately
- if the vendor does not finish in time, surface a structured timeout or
  provider-running error

This fits the current ReAct tool model without requiring a larger background job
system first.

### Future evolution

Later, the same service contract can evolve into:

- persisted image jobs
- background workers or supervisors
- message-queue-backed polling
- explicit task resume/query tools

That future is easier if the provider adapter already exposes separate
`start/poll/collect` methods under one shared task model for both sync and
async vendors.

## Execution Environment

Image provider calls should happen in Pivot server, not in the sandbox.

Why:

- providers need platform-managed secrets
- provider calls need server-side services
- usage logging is server-side
- workspace artifact persistence should remain platform-mediated

Therefore:

- the image tool is a `normal` tool
- the vendor network call runs on the server
- the resulting file is written by the server into the bound workspace backend
- the agent later sees the result as a normal `/workspace/...` file

This design keeps one clean trust boundary:

- sandbox for local workspace execution
- server for privileged platform integrations

## Provider Key vs Extension Key

Runtime routing should use `provider_key`, not `extension_key`.

Why:

- one extension may contribute multiple providers
- the extension is the packaging unit
- the provider is the runtime capability unit

Therefore:

- providers declare `provider_key`
- bindings are keyed by `provider_key`
- services resolve providers by `provider_key`
- tools should target `provider_key`

The extension package remains important for:

- install and trust workflow
- version pinning
- source loading
- manifest validation

But it should not be the primary runtime routing key for invocation.

## Open Implementation Questions

The following are still implementation details to decide, but they no longer
block the overall direction:

- whether image providers should have a dedicated registry service or extend the
  current provider-registry pattern
- whether generated artifacts should also be snapshotted into object storage in
  addition to living in the workspace
- whether the first milestone should expose only vendor-specific tools, or also
  one small generic image tool for curated providers
- whether image provider bindings should allow one provider per extension
  installation only, or support multiple named providers per extension package

## Recommended First Slice

The first implementation slice should be:

1. add one new image-provider extension contribution type
2. add one `AgentImageProviderBinding` persistence model and service
3. add one `ImageGenerationService`
4. implement one vendor-specific extension such as `wan2_7`
5. expose vendor-specific tools such as:
   - `wan2_7_generate_image`
   - `wan2_7_edit_image`
6. persist generated images into the workspace
7. reuse answer attachments so the agent can return generated images to users
8. add one usage log model for observability and future billing

This gives Pivot a clean architecture for image generation without prematurely
forcing all vendors into one fake cross-provider parameter contract.
