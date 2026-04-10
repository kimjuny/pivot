#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
POSIX_ROOT="${PIVOT_EXTERNAL_POSIX_ROOT:-/tmp/pivot-seaweedfs-posix}"
FILER_ENDPOINT="${PIVOT_SEAWEEDFS_FILER_ENDPOINT:-127.0.0.1:8888}"
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
- PIVOT_SEAWEEDFS_MOUNT_LOG
EOF
}

log() {
  printf '[fs-up] %s\n' "$*"
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf '[fs-up] missing required command: %s\n' "$1" >&2
    exit 1
  fi
}

ensure_seaweedfs_service() {
  log "Starting SeaweedFS service"
  (
    cd "$ROOT_DIR"
    podman compose --profile seaweedfs up -d seaweedfs
  )
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

  printf '[fs-up] SeaweedFS filer did not become ready at %s\n' "$health_url" >&2
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
if command -v fusermount >/dev/null 2>&1; then
  fusermount -u "$1"
else
  umount "$1"
fi
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

  sleep 2

  if ! mountpoint -q "$POSIX_ROOT"; then
    printf '[fs-up] mount did not appear at %s; check %s\n' "$POSIX_ROOT" "$MOUNT_LOG" >&2
    exit 1
  fi

  if ! bash -lc "$(mount_probe_snippet)" -- "$POSIX_ROOT" >/dev/null 2>&1; then
    printf '[fs-up] mounted path is not writable at %s; check %s\n' "$POSIX_ROOT" "$MOUNT_LOG" >&2
    exit 1
  fi

  log "SeaweedFS POSIX bridge is ready at $POSIX_ROOT"
}

ensure_macos_mount() {
  require_command podman
  require_command ssh
  require_command python3

  local inspect_json
  inspect_json="$(podman machine inspect)"

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
sleep 2
mountpoint -q "$POSIX_ROOT"
$(mount_probe_snippet)
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
      ensure_seaweedfs_service
      wait_for_filer
      ensure_macos_mount
      ;;
    Linux)
      ensure_seaweedfs_service
      wait_for_filer
      ensure_linux_mount
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
