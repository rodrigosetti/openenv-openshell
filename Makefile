.PHONY: check format integration lint test typecheck

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
