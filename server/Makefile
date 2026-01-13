.PHONY: lint ruff pyright check-all

lint: ruff pyright

ruff:
	@echo "Running Ruff..."
	poetry run ruff check . ../core --fix

pyright:
	@echo "Running Pyright..."
	poetry run pyright . ../core

check-all: ruff pyright
	@echo "All checks passed!"
