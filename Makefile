.PHONY: check format integration lint openshell-prereqs openshell-smoke test typecheck

check: lint typecheck test

format:
	uv run ruff format .
	uv run ruff check --fix .

lint:
	uv run ruff format --check .
	uv run ruff check .

typecheck:
	uv run pyright

test:
	uv run pytest

integration:
	uv run pytest -m integration

openshell-prereqs:
	./scripts/check-openshell-local.sh

openshell-smoke:
	./scripts/check-openshell-local.sh --smoke
