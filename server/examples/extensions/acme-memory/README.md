# ACME Memory

This sample extension demonstrates the intended boundary for an external memory
plugin:

- Pivot triggers lifecycle hooks
- The extension reads hook context and decides what to recall or persist
- Memory is stored outside Pivot itself
- The extension injects recalled memory via `append_prompt_block`

## Hooks

- `task.before_start`
  Loads recent memory from an external JSON file and prepends it to the task
  bootstrap prompt.
- `task.completed`
  Builds a small memory candidate from the completed task and writes it to the
  external JSON file when `execution_mode` is `live`.

## External Store

This sample uses a local JSON file as a stand-in for an external memory system.
That keeps the example runnable in local development while preserving the
architectural boundary that memory does not belong to Pivot itself.

Environment variable:

- `PIVOT_SAMPLE_MEMORY_PATH`
  Optional custom path for the external JSON store.

Default path:

- `/tmp/pivot-sample-memory.json`

## Why This Example Exists

The goal is not to recommend file-based memory storage. The goal is to show how
an extension can:

1. Read lifecycle context
2. Skip external writes during replay
3. Recall memory at task start
4. Persist memory after task completion

without requiring Pivot to own the memory subsystem.
