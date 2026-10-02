.PHONY: docs-build docs-serve check compatibility demo format integration lint openshell-prereqs openshell-smoke security-e2e security-filesystem security-network test typecheck

export OPENENV_OPENSHELL_FILESYSTEM_IMAGE_ID OPENENV_OPENSHELL_NETWORK_IMAGE_ID OPENENV_OPENSHELL_CODING_IMAGE_ID

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

# Explicit jobs must fail on missing opt-in rather than report skipped tests.
# Separate images prevent accidentally using EchoEnv without the SEC5 canaries.
security-filesystem:
	@test -n "$$OPENENV_OPENSHELL_FILESYSTEM_IMAGE_ID" || { echo "Set OPENENV_OPENSHELL_FILESYSTEM_IMAGE_ID to the SEC5 canary image" >&2; exit 2; }
	OPENENV_OPENSHELL_ECHO_IMAGE_ID="$$OPENENV_OPENSHELL_FILESYSTEM_IMAGE_ID" uv run pytest -m integration --no-cov tests/integration/test_filesystem_security.py -v

security-network:
	@test -n "$$OPENENV_OPENSHELL_NETWORK_IMAGE_ID" || { echo "Set OPENENV_OPENSHELL_NETWORK_IMAGE_ID to the validated EchoEnv image" >&2; exit 2; }
	OPENENV_OPENSHELL_ECHO_IMAGE_ID="$$OPENENV_OPENSHELL_NETWORK_IMAGE_ID" uv run pytest -m integration --no-cov tests/integration/test_network_security.py -v

# Check both inputs before creating any sandbox; run the jobs sequentially.
security-e2e:
	@test -n "$$OPENENV_OPENSHELL_FILESYSTEM_IMAGE_ID" && test -n "$$OPENENV_OPENSHELL_NETWORK_IMAGE_ID" || { echo "Set both security job image variables; see tests/integration/README.md" >&2; exit 2; }
	$(MAKE) security-filesystem
	$(MAKE) security-network

# I8 reference demo; see docs/coding-agent-demo.md for the image build.
demo:
	@test -n "$$OPENENV_OPENSHELL_CODING_IMAGE_ID" || { echo "Set OPENENV_OPENSHELL_CODING_IMAGE_ID; see docs/coding-agent-demo.md" >&2; exit 2; }
	uv run python examples/coding_env.py

openshell-prereqs:
	./scripts/check-openshell-local.sh

openshell-smoke:
	./scripts/check-openshell-local.sh --smoke

# Docs-only commands do not install or execute the runtime dependencies.
docs-build:
	uv run --locked --only-group docs mkdocs build --strict

docs-serve:
	uv run --locked --only-group docs mkdocs serve
