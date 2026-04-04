# Mem0 Extension Workspace

This directory contains the two deliverables required for a scalable external
memory integration:

- `extension/`: the package imported into Pivot
- `service/`: the standalone HTTP service that stores and recalls memory

Why the split exists:

- Pivot should not install third-party SDK dependencies into its own server
  container
- memory storage should remain external and scalable
- hooks should stay lightweight and call a stable HTTP contract instead of
  importing memory libraries directly

Recommended operator flow:

1. Import `extension/` into Pivot.
2. Start `service/` locally or deploy it remotely.
3. Open the extension detail `Setup` tab in Pivot.
4. Fill the service URL.
5. Bind the extension to one or more agents.

Current scope:

- the extension stays lightweight and only calls HTTP
- the service owns LLM, embedder, and vector-store configuration
- one runtime request derives one memory namespace from the current
  `user + agent` pair
