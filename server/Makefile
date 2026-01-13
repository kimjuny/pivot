.PHONY: lint ruff pyright check-all

lint: ruff pyright

ruff:
	@echo "Running Ruff..."
	python3 -m ruff check . ../core --fix

pyright:
	@echo "Running Pyright..."
	python3 -m pyright . ../core

check-all: ruff pyright
	@echo "All checks passed!"
