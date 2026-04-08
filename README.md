# Pivot

An agent development framework that enables strategic, purpose-driven conversations — making agents think and act more like real people.

## Prerequisites

- [Podman](https://podman.io/docs/installation) ≥ 4.0
- [podman-compose](https://github.com/containers/podman-compose) ≥ 1.0
- Native SeaweedFS local development also requires FUSE support.
  - macOS / Windows: Podman machine already provides the required FUSE device.
  - Linux: ensure `fusermount3` is available on the host.

## Development

Pivot local development now uses the same **native shared mount root** shape as
the intended production architecture:

- SeaweedFS is the canonical storage backend
- `sandbox-manager` requires a real native mount under the shared mount root
- `server/workspace/` is **not** used as a duplicate live workspace tree

Before opening the app, make sure the runtime status reports:

- `native_mount_active=true`
- `fallback_bridge_active=false`

### 1. Build and start the base services

```bash
# First time: build images (installs all dependencies inside containers)
podman compose build

# Start the local services before mounting the shared root
podman compose up -d seaweedfs sandbox-base sandbox-manager backend frontend
```

| Service  | URL                    | Description                         |
| -------- | ---------------------- | ----------------------------------- |
| Frontend | http://localhost:3000   | Vite dev server (hot-reload)        |
| Backend  | http://localhost:8003   | FastAPI (auto-reload on code save)  |

Source code is bind-mounted into the containers, so code changes still hot-reload
normally. The additional native-mount step below only affects the live
workspace filesystem.

### 2. Prepare the native SeaweedFS shared mount

These commands assume the default Compose project name is `pivot`, which
creates the volume `pivot_seaweedfs_mount_root`. If you override the Compose
project name, adjust the volume name accordingly.

#### macOS

```bash
podman machine start

podman machine ssh 'mkdir -p /var/home/core/bin && \
  podman cp pivot-seaweedfs:/usr/bin/weed /var/home/core/bin/weed && \
  chmod +x /var/home/core/bin/weed'

podman machine ssh 'MOUNT_ROOT=$(podman volume inspect pivot_seaweedfs_mount_root --format "{{.Mountpoint}}") && \
  mkdir -p /var/home/core/.cache/pivot/seaweedfs "$MOUNT_ROOT/seaweedfs-mnt" && \
  nohup /var/home/core/bin/weed mount \
    -dir="$MOUNT_ROOT/seaweedfs-mnt" \
    -filer=127.0.0.1:8888 \
    -allowOthers=false \
    -nonempty \
    -dirAutoCreate \
    -cacheDir=/var/home/core/.cache/pivot/seaweedfs \
    >/var/home/core/.cache/pivot/seaweedfs-mount.log 2>&1 </dev/null &'
```

#### Windows

Run the same Podman-machine steps as macOS. If you use PowerShell, replace the
outer single quotes with double quotes.

```powershell
podman machine start

podman machine ssh "mkdir -p /var/home/core/bin && podman cp pivot-seaweedfs:/usr/bin/weed /var/home/core/bin/weed && chmod +x /var/home/core/bin/weed"

podman machine ssh "MOUNT_ROOT=`$(podman volume inspect pivot_seaweedfs_mount_root --format '{{.Mountpoint}}') && mkdir -p /var/home/core/.cache/pivot/seaweedfs `"`$MOUNT_ROOT/seaweedfs-mnt`" && nohup /var/home/core/bin/weed mount -dir=`"`$MOUNT_ROOT/seaweedfs-mnt`" -filer=127.0.0.1:8888 -allowOthers=false -nonempty -dirAutoCreate -cacheDir=/var/home/core/.cache/pivot/seaweedfs >/var/home/core/.cache/pivot/seaweedfs-mount.log 2>&1 </dev/null &"
```

#### Linux

```bash
mkdir -p ~/.local/bin
podman cp pivot-seaweedfs:/usr/bin/weed ~/.local/bin/weed
chmod +x ~/.local/bin/weed

MOUNT_ROOT="$(podman volume inspect pivot_seaweedfs_mount_root --format '{{.Mountpoint}}')"
mkdir -p "$HOME/.cache/pivot/seaweedfs" "$MOUNT_ROOT/seaweedfs-mnt"

nohup ~/.local/bin/weed mount \
  -dir="$MOUNT_ROOT/seaweedfs-mnt" \
  -filer=127.0.0.1:8888 \
  -allowOthers=false \
  -nonempty \
  -dirAutoCreate \
  -cacheDir="$HOME/.cache/pivot/seaweedfs" \
  >"$HOME/.cache/pivot/seaweedfs-mount.log" 2>&1 </dev/null &
```

### 3. Verify that native mount is active

```bash
podman compose exec backend python - <<'PY'
import json
import urllib.request

request = urllib.request.Request(
    "http://sandbox-manager:8051/runtime/seaweedfs/status",
    headers={"X-Sandbox-Token": "dev-sandbox-token"},
)
payload = urllib.request.urlopen(request, timeout=5).read().decode()
print(json.dumps(json.loads(payload), indent=2))
PY
```

Healthy local-development output should include:

```json
{
  "attach_strategy": "shared_mount_root",
  "native_mount_required": true,
  "native_mount_active": true,
  "fallback_bridge_active": false
}
```

If `native_mount_active` is `false`, do not start agent workflows yet. Fix the
native mount first.

### Useful commands

```bash
# Stop all services
podman compose down

# View logs
podman compose logs -f backend
podman compose logs -f frontend
podman compose logs -f sandbox-manager
podman compose logs -f seaweedfs

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
