# openenv-openshell

`openenv-openshell` is a planned OpenEnv `ContainerProvider` backed by NVIDIA
OpenShell. The repository currently contains the package and quality scaffold;
the runtime lifecycle described in [SPEC.md](SPEC.md) is not implemented yet.

## Development

Python 3.11 or newer and [uv](https://docs.astral.sh/uv/) are required.

```bash
uv sync --all-groups
make check
```

The checks enforce formatting and linting with Ruff, strict static typing with
Pyright, and unit-test branch coverage of at least 95%. Tests that require a
real OpenShell gateway belong in `tests/integration` and are opt-in:

```bash
uv run pytest -m integration
```

## Status

The public import is reserved and usable for development:

```python
from openenv_openshell import OpenShellProvider
```

Lifecycle operations intentionally raise `NotImplementedError` until Milestone
1 is implemented. See [SPEC.md](SPEC.md) for the design and milestones.

