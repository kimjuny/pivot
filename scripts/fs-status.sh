#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
POSIX_ROOT="${PIVOT_EXTERNAL_POSIX_ROOT:-/tmp/pivot-seaweedfs-posix}"
STATUS_URL="${PIVOT_STORAGE_STATUS_URL:-http://localhost:8003/api/system/storage-status}"

usage() {
  cat <<'EOF'
Usage: scripts/fs-status.sh

Shows the current status of Pivot's optional external filesystem path.

Checks:
- whether the SeaweedFS service container is running
- whether the POSIX bridge mount exists
- whether Pivot currently activated the external `seaweedfs` profile

Environment overrides:
- PIVOT_EXTERNAL_POSIX_ROOT
- PIVOT_STORAGE_STATUS_URL
EOF
}

print_kv() {
  printf '%-28s %s\n' "$1" "$2"
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

mount_probe_snippet() {
  cat <<'EOF'
probe_path="$1/.pivot-fs-status-probe.$$"
printf 'pivot-fs-status\n' >"$probe_path"
grep -q 'pivot-fs-status' "$probe_path"
rm -f "$probe_path"
EOF
}

compose_service_status() {
  if ! command_exists podman; then
    echo "podman-unavailable"
    return 0
  fi

  if podman ps --format '{{.Names}}' 2>/dev/null | grep -qx 'pivot-seaweedfs'; then
    echo "running"
    return 0
  fi

  echo "not-running"
}

linux_mount_status() {
  if ! command_exists mountpoint; then
    echo "mountpoint-unavailable"
    return 0
  fi

  if mountpoint -q "$POSIX_ROOT"; then
    if bash -lc "$(mount_probe_snippet)" -- "$POSIX_ROOT" >/dev/null 2>&1; then
      echo "mounted"
      return 0
    fi
    echo "mounted-unhealthy"
    return 0
  fi

  echo "not-mounted"
}

macos_mount_status() {
  if ! command_exists podman || ! command_exists ssh || ! command_exists python3; then
    echo "vm-check-unavailable"
    return 0
  fi

  local inspect_json
  if ! inspect_json="$(podman machine inspect 2>/dev/null)"; then
    echo "vm-check-unavailable"
    return 0
  fi
  if [ "$inspect_json" = "[]" ]; then
    echo "vm-check-unavailable"
    return 0
  fi

  local port
  local user
  local identity
  port="$(python3 -c 'import json, sys; print(json.load(sys.stdin)[0]["SSHConfig"]["Port"])' <<<"$inspect_json")"
  user="$(python3 -c 'import json, sys; print(json.load(sys.stdin)[0]["SSHConfig"]["RemoteUsername"])' <<<"$inspect_json")"
  identity="$(python3 -c 'import json, sys; print(json.load(sys.stdin)[0]["SSHConfig"]["IdentityPath"])' <<<"$inspect_json")"

  local remote_status
  local remote_script
  remote_script="$(cat <<EOF
set -euo pipefail
mount_root="$POSIX_ROOT"
if ! mountpoint -q "\$mount_root"; then
  printf not-mounted
  exit 0
fi
probe_path="\$mount_root/.pivot-fs-status-probe.\$\$"
printf "pivot-fs-status\n" >"\$probe_path"
if grep -q "pivot-fs-status" "\$probe_path"; then
  rm -f "\$probe_path"
  printf mounted
  exit 0
fi
rm -f "\$probe_path"
printf mounted-unhealthy
EOF
)"
  remote_status="$(ssh \
    -o StrictHostKeyChecking=no \
    -i "$identity" \
    -p "$port" \
    "${user}@127.0.0.1" \
    "/bin/bash -lc '$remote_script'" 2>/dev/null || printf vm-check-unavailable)"

  if [ -n "$remote_status" ]; then
    echo "$remote_status"
    return 0
  fi

  echo "vm-check-unavailable"
}

posix_bridge_status() {
  case "$(uname -s)" in
    Darwin)
      macos_mount_status
      ;;
    Linux)
      linux_mount_status
      ;;
    MINGW*|MSYS*|CYGWIN*|Windows_NT)
      echo "not-required"
      ;;
    *)
      echo "unknown-platform"
      ;;
  esac
}

read_backend_status() {
  if ! command_exists curl; then
    return 1
  fi

  curl -fsS --max-time 3 "$STATUS_URL" 2>/dev/null || return 1
}

main() {
  case "${1:-}" in
    -h|--help)
      usage
      exit 0
      ;;
  esac

  local service_status
  local bridge_status
  service_status="$(compose_service_status)"
  bridge_status="$(posix_bridge_status)"

  print_kv "seaweedfs_service" "$service_status"
  print_kv "external_posix_root" "$POSIX_ROOT"
  print_kv "external_posix_bridge" "$bridge_status"

  local backend_status_json
  if backend_status_json="$(read_backend_status)"; then
    local requested_profile
    local active_profile
    local object_backend
    local posix_backend
    local fallback_reason
    requested_profile="$(python3 -c 'import json, sys; print(json.load(sys.stdin)["requested_profile"])' <<<"$backend_status_json")"
    active_profile="$(python3 -c 'import json, sys; print(json.load(sys.stdin)["active_profile"])' <<<"$backend_status_json")"
    object_backend="$(python3 -c 'import json, sys; print(json.load(sys.stdin)["object_storage_backend"])' <<<"$backend_status_json")"
    posix_backend="$(python3 -c 'import json, sys; print(json.load(sys.stdin)["posix_workspace_backend"])' <<<"$backend_status_json")"
    fallback_reason="$(python3 -c 'import json, sys; print(json.load(sys.stdin)["fallback_reason"])' <<<"$backend_status_json")"
    print_kv "pivot_requested_profile" "$requested_profile"
    print_kv "pivot_active_profile" "$active_profile"
    print_kv "pivot_object_backend" "$object_backend"
    print_kv "pivot_posix_backend" "$posix_backend"
    print_kv "pivot_fallback_reason" "$fallback_reason"
  else
    print_kv "pivot_storage_status" "unavailable ($STATUS_URL)"
  fi
}

main "$@"
