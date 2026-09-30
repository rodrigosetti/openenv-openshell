# openenv-openshell

`openenv-openshell` is a planned OpenEnv `ContainerProvider` backed by NVIDIA
OpenShell. Configuration validation and HTTP readiness are implemented; sandbox
startup and cleanup described in [SPEC.md](SPEC.md) are still pending.

## Development

Python 3.11 or newer and [uv](https://docs.astral.sh/uv/) are required.

```bash
uv sync --locked --all-groups
make check
```

The shared [Codex local environment](.codex/environments/environment.toml)
runs `uv sync --locked --all-groups` when a new worktree is created, using
Python 3.11 from `.python-version`. Install uv on the host first. Its actions
provide quality checks, unit tests, formatting, loopback HTTP integration tests,
and opt-in OpenShell prerequisite, smoke, and integration checks. Runtime actions
require the [local OpenShell setup](docs/local-openshell-testing.md); setup only
installs Python dependencies. Integration actions use `--no-cov` because they
run separately from the unit coverage gate enforced by `make check`. The EchoEnv
probe also needs `OPENENV_OPENSHELL_ECHO_IMAGE_ID` as described in the
[integration guide](tests/integration/README.md).

The SDK is pinned to the official OpenShell 0.1.2 release wheel by URL and
SHA-256. Use a matching 0.1.2 gateway for future runtime work; see the
[distribution and model-boundary decision](docs/openshell-sdk-contract.md).
The local 0.1.2 runtime and pinned EchoEnv image have been revalidated (S2a/S3a).
The separate [S4 lifecycle spike](docs/lifecycle-spike.md) exercises SDK creation,
atomic routing, readiness, and deletion without using the production provider.
[S5](docs/protocol-spike.md) verified the local routed protocol;
[S6 decisions](docs/spike-decisions.md) define port/service/policy behavior and
record the remaining image-startup and remote-validation prerequisites.
The [M0 acceptance rerun](docs/protocol-spike.md#m0-acceptance-verification-2026-09-30)
verified local routed EchoEnv reset/step and sandbox deletion, completing the
spike milestone. Production provider lifecycle remains Milestone 1 work.

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

## Explicit policy loading

`openenv_openshell.policy.load_policy()` accepts a YAML file path (`str` or
`Path`) or a mapping and returns a detached mapping of normalized OpenShell
0.1.2 protobuf fields. It runs offline, without a gateway:

```python
from openenv_openshell.policy import load_policy

policy = load_policy("policy.yaml")
```

Policies must explicitly specify integer `version: 1`. The authored
`filesystem_policy` key becomes `filesystem`; supplying both is rejected.
Nested fields use exact snake_case SDK names. Network endpoint `tls`,
`enforcement`, and `access` accept the short YAML spellings (such as `terminate`,
`enforce`, and `read_only`) or canonical protobuf enum names. List order is
preserved; mapping keys are sorted. No filesystem or network grants are added.

Unknown fields, incorrect types, unsupported versions, nulls, duplicate or merge
keys, YAML anchors/aliases, unsafe tags, and multiple YAML documents raise
`PolicyConfigurationError`. File paths and policy contents are omitted from
errors. Files are limited to 1 MiB and mappings to 64 nesting levels. Authored
convenience forms requiring additional conversion (for example nested MCP or
JSON-RPC stanzas, query shorthand, and arbitrary middleware Struct config) are
currently unsupported and rejected; use the supported SDK field representation.
The loader validates field shape and strict SDK conversion; gateway semantic
validation and real enforcement remain separate checks.

`None` is rejected by this explicit loader. Image/default policy selection must
be a deliberate caller choice and cannot recover from an explicit-policy error.
The loader is ready for provider startup integration; startup itself remains
pending, and no runtime enforcement claim follows from these offline tests.

See the [policy examples and selection guide](examples/policies/README.md) for
strict deny-all egress, minimal Hugging Face reads, and an image compatibility
policy. Their schema and create-request serialization are checked against the
pinned 0.1.2 wheel. The guide explains image-policy selection, the proposed
`policy_mode` API, and the difference between compatibility and least privilege.

## Credentials

Prefer OpenShell provider-backed credentials for secrets; use `env_vars` for
ordinary configuration. Raw environment values are readable by sandbox
processes even when request representations and errors redact them. The
`providers` option selects existing provider instance names in the configured
workspace and maps them to the sandbox spec; it does not provision credentials
or infer providers. See the [credential and provider guide](docs/security.md)
for setup, permission scope, and the SEC7 runtime visibility check. Public
sandbox startup and cleanup remain pending Milestone 1.
