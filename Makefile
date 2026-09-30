.PHONY: check compatibility format integration lint openshell-prereqs openshell-smoke test typecheck

check: lint typecheck test

compatibility:
	uv run --locked pytest --no-cov tests/unit/test_compatibility.py tests/unit/test_openenv_client.py tests/unit/test_openshell_contract.py tests/unit/test_adapter_contract.py tests/unit/test_adapter.py

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
