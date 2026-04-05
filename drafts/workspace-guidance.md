# Workspace Guidance Design

## Summary

This document proposes a Pivot-native `workspace guidance` mechanism that is
compatible with repository-level instruction files such as `AGENTS.md` and
`CLAUDE.md`.

The purpose of this mechanism is to inject project-local working conventions
into the ReAct task bootstrap prompt, without elevating those conventions to
system-prompt authority.

This fills a gap that is not covered by the existing `tools`, `skills`, or
`mandatory_skills` channels:

- `tools` describe what the agent can do
- `skills` describe reusable capabilities the agent may choose to load
- `mandatory_skills` describe capabilities the user explicitly wants applied
- `workspace guidance` describes how this specific repository expects work to be
  done

## Motivation

Some projects, templates, and extensions rely heavily on repository-local
instruction files. The common examples are:

- `AGENTS.md`
- `CLAUDE.md`

These files often contain practical project rules such as:

- preferred commands
- test and build expectations
- folder ownership or architecture notes
- conventions for file organization
- repository-specific workflow preferences

Without this context, the runtime agent can still operate, but it tends to:

- spend more recursions rediscovering repository norms
- make less accurate tool and file choices
- miss project-specific constraints that are not universal enough to become a
  reusable skill

## Design Goals

- preserve the current ReAct architecture
- avoid vendor-specific prompt semantics in the core runtime
- support `AGENTS.md` and `CLAUDE.md` as compatibility inputs
- keep repository-local instructions below system-level authority
- make the first version simple enough to ship quickly

## Non-Goals

- do not make repository guidance a replacement for `SKILL.md`
- do not create a full summarization pipeline in v1
- do not infer or merge multiple guidance files with complex precedence rules in
  v1
- do not auto-edit user repositories by default

## Key Decision

Pivot should support this concept as `workspace guidance`, not as a
hard-coded vendor feature.

That means:

- the runtime may discover `AGENTS.md` and `CLAUDE.md`
- the prompt should refer to the injected content as `Workspace Guidance`
- the internal abstraction stays product-native and extensible

This keeps the mechanism compatible with external ecosystems while avoiding
tight coupling to one tool vendor's naming.

## Prompt Placement

### Recommendation

Inject workspace guidance into the task bootstrap `user prompt`, not into the
stable `system prompt`.

### Why not the system prompt

The system prompt in Pivot defines:

- the role of the runtime
- the ReAct state machine contract
- the schema and action rules

Repository-local guidance is different in nature. It is:

- workspace-specific
- user/project-authored
- lower-trust than system policy
- expected to vary between tasks and repositories

If repository guidance were injected into the system prompt, it would gain too
much authority and could interfere with core runtime behavior.

### Why the user prompt is a better fit

The task bootstrap user prompt already carries dynamic, task-scoped context:

- tools
- skill index
- mandatory skills

Workspace guidance belongs in the same family of context.

The intended lifecycle is:

1. discover the active workspace guidance file before a task starts
2. inject it into the bootstrap user prompt once for that task
3. persist that bootstrap message in the task's message history
4. let later recursions reuse the existing message history rather than
   re-injecting the same content every recursion

This means the guidance is injected once per task bootstrap, not once per
recursion.

## Discovery Rules

The first version should keep discovery intentionally simple.

### v1 discovery order

1. If `/workspace/AGENTS.md` exists, load it.
2. Otherwise, if `/workspace/CLAUDE.md` exists, load it.
3. Otherwise, inject an empty workspace-guidance block.

### v1 conflict rule

- `AGENTS.md` has explicit priority over `CLAUDE.md`
- if `AGENTS.md` exists, `CLAUDE.md` is ignored

This keeps the behavior deterministic and easy to explain.

## Injection Format

The first version can use full-text injection.

Recommended rendered structure:

```markdown
# /workspace/AGENTS.md

<full file content>
```

If `AGENTS.md` is absent and `CLAUDE.md` is present:

```markdown
# /workspace/CLAUDE.md

<full file content>
```

If neither file exists:

```markdown

```

## First-Version Scope

The first version should intentionally stay narrow:

- only inspect `/workspace/AGENTS.md`
- otherwise inspect `/workspace/CLAUDE.md`
- inject the full file content
- do not summarize
- do not traverse nested directories
- do not merge multiple files

This is enough to validate product value before investing in a richer guidance
resolver.

## Priority Model

Workspace guidance should be followed, but it must not outrank core runtime or
explicit user intent.

Recommended priority order:

1. system prompt
2. user explicit request for the current task
3. mandatory skills
4. workspace guidance
5. skills index metadata

This makes workspace guidance strong enough to matter, while keeping it below
session-critical instructions.

## Relationship to Skills

Workspace guidance and skills solve different problems.

### Skills

Skills are reusable capability bundles. They are designed to be portable across
repositories and tasks.

### Workspace Guidance

Workspace guidance is repository-local operating context. It describes how this
particular project expects the agent to work.

Examples of guidance content that should remain in workspace guidance:

- "run tests with this wrapper script"
- "keep generated code under this directory"
- "do not edit this folder directly"
- "use this architecture pattern in this repository"

Examples of content that belongs in a skill instead:

- how to use an external framework in general
- a reusable debugging workflow
- a reusable deployment playbook

## Security and Trust Considerations

Repository-local guidance is useful, but it should be treated as lower-trust
context than system instructions.

The runtime should assume:

- repository authors may place strong opinions in these files
- those opinions may not always be safe or relevant
- the agent must still obey the system contract and explicit user instructions

For v1, the main safety control is prompt placement and priority, not content
rewriting.

## Auto-Creation Policy

The runtime should not automatically create an empty `/workspace/AGENTS.md` for
every workspace by default.

Reasons:

- it mutates repositories unnecessarily
- it pollutes diffs and version control
- an empty file adds no useful context
- imported third-party repositories should not be modified implicitly

If desired later, Pivot may offer an explicit initialization action for new
blank workspaces, but that should be opt-in.

## Suggested Runtime API Shape

The prompt builder will eventually need a new argument:

```python
def build_runtime_user_prompt(
    ...,
    workspace_guidance: str = "",
) -> str:
    ...
```

And the template renderer should replace:

- `{{workspace_guidance}}`

This draft does not require a specific implementation yet, but the prompt API
should stay aligned with the injection point already added to
`server/app/orchestration/react/user_prompt.md`.

## Future Extensions

If v1 proves useful, the next iterations could add:

- directory-aware resolution using the current working path
- bounded-length injection with truncation metadata
- summary generation for very large files
- support for additional guidance filenames
- optional UI surfacing showing which guidance file was loaded

## Recommended v1 Decision

Ship the first version with these rules:

- inject workspace guidance in the task bootstrap user prompt
- do not inject it into the system prompt
- load `/workspace/AGENTS.md` first
- fall back to `/workspace/CLAUDE.md`
- ignore `CLAUDE.md` when `AGENTS.md` exists
- inject full file content
- do not auto-create an empty guidance file

This gives Pivot a useful compatibility layer immediately, while preserving a
clean path toward a more advanced resolver later.
