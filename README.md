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

# Run (single container, single port)
podman run -d -p 8080:80 --name pivot pivot
```

Open http://localhost:8080 — the backend serves both the API and the frontend from a single process.

### Configuration

| Variable       | Default                    | Description             |
| -------------- | -------------------------- | ----------------------- |
| `DATABASE_URL` | `sqlite:///./server/pivot.db` | Database connection URL |
| `ENV`          | `production`               | Environment mode        |

Pass environment variables at runtime:

```bash
podman run -d -p 8080:80 \
  -e DATABASE_URL="postgresql://user:pass@host:5432/pivot" \
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
