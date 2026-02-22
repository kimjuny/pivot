# Pivot

An agent development framework that enables strategic, purpose-driven conversations — making agents think and act more like real people.

## Prerequisites

- [Podman](https://podman.io/docs/installation) ≥ 4.0
- [podman-compose](https://github.com/containers/podman-compose) ≥ 1.0

## Development

```bash
# First time — build images (installs all dependencies inside containers)
podman compose build

# Start dev environment (backend + frontend with hot-reload)
podman compose up

# Rebuild after dependency changes (package.json / pyproject.toml)
podman compose build --no-cache
podman compose up
```

### Platform-Specific Setup

The sidecar mode requires access to the Podman socket. Configuration varies by platform:

**macOS (podman-machine)**
```bash
# Default configuration works - uses /var/run/docker.sock symlink
podman compose up
```

**Linux (rootful)**
```bash
# Edit compose.yaml socket mount:
# - /run/podman/podman.sock:/run/podman/podman.sock
podman compose up
```

**Linux (rootless)**
```bash
# 1. Ensure XDG_RUNTIME_DIR is set
export XDG_RUNTIME_DIR=/run/user/$(id -u)

# 2. Edit compose.yaml socket mount:
# - /run/user/1000/podman/podman.sock:/run/podman/podman.sock
#    (replace 1000 with your actual UID)

# 3. May need to remove privileged: true for rootless
podman compose up
```

**Windows (WSL2)**
```bash
# Inside WSL2, follow Linux rootless instructions above
# Ensure Podman is installed inside WSL2
```

| Service  | URL                    | Description                         |
| -------- | ---------------------- | ----------------------------------- |
| Frontend | http://localhost:3000   | Vite dev server (hot-reload)        |
| Backend  | http://localhost:8003   | FastAPI (auto-reload on code save)  |

Source code is bind-mounted into the containers — edit locally, changes reflect instantly.

### Useful commands

```bash
# Stop all services
podman compose down

# View logs
podman compose logs -f backend
podman compose logs -f frontend

# Run backend linting inside container
podman exec pivot-backend poetry run ruff check server/ --fix
podman exec pivot-backend poetry run pyright server/

# Run frontend checks inside container
podman exec pivot-frontend npm run check-all
```

## Production

```bash
# Build the production image (frontend built & bundled into backend)
podman build -t pivot .

# Run with sidecar mode (requires podman socket)
podman run -d -p 8080:80 --privileged \
  -v /run/user/$(id -u)/podman/podman.sock:/run/podman/podman.sock \
  -v pivot-data:/app/server/data \
  --name pivot pivot
```

Open http://localhost:8080 — the backend serves both the API and the frontend from a single process.

### Configuration

| Variable       | Default                    | Description             |
| -------------- | -------------------------- | ----------------------- |
| `DATABASE_URL` | `sqlite:///./server/pivot.db` | Database connection URL |
| `ENV`          | `production`               | Environment mode        |
| `SANDBOX_MODE` | `sidecar`                  | Tool execution mode: `sidecar` (isolated containers) or `local` (in-process) |
| `PODMAN_SOCKET_PATH` | `/run/podman/podman.sock` | Path to Podman socket (for sidecar mode) |
| `SIDECAR_TIMEOUT_SECONDS` | `60` | Timeout for sidecar container execution |
| `SIDECAR_BASE_IMAGE` | auto-detect | Base image for sidecar containers |

### Tool Sandbox Modes

Pivot uses **sidecar mode by default** for tool execution. Each tool runs in an isolated Podman container, providing:

- **Process isolation**: Tool failures don't affect the main process
- **Resource limits**: Timeouts prevent runaway execution
- **Network isolation**: Optional network mode configuration
- **Security**: Tools execute in separate container contexts

**Requirements for sidecar mode**:
- Podman socket must be accessible at `PODMAN_SOCKET_PATH`
- Container must run with `--privileged` flag (for socket access)
- The base image must contain the tool codebase

**Fallback to local mode** (for special cases only):

```bash
podman run -d -p 8080:80 \
  -e SANDBOX_MODE="local" \
  -v pivot-data:/app/server/data \
  pivot
```

## Project Structure

```
pivot/
├── server/              # FastAPI backend
│   ├── app/
│   │   ├── api/         # API endpoints
│   │   ├── models/      # SQLModel database models
│   │   ├── services/    # Business logic layer
│   │   ├── orchestration/  # Agent orchestration (ReAct engine)
│   │   └── llm/         # LLM provider implementations
│   └── data/            # SQLite database (dev, gitignored)
├── web/                 # React + Vite frontend
│   └── src/
├── compose.yaml         # Dev environment (podman compose)
├── Containerfile        # Production image
├── Containerfile.dev    # Dev image (multi-stage)
└── pyproject.toml       # Python dependencies & tooling config
```
