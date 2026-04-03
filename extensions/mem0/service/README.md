# Mem0 Service

This service is the external data plane for the Pivot Mem0 extension.

It runs outside Pivot's server container so the main Pivot runtime stays
hot-pluggable and does not need the memory provider's Python dependencies
installed ahead of time.

## What This Service Includes

- `mem0ai` as the memory orchestration SDK
- `qdrant-client` for the vector database integration
- a FastAPI server that exposes the stable HTTP contract consumed by the Pivot
  extension
- a local `compose.yaml` that starts both the Mem0 service and Qdrant

Endpoints:

- `GET /health`
- `POST /v1/memories/recall`
- `POST /v1/memories/persist`

## Configuration Model

This service owns its own model and vector-store configuration. Pivot should
only know the service `base_url`.

Required environment variables:

- `MEM0_LLM_CONFIG_JSON`
- `MEM0_EMBEDDER_CONFIG_JSON`

Optional environment variables:

- `MEM0_QDRANT_URL`
- `MEM0_QDRANT_HOST`
- `MEM0_QDRANT_PORT`
- `MEM0_QDRANT_API_KEY`
- `MEM0_COLLECTION_NAME`

`MEM0_LLM_CONFIG_JSON` and `MEM0_EMBEDDER_CONFIG_JSON` are passed through as
Mem0-native JSON config objects. This keeps the service open to different
providers without requiring Pivot to understand provider-specific fields.

Example using an OpenAI-compatible provider:

```env
MEM0_LLM_CONFIG_JSON={"provider":"openai","config":{"model":"gpt-4.1-mini","api_key":"REPLACE_WITH_LLM_API_KEY"}}
MEM0_EMBEDDER_CONFIG_JSON={"provider":"openai","config":{"model":"text-embedding-3-small","api_key":"REPLACE_WITH_EMBEDDER_API_KEY"}}
```

Example using Ollama:

```env
MEM0_LLM_CONFIG_JSON={"provider":"ollama","config":{"model":"qwen2.5:7b","ollama_base_url":"http://host.containers.internal:11434"}}
MEM0_EMBEDDER_CONFIG_JSON={"provider":"ollama","config":{"model":"nomic-embed-text","ollama_base_url":"http://host.containers.internal:11434"}}
```

If a chosen provider requires an extra Python SDK that is not already bundled
by `mem0ai` or this image, extend `requirements.txt` and rebuild the service
image.

## Run Locally With Podman Compose

1. Copy the environment template:

```bash
cp /Users/erickim/Documents/学习/TRAE/hackon-project/pivot/extensions/mem0/service/.env.example \
  /Users/erickim/Documents/学习/TRAE/hackon-project/pivot/extensions/mem0/service/.env
```

2. Edit `.env` with your real provider configuration.

3. Start the service stack:

```bash
podman compose -f /Users/erickim/Documents/学习/TRAE/hackon-project/pivot/extensions/mem0/service/compose.yaml up --build
```

4. In Pivot, set the extension `Mem0 Server URL` to:

- `http://localhost:8765`

## Request Semantics

Pivot sends one runtime-derived `namespace` on every request. The current
example extension derives it from both the current user and agent, so one
user-agent pair maps to one logical memory bucket by default.

This means:

- setup only configures where the service lives
- runtime requests decide which logical memory namespace to read or write
- future extensions can change the namespace derivation strategy without
  changing the service deployment model
