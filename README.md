# openenv-openshell

`openenv-openshell` is a planned OpenEnv `ContainerProvider` backed by NVIDIA
OpenShell. Configuration validation and HTTP readiness are implemented; sandbox
startup and cleanup described in [SPEC.md](SPEC.md) are still pending.

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

Sandbox startup and cleanup intentionally raise `NotImplementedError` until
their Milestone 1 tasks are implemented. See [SPEC.md](SPEC.md) for the design
and milestones.

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

## HTTP readiness

`wait_for_ready(base_url, timeout_s=30.0)` polls `<base_url>/health` and sets
`provider.state.ready` when HTTP 200 arrives before the monotonic deadline.
Non-200 responses and transport errors are retried; redirects are not followed.
The response body is not downloaded. The URL must use HTTP or HTTPS and must
exclude embedded credentials, query parameters, and fragments. Service path
prefixes are preserved.

```python
from openenv_openshell import OpenEnvReadinessTimeout, OpenShellProvider

provider = OpenShellProvider(
    health_poll_interval_s=0.5,
    health_request_timeout_s=2.0,
)
try:
    provider.wait_for_ready("http://my-service.openshell.localhost", timeout_s=30)
except OpenEnvReadinessTimeout:
    # The environment did not become healthy within the polling budget.
    pass
```

Both polling settings and `timeout_s` must be positive and finite. Each request
uses the smaller of `health_request_timeout_s` and the remaining budget for its
HTTPX connection, read, write, and pool timeouts. Sleeps also use the remaining
budget. HTTP transport timeouts apply per operation, so an in-flight request or
DNS lookup can finish after the deadline; no further probes are started, and a
late HTTP 200 is rejected. Timeout errors omit the URL and raw transport details.
HTTP health alone does not verify WebSocket connectivity or sandbox cleanup.
