#!/bin/bash

echo "Running Ruff..."
python3 -m ruff check . ../core --fix
RUFF_EXIT=$?

echo ""
echo "Running Pyright..."
python3 -m pyright .
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
