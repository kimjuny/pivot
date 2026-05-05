# Pivot

Pivot is an agent development framework for building, testing, and operating
tool-using agents with a real workspace, live files, extensions, skills, and a
full chat runtime.

## Why Pivot

- Real agent workspace: agents work against a real `/workspace`, not a fake prompt-only sandbox.
- Live file loop: uploads, generated files, attachments, and workspace edits stay connected.
- Extension system: add tools, skills, hooks, and runtime capabilities as installable packages.
- ReAct runtime: plan, act, observe, and recover through a structured task engine.
- Local-first DX: start fast on one machine, then grow toward external storage and distributed setups.

## Quick Start

### Prerequisites

- [Podman](https://podman.io/docs/installation)
- `podman compose`

### Default development mode

```bash
podman compose build
podman compose up
```

Open:

- Frontend: http://localhost:3000
- Backend: http://localhost:8003

### Optional SeaweedFS mode

```bash
scripts/fs-up.sh
podman compose --profile seaweedfs up -d
```

`scripts/fs-up.sh` prepares and repairs the external POSIX bridge used by the
`seaweedfs` profile. It is needed for macOS and Linux when you want real
external workspace storage. Windows continues to use `local_fs` by default.

If a previous `podman compose --profile seaweedfs up` got stuck because the
bridge mount went bad, rerun `scripts/fs-up.sh`. It will clear stale
SeaweedFS-mode containers, repair the bridge, and recreate the SeaweedFS
service if needed so the next `podman compose --profile seaweedfs up` does not
inherit the poisoned state. It can often unblock the stuck startup indirectly,
but the guaranteed part is repairing the environment for the next `up`.

When `backend` or `sandbox-manager` are already running, `scripts/fs-up.sh`
also refreshes them and clears warm workspace sandboxes so every runtime sees
the same bridge state after the command completes.

To tear the bridge down again:

```bash
scripts/fs-down.sh
```

When `backend` or `sandbox-manager` are already running, `scripts/fs-down.sh`
also refreshes them and clears warm workspace sandboxes so the stack cleanly
falls back away from the external bridge without split-brain mounts.

To inspect the current external-fs state:

```bash
scripts/fs-status.sh
```

Check the active storage mode at:

```text
GET /api/system/storage-status
```

SeaweedFS explorer:

- http://localhost:8888

## Development Notes

- Source code is bind-mounted into containers, so edits reload automatically.
- Default startup path:
  - `podman compose up`
- External-storage startup path:
  - `scripts/fs-up.sh`
  - `podman compose --profile seaweedfs up -d`

### Common commands

```bash
# Stop services
podman compose down

# Logs
podman compose logs -f backend
podman compose logs -f frontend
podman compose logs -f seaweedfs

# External POSIX bridge
scripts/fs-up.sh
scripts/fs-status.sh
scripts/fs-down.sh

# Backend checks
podman compose exec backend bash server/lint.sh

# Frontend checks
podman compose exec frontend npm run check-all
```

### Reset development database

The default compose stack stores SQLite data at:

```text
server/data/pivot.db
```

To reset local development data, stop the backend, delete that file, then start
the stack again. Startup seeds the default roles (`user`, `builder`, `admin`),
permissions, and the default admin account (`default` / `123456`).

## Production

```bash
podman build -t pivot .
podman run -d -p 8080:80 --name pivot pivot
```

Open:

- http://localhost:8080

## Project Structure

```text
pivot/
├── server/
│   ├── app/
│   │   ├── api/
│   │   ├── models/
│   │   ├── services/
│   │   ├── orchestration/
│   │   └── llm/
│   └── data/
├── web/
├── compose.yaml
├── Containerfile
├── Containerfile.dev
└── drafts/
```

## Docs

- Filesystem and storage design: [drafts/filesystem.md](/Users/erickim/Documents/学习/TRAE/hackon-project/pivot/drafts/filesystem.md)
