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

See [Local OpenShell integration setup](docs/local-openshell-testing.md) for
the CLI, gateway, workspace, compute-driver, and service-routing prerequisites.

## Status

The public import is reserved and usable for development:

```python
from openenv_openshell import OpenShellProvider
```

Lifecycle operations intentionally raise `NotImplementedError` until Milestone
1 is implemented. See [SPEC.md](SPEC.md) for the design and milestones.

Provider configuration is accepted directly as keyword arguments and validated
without contacting an OpenShell gateway:

```python
from openenv_openshell import OpenShellProvider, OpenShellResources

provider = OpenShellProvider(
    workspace="default",
    service_port=8000,
    startup_timeout_s=120,
    labels={"openenv.run_id": "example-run"},
    providers=["github"],
    resources=OpenShellResources(cpu=2, memory="4Gi"),
)
```

Ports, timeouts, and requested resources must be positive. Explicit sandbox and
service names use lowercase letters, digits, and hyphens; otherwise the provider
generates a bounded `openenv-<image>-<suffix>` sandbox name. Labels are copied
defensively and must contain only non-secret operational metadata—never tokens,
credentials, prompts, or private task/user content.
