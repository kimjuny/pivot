#!/bin/bash

# =============================================================================
# Pivot — Lint Script
# Runs ruff and pyright for code quality checks
# =============================================================================

set -e

# Get directory of this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Check if running inside a container or if podman container is available
IN_CONTAINER=$(grep -q 'pivot-backend' /proc/1/cgroup 2>/dev/null && echo "true" || echo "false")
CONTAINER_RUNNING=$(podman ps --format '{{.Names}}' 2>/dev/null | grep -q 'pivot-backend' && echo "true" || echo "false")

run_in_container() {
    echo "Running linting inside pivot-backend container..."
    podman exec pivot-backend sh -c "cd /app && poetry run ruff check server/ --fix && poetry run ruff format server/ && poetry run pyright server/"
}

run_locally() {
    echo "Running linting locally..."
    cd "$PROJECT_ROOT"

    echo "Running Ruff check..."
    cd server && poetry run ruff check . --fix
    RUFF_EXIT=$?

    echo ""
    echo "Running Ruff format..."
    poetry run ruff format .
    FORMAT_EXIT=$?

    echo ""
    echo "Running Pyright..."
    poetry run pyright .
    PYRIGHT_EXIT=$?

    if [ $RUFF_EXIT -eq 0 ] && [ $FORMAT_EXIT -eq 0 ] && [ $PYRIGHT_EXIT -eq 0 ]; then
        echo ""
        echo "All checks passed!"
        exit 0
    else
        echo ""
        echo "Some checks failed!"
        exit 1
    fi
}

# Prefer container execution if available
if [ "$CONTAINER_RUNNING" = "true" ]; then
    run_in_container
elif [ "$IN_CONTAINER" = "true" ]; then
    # Already inside container, run directly
    run_locally
else
    echo "Warning: pivot-backend container is not running."
    echo "Attempting to run locally (requires Poetry to be installed)..."
    run_locally
fi
