#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
POSIX_ROOT="${PIVOT_EXTERNAL_POSIX_ROOT:-/tmp/pivot-seaweedfs-posix}"
FILER_ENDPOINT="${PIVOT_SEAWEEDFS_FILER_ENDPOINT:-127.0.0.1:8888}"
FILER_GRPC_ENDPOINT="${PIVOT_SEAWEEDFS_FILER_GRPC_ENDPOINT:-}"
MOUNT_LOG="${PIVOT_SEAWEEDFS_MOUNT_LOG:-/tmp/pivot-seaweedfs-mount.log}"

usage() {
  cat <<'EOF'
Usage: scripts/fs-up.sh

Prepares the external SeaweedFS POSIX bridge used by Pivot's optional
`seaweedfs` profile.

Behavior:
- Starts the `seaweedfs` compose service if it is not running yet
- Reuses the existing mount when it is already healthy
- On macOS, mounts inside the Podman machine
- On Linux, mounts on the host
- On Windows, exits with a short note because Pivot defaults to `local_fs`

Environment overrides:
- PIVOT_EXTERNAL_POSIX_ROOT
- PIVOT_SEAWEEDFS_FILER_ENDPOINT
- PIVOT_SEAWEEDFS_FILER_GRPC_ENDPOINT
- PIVOT_SEAWEEDFS_MOUNT_LOG
EOF
}

log() {
  printf '[fs-up] %s\n' "$*"
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

container_status() {
  podman inspect --format '{{.State.Status}}' "$1" 2>/dev/null || true
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf '[fs-up] missing required command: %s\n' "$1" >&2
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

  log "Refreshing backend and sandbox-manager so they observe the same POSIX bridge"

  local sandbox_ids
  sandbox_ids="$(podman ps -aq --filter label=pivot.sandbox.workspace_id)"
  if [ -n "$sandbox_ids" ]; then
    log "Removing workspace sandboxes so they reconnect to the refreshed bridge"
    # shellcheck disable=SC2086
    podman rm -f $sandbox_ids >/dev/null
  fi

  compose_base stop backend sandbox-manager >/dev/null 2>&1 || true
  compose_base up -d backend sandbox-manager >/dev/null
}

remove_container_if_present() {
  local container_name="$1"
  if [ -n "$(container_status "$container_name")" ]; then
    log "Removing stale container $container_name"
    podman rm -f "$container_name" >/dev/null 2>&1 || true
  fi
}

repair_poisoned_runtime_state() {
  require_command podman

  local repaired=false
  local container_name
  local status

  for container_name in pivot-seaweedfs pivot-backend pivot-sandbox-manager pivot-frontend; do
    status="$(container_status "$container_name")"
    case "$status" in
      created|configured|exited|stopping)
        remove_container_if_present "$container_name"
        repaired=true
        ;;
    esac
  done

  if [ "$repaired" = true ]; then
    log "Cleared stale SeaweedFS compose containers before bridge repair"
  fi
}

start_seaweedfs_service() {
  log "Starting SeaweedFS service"
  compose_with_seaweedfs up -d seaweedfs >/dev/null
}

recreate_seaweedfs_service() {
  remove_container_if_present pivot-seaweedfs
  start_seaweedfs_service
}

derive_filer_grpc_endpoint() {
  if [ -n "$FILER_GRPC_ENDPOINT" ]; then
    printf '%s\n' "$FILER_GRPC_ENDPOINT"
    return 0
  fi

  local filer_host="${FILER_ENDPOINT%:*}"
  local filer_port="${FILER_ENDPOINT##*:}"
  if [[ "$filer_host" == "$FILER_ENDPOINT" ]] || ! [[ "$filer_port" =~ ^[0-9]+$ ]]; then
    return 1
  fi

  printf '%s:%s\n' "$filer_host" "$((filer_port + 10000))"
}

wait_for_filer() {
  require_command curl

  local health_url="http://${FILER_ENDPOINT}/"
  local attempts=30
  local index=1

  log "Waiting for SeaweedFS filer at ${health_url}"
  while [ "$index" -le "$attempts" ]; do
    if curl -fsS --max-time 2 "$health_url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
    index=$((index + 1))
  done

  return 1
}

wait_for_filer_grpc() {
  require_command python3

  local grpc_endpoint
  if ! grpc_endpoint="$(derive_filer_grpc_endpoint)"; then
    log "Skipping filer gRPC readiness probe because endpoint could not be derived"
    return 0
  fi

  local grpc_host="${grpc_endpoint%:*}"
  local grpc_port="${grpc_endpoint##*:}"
  local attempts=30
  local index=1

  log "Waiting for SeaweedFS filer gRPC at ${grpc_endpoint}"
  while [ "$index" -le "$attempts" ]; do
    if python3 - "$grpc_host" "$grpc_port" <<'PY' >/dev/null 2>&1
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])
sock = socket.socket()
sock.settimeout(2)
try:
    sock.connect((host, port))
except OSError:
    raise SystemExit(1)
finally:
    sock.close()
PY
    then
      return 0
    fi
    sleep 1
    index=$((index + 1))
  done

  return 1
}

ensure_seaweedfs_service_ready() {
  local attempts=2
  local index=1

  while [ "$index" -le "$attempts" ]; do
    if [ "$index" -gt 1 ]; then
      log "SeaweedFS service looked unhealthy; recreating it"
      recreate_seaweedfs_service
    else
      start_seaweedfs_service
    fi

    if wait_for_filer && wait_for_filer_grpc; then
      return 0
    fi

    index=$((index + 1))
  done

  printf '[fs-up] SeaweedFS service did not become healthy after repair attempts\n' >&2
  exit 1
}

mount_probe_snippet() {
  cat <<'EOF'
probe_path="$1/.pivot-fs-up-probe.$$"
printf 'pivot-fs-up\n' >"$probe_path"
grep -q 'pivot-fs-up' "$probe_path"
rm -f "$probe_path"
EOF
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

wait_for_mount_ready_snippet() {
  cat <<'EOF'
mount_root="$1"
attempts=20
index=1
while [ "$index" -le "$attempts" ]; do
  if mountpoint -q "$mount_root" && bash -lc "$(cat <<'INNER'
probe_path="$1/.pivot-fs-up-probe.$$"
printf 'pivot-fs-up\n' >"$probe_path"
grep -q 'pivot-fs-up' "$probe_path"
rm -f "$probe_path"
INNER
)" -- "$mount_root" >/dev/null 2>&1; then
    exit 0
  fi
  sleep 1
  index=$((index + 1))
done
exit 1
EOF
}

mount_command_snippet() {
  cat <<EOF
mkdir -p "$POSIX_ROOT"
/var/home/core/bin/weed mount \\
  -filer="$FILER_ENDPOINT" \\
  -dir="$POSIX_ROOT" \\
  -dirAutoCreate \\
  -nonempty \\
  -allowOthers \\
  -volumeServerAccess=filerProxy
EOF
}

ensure_linux_mount() {
  require_command weed
  mkdir -p "$POSIX_ROOT"

  if mountpoint -q "$POSIX_ROOT"; then
    if bash -lc "$(mount_probe_snippet)" -- "$POSIX_ROOT" >/dev/null 2>&1; then
      log "SeaweedFS POSIX bridge already mounted at $POSIX_ROOT"
      return 0
    fi
    log "Existing mount at $POSIX_ROOT is unhealthy; remounting"
    bash -lc "$(unmount_snippet)" -- "$POSIX_ROOT"
  fi

  log "Mounting SeaweedFS POSIX bridge on Linux host at $POSIX_ROOT"
  nohup weed mount \
    -filer="$FILER_ENDPOINT" \
    -dir="$POSIX_ROOT" \
    -dirAutoCreate \
    -nonempty \
    -allowOthers \
    -volumeServerAccess=filerProxy \
    >"$MOUNT_LOG" 2>&1 &

  if ! bash -lc "$(wait_for_mount_ready_snippet)" -- "$POSIX_ROOT"; then
    printf '[fs-up] mounted path did not become ready at %s; check %s\n' "$POSIX_ROOT" "$MOUNT_LOG" >&2
    exit 1
  fi

  log "SeaweedFS POSIX bridge is ready at $POSIX_ROOT"
}

ensure_macos_mount() {
  require_command podman
  require_command ssh
  require_command python3

  local inspect_json
  if ! inspect_json="$(podman machine inspect 2>/dev/null)"; then
    printf '[fs-up] unable to inspect the active Podman machine\n' >&2
    exit 1
  fi
  if [ "$inspect_json" = "[]" ]; then
    printf '[fs-up] no active Podman machine is available\n' >&2
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

  local remote_probe
  remote_probe="$(cat <<EOF
set -euo pipefail
mkdir -p "$POSIX_ROOT"
if mountpoint -q "$POSIX_ROOT"; then
  $(mount_probe_snippet)
  exit 0
fi
exit 11
EOF
)"

  if "${ssh_base[@]}" /bin/bash -lc "$remote_probe" sh "$POSIX_ROOT" >/dev/null 2>&1; then
    log "SeaweedFS POSIX bridge already mounted in Podman VM at $POSIX_ROOT"
    return 0
  fi

  local remote_mount
  remote_mount="$(cat <<EOF
set -euo pipefail
mkdir -p "$POSIX_ROOT"
if mountpoint -q "$POSIX_ROOT"; then
  $(unmount_snippet)
fi
nohup $(mount_command_snippet) >"$MOUNT_LOG" 2>&1 &
bash -lc '$(wait_for_mount_ready_snippet)' -- "$POSIX_ROOT"
EOF
)"

  log "Mounting SeaweedFS POSIX bridge in Podman VM at $POSIX_ROOT"
  if ! "${ssh_base[@]}" /bin/bash -lc "$remote_mount" sh "$POSIX_ROOT" >/dev/null 2>&1; then
    printf '[fs-up] failed to mount SeaweedFS bridge in Podman VM; check %s inside the VM\n' "$MOUNT_LOG" >&2
    exit 1
  fi

  log "SeaweedFS POSIX bridge is ready in Podman VM at $POSIX_ROOT"
}

main() {
  case "${1:-}" in
    -h|--help)
      usage
      exit 0
      ;;
  esac

  case "$(uname -s)" in
    Darwin)
      repair_poisoned_runtime_state
      ensure_seaweedfs_service_ready
      ensure_macos_mount
      refresh_runtime_services
      ;;
    Linux)
      repair_poisoned_runtime_state
      ensure_seaweedfs_service_ready
      ensure_linux_mount
      refresh_runtime_services
      ;;
    MINGW*|MSYS*|CYGWIN*|Windows_NT)
      log "Windows uses local_fs by default; no external POSIX bridge is required"
      ;;
    *)
      printf '[fs-up] unsupported platform: %s\n' "$(uname -s)" >&2
      exit 1
      ;;
  esac
}

main "$@"
