# Pivot Extensions

## Overview

This document explains how to build a Pivot extension package that can be
imported locally today and, later, installed from a Hub or Market.

Pivot supports two integration styles:

- Lightweight direct integration for standalone `tools` and `skills`
- Package-based integration for versioned extensions

Use a package when you want one installable unit with versioning, trust,
bindings, release pinning, lifecycle hooks, or providers.

In practice:

- `channel providers` and `web-search providers` should be packaged
- `hooks` are packaged
- `tools` and `skills` may stay lightweight, but packages can include them

## Package Identity

Every package is identified by:

- `scope`
- `name`
- `version`

Pivot derives:

- Package id: `@scope/name`
- Versioned reference: `@scope/name@version`

Provider keys are separate from package ids and must follow:

- `scope@provider_name`

Examples:

- Package id: `@acme/memory`
- Channel provider key: `acme@chat`
- Web-search provider key: `acme@search`

## Package Layout

An extension is one folder with a required `manifest.json` file at its root.

```text
acme-extension/
  manifest.json
  README.md
  hooks/
    lifecycle.py
  channel_providers/
    chat.py
  web_search_providers/
    search/
      provider.py
  tools/
    summarize.py
  skills/
    researcher/
      SKILL.md
  tests/
```

Rules:

- `manifest.json` is required
- Skill directories must contain `SKILL.md`
- Paths inside the manifest must be relative to the package root
- The folder name is not authoritative; `manifest.json` is

Ready-to-import examples in this repository:

- [acme-memory](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/server/examples/extensions/acme-memory)
- [acme-providers](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/server/examples/extensions/acme-providers)

## Manifest

Minimal hook-based package:

```json
{
  "schema_version": 1,
  "scope": "acme",
  "name": "memory",
  "display_name": "ACME Memory",
  "version": "1.0.0",
  "description": "Sample external-memory extension.",
  "api_version": "1.x",
  "contributions": {
    "hooks": [
      {
        "event": "task.before_start",
        "callable": "inject_memory",
        "mode": "sync",
        "entrypoint": "hooks/lifecycle.py"
      },
      {
        "event": "task.completed",
        "callable": "persist_memory",
        "mode": "sync",
        "entrypoint": "hooks/lifecycle.py"
      }
    ]
  }
}
```

Minimal provider package:

```json
{
  "schema_version": 1,
  "scope": "acme",
  "name": "providers",
  "display_name": "ACME Providers",
  "version": "1.0.0",
  "description": "Sample local-import provider package.",
  "api_version": "1.x",
  "contributions": {
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
  }
}
```

Common top-level fields:

- `schema_version`
- `scope`
- `name`
- `display_name`
- `version`
- `description`
- `api_version`
- `license`
- `homepage_url`
- `repository_url`
- `contributions`
- `permissions`
- `compatibility`

Current contribution declarations:

- `hooks[*].event`
- `hooks[*].callable`
- `hooks[*].mode`
- `hooks[*].entrypoint`
- `channel_providers[*].entrypoint`
- `web_search_providers[*].entrypoint`
- `tools[*].name`
- `tools[*].entrypoint`
- `skills[*].name`
- `skills[*].path`

Validation rules worth knowing:

- `scope` and `name` must be simple lowercase identifiers
- `version` must be a non-empty version token
- provider keys must use `scope@provider_name`
- provider key scope must match `manifest.json.scope`
- hook `event` must be one of the supported lifecycle events
- hook `mode` must be `sync` or `async`

## Hooks

Hooks are the main way to participate in the agent lifecycle.

### Supported Events

Current supported events:

- `task.before_start`
- `task.completed`
- `task.failed`
- `task.waiting_input`
- `iteration.plan_updated`
- `iteration.answer_ready`
- `iteration.error`
- `iteration.before_tool_call`
- `iteration.after_tool_result`

### Entrypoint Format

Each manifest hook entry points at a Python file plus one callable name:

```json
{
  "event": "task.before_start",
  "callable": "inject_memory",
  "mode": "sync",
  "entrypoint": "hooks/lifecycle.py"
}
```

That entrypoint file must export a function with this shape:

```python
from typing import Any


def inject_memory(context: dict[str, Any]) -> list[dict[str, Any]]:
    ...
```

Async hooks are also allowed:

```python
from typing import Any


async def after_tool_result(context: dict[str, Any]) -> list[dict[str, Any]]:
    ...
```

Pivot does not inject service objects, database handles, or ORM models into
hooks. Hooks only receive a JSON-like `context` dictionary.

### Hook Context

The exact shape depends on the event, but these top-level fields are stable:

- `session_id`
- `task_id`
- `trace_id`
- `iteration`
- `agent_id`
- `release_id`
- `execution_mode`
- `timestamp`
- `runtime`
- `event_payload`

Task-level hooks also receive a `task` snapshot. Today that includes:

- `task.user_message`
- `task.status`
- `task.total_tokens`
- `task.agent_answer`

Example task hook context:

```json
{
  "session_id": "3893195d-...",
  "task_id": "81894df9-...",
  "trace_id": null,
  "iteration": 0,
  "agent_id": 2,
  "release_id": 3,
  "execution_mode": "live",
  "timestamp": "2026-04-03T04:27:08.021130+00:00",
  "task": {
    "user_message": "what can you do?",
    "status": "completed",
    "total_tokens": 5596,
    "agent_answer": "Hi there! ..."
  },
  "runtime": {
    "source": "release",
    "task_status": "completed"
  },
  "event_payload": {}
}
```

Iteration-level hooks receive `event_payload` instead of the task snapshot as
their main event-specific input.

### Hook Return Value

A hook must return a list of effect dictionaries:

```python
[
    {"type": "...", "payload": {...}},
]
```

Current supported effects:

- `emit_event`
- `append_prompt_block`

#### `emit_event`

Use this to publish a structured runtime event to Pivot's normal task event
stream.

```python
return [
    {
        "type": "emit_event",
        "payload": {
            "type": "memory_persisted",
            "data": {
                "kind": "external_memory_write",
                "stored_count": 3,
            },
        },
    }
]
```

Pivot will enrich the emitted event with task and hook metadata before it is
published.

#### `append_prompt_block`

Use this to inject additional prompt text during `task.before_start`.

```python
return [
    {
        "type": "append_prompt_block",
        "payload": {
            "target": "task_bootstrap",
            "position": "head",
            "content": "## Retrieved Memory\n- User prefers quarterly billing",
        },
    }
]
```

Current restrictions:

- only supported for `task.before_start`
- only supports `target: "task_bootstrap"`
- `position` must be `head` or `tail`

### Replay Behavior

Hook context includes:

- `execution_mode = "live"` during normal execution
- `execution_mode = "replay"` during safe replay

Use this when your hook talks to an external system. A write-on-complete hook
should usually skip writes during replay.

The sample memory extension does exactly that:

- [lifecycle.py](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/server/examples/extensions/acme-memory/hooks/lifecycle.py)

Its `persist_memory(...)` hook returns no effects in replay mode so replay stays
side-effect free.

### Hook Example

This is the real pattern used by the sample memory extension:

```python
from typing import Any


def inject_memory(context: dict[str, Any]) -> list[dict[str, Any]]:
    agent_id = context.get("agent_id")
    if not isinstance(agent_id, int):
        return []

    memories = ["User prefers concise billing emails."]
    return [
        {
            "type": "append_prompt_block",
            "payload": {
                "target": "task_bootstrap",
                "position": "head",
                "content": "## Retrieved External Memory\n- " + memories[0],
            },
        }
    ]


def persist_memory(context: dict[str, Any]) -> list[dict[str, Any]]:
    if context.get("execution_mode") != "live":
        return []

    return [
        {
            "type": "emit_event",
            "payload": {
                "type": "memory_persisted",
                "data": {"kind": "external_memory_write"},
            },
        }
    ]
```

## Channel Providers

Channel providers are packaged integrations. The manifest only declares the
entrypoint path; the provider file itself defines the provider metadata.

### Entrypoint Contract

The entrypoint must export a top-level `PROVIDER` object.

The sample implementation lives at:

- [chat.py](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/server/examples/extensions/acme-providers/channel_providers/chat.py)

Pattern:

```python
from typing import Any

from app.channels.providers import BaseBuiltinProvider
from app.channels.types import ChannelManifest, ChannelTestResult


class AcmeChatProvider(BaseBuiltinProvider):
    manifest = ChannelManifest(
        key="acme@chat",
        name="ACME Chat",
        description="Sample provider.",
        icon="message-square",
        docs_url="https://example.com/acme/providers/chat",
        transport_mode="webhook",
        capabilities=["receive_text", "send_text"],
        auth_schema=[],
        config_schema=[],
        setup_steps=["Import the extension locally."],
    )

    def test_connection(
        self,
        auth_config: dict[str, Any],
        runtime_config: dict[str, Any],
        binding_id: int,
    ) -> ChannelTestResult:
        return ChannelTestResult(
            ok=True,
            status="healthy",
            message="ACME Chat is available.",
            endpoint_infos=self.build_endpoint_infos(binding_id),
        )


PROVIDER = AcmeChatProvider()
```

Rules:

- export `PROVIDER`
- `PROVIDER.manifest` must be a `ChannelManifest`
- `manifest.key` must follow `scope@provider_name`
- the `scope` portion must match the package scope

## Web-Search Providers

Web-search providers follow the same packaged-entrypoint pattern.

The sample implementation lives at:

- [provider.py](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/server/examples/extensions/acme-providers/web_search_providers/search/provider.py)

Pattern:

```python
from app.orchestration.web_search.base import BaseWebSearchProvider
from app.orchestration.web_search.types import (
    WebSearchExecutionResult,
    WebSearchProviderBinding,
    WebSearchProviderManifest,
    WebSearchQueryRequest,
    WebSearchTestResult,
)


class AcmeSearchProvider(BaseWebSearchProvider):
    manifest = WebSearchProviderManifest(
        key="acme@search",
        name="ACME Search",
        description="Sample provider.",
        docs_url="https://example.com/acme/providers/search",
        auth_schema=[],
        config_schema=[],
        setup_steps=["Import the extension locally."],
        supported_parameters=["query", "max_results"],
    )

    def get_api_key(self, binding: WebSearchProviderBinding) -> str:
        return "sample-local-import"

    def _search_with_binding(
        self,
        *,
        request: WebSearchQueryRequest,
        api_key: str,
        runtime_config: dict[str, object],
    ) -> WebSearchExecutionResult:
        return WebSearchExecutionResult(
            query=request.query,
            provider={"key": self.manifest.key, "name": self.manifest.name},
            applied_parameters={"max_results": request.max_results},
            results=[],
        )

    def test_connection(
        self,
        *,
        auth_config: dict[str, object],
        runtime_config: dict[str, object],
    ) -> WebSearchTestResult:
        return WebSearchTestResult(
            ok=True,
            status="healthy",
            message="ACME Search is available.",
        )


PROVIDER = AcmeSearchProvider()
```

Rules:

- export `PROVIDER`
- `PROVIDER.manifest` must be a `WebSearchProviderManifest`
- `manifest.key` must follow `scope@provider_name`
- the `scope` portion must match the package scope

## Skills

Skills may live inside a package, although simple skills can also stay
lightweight and un-packaged.

Manifest example:

```json
{
  "contributions": {
    "skills": [
      {
        "name": "researcher",
        "path": "skills/researcher"
      }
    ]
  }
}
```

Rules:

- `path` must point to a directory
- that directory must contain `SKILL.md`
- the contribution `name` must be unique within the package

Optional front matter in `SKILL.md` can provide a description:

```md
---
name: researcher
description: Research and summarize company background before drafting outreach.
---

# Researcher

...
```

Pivot reads the `description` field from front matter when it builds package
metadata.

## Tools

Packaged tools are optional. They are useful when one package needs to ship a
tool together with providers or hooks. If you only need one small internal
tool, the lightweight non-packaged path is usually simpler.

Manifest example:

```json
{
  "contributions": {
    "tools": [
      {
        "name": "summarize_account",
        "entrypoint": "tools/summarize_account.py"
      }
    ]
  }
}
```

The entrypoint file must export at least one function decorated with `@tool`,
and the decorated tool name must match the manifest contribution name.

Pattern:

```python
from app.orchestration.tool import tool


@tool
def summarize_account(account_name: str) -> str:
    """Summarize one account for the current operator."""
    return f"Summary for {account_name}"
```

How Pivot discovers packaged tool metadata:

- tool name comes from the Python function name
- description comes from the function docstring
- parameter schema comes from type hints
- execution type comes from the decorator's `tool_type`

Important rule:

- if the manifest says `name: "summarize_account"`, the decorated function must
  also resolve to `summarize_account`

## Local Development Workflow

Recommended workflow:

1. Create an extension folder with `manifest.json`
2. Implement hooks, providers, tools, or skills
3. Import the folder or bundle from the Extensions UI
4. Review the preview and trust prompt
5. Install the package
6. Bind it to one agent
7. Use Studio Test or publish a new release before testing consumer traffic

Important note about releases:

- consumer sessions use the agent's pinned release bundle
- if you install and bind a new extension after a release was published, that
  extension will not appear in old consumer sessions until you publish a new
  release

## Debugging

Pivot provides extension-specific debugging tools.

### Hook Execution Log

For packaged hooks, Pivot records:

- package id and version
- event name
- callable name
- task and trace identifiers
- hook context
- returned effects
- errors
- timing

### Safe Replay

You can replay one historical hook invocation from the Extensions detail page
or from Operations.

Replay is for debugging. It should not produce live side effects.

For hooks that write to external systems:

- check `execution_mode`
- skip writes during replay

### Good Replay Pattern

```python
def persist_memory(context: dict[str, Any]) -> list[dict[str, Any]]:
    if context.get("execution_mode") != "live":
        return []
    ...
```

## Trust And Source

Today, local imports are the primary installation path.

Current trust states:

- `unverified`
- `trusted_local`
- `verified`

Current behavior:

- local preview is `unverified`
- installation requires an explicit trust action
- persisted local installs are stored as `trusted_local`

The package may claim a `scope`, but local import does not verify ownership of
that scope.

## What Pivot Does Not Expose To Extensions

Pivot intentionally does not expose:

- database sessions
- ORM models
- file storage services
- cache clients
- arbitrary internal runtime mutation

Extensions should operate through:

- declared entrypoints
- hook context
- structured effects
- provider manifests

This boundary keeps packages replayable, observable, and easier to evolve.
