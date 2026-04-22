#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
POSIX_ROOT="${PIVOT_EXTERNAL_POSIX_ROOT:-/tmp/pivot-seaweedfs-posix}"

usage() {
  cat <<'EOF'
Usage: scripts/fs-down.sh

Tears down the external SeaweedFS POSIX bridge used by Pivot's optional
`seaweedfs` profile.

Behavior:
- macOS: unmounts the bridge inside the Podman machine
- Linux: unmounts the bridge on the host
- Windows: exits with a short note because Pivot defaults to `local_fs`
- With `--stop-service`, also stops the `seaweedfs` compose service

Environment overrides:
- PIVOT_EXTERNAL_POSIX_ROOT
EOF
}

log() {
  printf '[fs-down] %s\n' "$*"
}

compose_base() {
  (
    cd "$ROOT_DIR"
    podman compose -f compose.yaml "$@"
  )
}

compose_with_seaweedfs() {
  (
    cd "$ROOT_DIR"
    podman compose -f compose.yaml --profile seaweedfs "$@"
  )
}

container_is_running() {
  local container_name="$1"
  podman ps --format '{{.Names}}' 2>/dev/null | grep -qx "$container_name"
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf '[fs-down] missing required command: %s\n' "$1" >&2
    exit 1
  fi
}

refresh_runtime_services() {
  require_command podman

  local backend_running=false
  local sandbox_manager_running=false

  if container_is_running pivot-backend; then
    backend_running=true
  fi
  if container_is_running pivot-sandbox-manager; then
    sandbox_manager_running=true
  fi

  if [ "$backend_running" = false ] && [ "$sandbox_manager_running" = false ]; then
    log "Backend and sandbox-manager are not running; no runtime refresh is needed"
    return 0
  fi

  log "Refreshing backend and sandbox-manager so they drop the previous POSIX bridge view"

  local sandbox_ids
  sandbox_ids="$(podman ps -aq --filter label=pivot.sandbox.workspace_id)"
  if [ -n "$sandbox_ids" ]; then
    log "Removing workspace sandboxes so they reconnect after bridge teardown"
    # shellcheck disable=SC2086
    podman rm -f $sandbox_ids >/dev/null
  fi

  compose_base stop backend sandbox-manager >/dev/null 2>&1 || true
  compose_base up -d backend sandbox-manager >/dev/null
}

unmount_snippet() {
  cat <<'EOF'
if command -v fusermount3 >/dev/null 2>&1; then
  fusermount3 -u "$1" && exit 0
fi
if command -v fusermount >/dev/null 2>&1; then
  fusermount -u "$1" && exit 0
fi
umount "$1" 2>/dev/null && exit 0
umount -l "$1"
EOF
}

stop_seaweedfs_service() {
  log "Stopping SeaweedFS service"
  compose_with_seaweedfs stop seaweedfs
}

teardown_linux_mount() {
  if ! command -v mountpoint >/dev/null 2>&1; then
    printf '[fs-down] missing required command: mountpoint\n' >&2
    exit 1
  fi

  if ! mountpoint -q "$POSIX_ROOT"; then
    log "No SeaweedFS POSIX bridge mounted at $POSIX_ROOT"
    return 0
  fi

  log "Unmounting SeaweedFS POSIX bridge on Linux host at $POSIX_ROOT"
  bash -lc "$(unmount_snippet)" -- "$POSIX_ROOT"
}

teardown_macos_mount() {
  require_command podman
  require_command ssh
  require_command python3

  local inspect_json
  if ! inspect_json="$(podman machine inspect 2>/dev/null)"; then
    printf '[fs-down] unable to inspect the active Podman machine\n' >&2
    exit 1
  fi
  if [ "$inspect_json" = "[]" ]; then
    printf '[fs-down] no active Podman machine is available\n' >&2
    exit 1
  fi

  local port
  local user
  local identity
  port="$(python3 -c 'import json, sys; print(json.load(sys.stdin)[0]["SSHConfig"]["Port"])' <<<"$inspect_json")"
  user="$(python3 -c 'import json, sys; print(json.load(sys.stdin)[0]["SSHConfig"]["RemoteUsername"])' <<<"$inspect_json")"
  identity="$(python3 -c 'import json, sys; print(json.load(sys.stdin)[0]["SSHConfig"]["IdentityPath"])' <<<"$inspect_json")"

  local ssh_base=(
    ssh
    -o
    StrictHostKeyChecking=no
    -i
    "$identity"
    -p
    "$port"
    "${user}@127.0.0.1"
  )

  local remote_teardown
  remote_teardown="$(cat <<EOF
set -euo pipefail
if ! mountpoint -q "$POSIX_ROOT"; then
  exit 0
fi
$(unmount_snippet)
EOF
)"

  log "Unmounting SeaweedFS POSIX bridge in Podman VM at $POSIX_ROOT"
  "${ssh_base[@]}" /bin/bash -lc "$remote_teardown" sh "$POSIX_ROOT" >/dev/null 2>&1 || {
    printf '[fs-down] failed to unmount SeaweedFS bridge in Podman VM at %s\n' "$POSIX_ROOT" >&2
    exit 1
  }
}

main() {
  local stop_service=false

  while [ "$#" -gt 0 ]; do
    case "$1" in
      -h|--help)
        usage
        exit 0
        ;;
      --stop-service)
        stop_service=true
        ;;
      *)
        printf '[fs-down] unknown argument: %s\n' "$1" >&2
        usage >&2
        exit 1
        ;;
    esac
    shift
  done

  case "$(uname -s)" in
    Darwin)
      teardown_macos_mount
      refresh_runtime_services
      ;;
    Linux)
      teardown_linux_mount
      refresh_runtime_services
      ;;
    MINGW*|MSYS*|CYGWIN*|Windows_NT)
      log "Windows uses local_fs by default; no external POSIX bridge is required"
      ;;
    *)
      printf '[fs-down] unsupported platform: %s\n' "$(uname -s)" >&2
      exit 1
      ;;
  esac

  if [ "$stop_service" = true ]; then
    stop_seaweedfs_service
  fi
}

main "$@"
