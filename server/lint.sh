#!/bin/bash

# Get directory of this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

echo "Running Ruff..."
cd server && poetry run ruff check . ../core --fix
RUFF_EXIT=$?

echo ""
echo "Running Pyright..."
poetry run pyright . ../core
PYRIGHT_EXIT=$?

if [ $RUFF_EXIT -eq 0 ] && [ $PYRIGHT_EXIT -eq 0 ]; then
    echo ""
    echo "All checks passed!"
    exit 0
else
    echo ""
    echo "Some checks failed!"
    exit 1
fi
