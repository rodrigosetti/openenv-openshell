# openenv-openshell

`openenv-openshell` is an experimental adapter for running Hugging Face OpenEnv
environment servers under NVIDIA OpenShell filesystem, network, and credential
policies. It targets OpenEnv's existing `ContainerProvider` interface so users
can keep their environment protocol and training loop while changing runtimes.

**Pre-alpha: the production provider is unfinished.** Configuration validation,
sandbox startup, HTTP readiness, strict policy loading, and private SDK request
translation and public cleanup are implemented. This source baseline is for
development; it is not a usable production provider, a PyPI release, or a claim to the PyPI package name.

The completed local lifecycle spike demonstrated routed HTTP health,
WebSocket reset/step/state, and verified sandbox deletion with SDK/gateway
0.1.2. That evidence comes from separate integration probes, not the public
provider. See the [M0 acceptance evidence](docs/protocol-spike.md#m0-acceptance-verification-2026-09-30)
and [SPEC.md](SPEC.md) for requirements and milestones.

The public home is [rodrigosetti/openenv-openshell](https://github.com/rodrigosetti/openenv-openshell).
Publication status and baseline review are recorded in the
[repository publication guide](docs/repository-publication.md).

## Known limitations

- Unmodified OpenEnv client integration remains Milestone 1 work. Runtime probes
  do not establish complete provider behavior.
- The validated image is a locally built arm64 EchoEnv image on the native VM
  lane. Its checked-in Docker image ID is not a pullable registry digest;
  arbitrary images and compute drivers are unverified.
- Remote gateways, service authentication, long idle sessions, and reconnects
  are unverified. No remote compatibility claim follows from local tests.
- Startup requires caller-supplied command argv, environment, and directory
  handling. Automatic OCI ENTRYPOINT/CMD, ENV, and WORKDIR resolution is outside
  the MVP contract.
- Policy parsing and atomic request validation are tested, but the release's
  filesystem and network denial acceptance tests remain pending. Trusted
  external verification is a later milestone.

## Development

Python 3.11 or newer and [uv](https://docs.astral.sh/uv/) are required.

```bash
git clone https://github.com/rodrigosetti/openenv-openshell.git
cd openenv-openshell
uv sync --locked --all-groups
make check
```

Unit tests use typed fakes and do not need an OpenShell installation or gateway.
The default check excludes the opt-in runtime integration tests.
`tests/unit/test_successful_lifecycle.py` follows startup and mocked HTTP health
through identity-aware deletion, client closure, cleared ownership, and retained
non-secret metadata. It also checks cleanup through the production SDK adapter
using an offline SDK double; runtime evidence is recorded separately in the
[integration guide](tests/integration/README.md).

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

The public import is available in a development checkout:

```python
from openenv_openshell import OpenShellProvider
```

`start_container` creates an atomic policy/workload/service request, captures
the configured create-time service URL, waits for OpenShell readiness, and
populates `provider.state`. It rejects a second start while it owns a sandbox.
Startup failures use public cleanup and preserve the sanitized creation/readiness
error. If rollback fails, an exception note instructs callers to retry
`stop_container()`; ownership and recovered identity remain available for retry.
`keep_sandbox=True` retains failed sandboxes for inspection and releases local
ownership after the client closes.
`stop_container()` deletes the owned sandbox, waits for its original identity to
disappear, and releases client resources. Repeated calls are harmless. With
`keep_sandbox=True`, it closes the client and clears local ownership while leaving
the sandbox running. Deletion, wait, or client-close failures raise a sanitized
`SandboxDeletionError` and retain enough state for another stop call to retry.
`close()` performs the same cleanup, and `with OpenShellProvider(...) as provider:`
calls it on exit, including when the body raises. Context entry returns the provider
without starting a sandbox. Cleanup before startup or after a successful stop/close
is harmless. If context cleanup fails, it raises `SandboxDeletionError` with the
exception chain suppressed to keep SDK secrets out of tracebacks. Call
`provider.close()` again to retry. `keep_sandbox=True` also applies to close and
context exit.
After a health timeout, OpenEnv invokes `stop_container()`; callers using the
provider directly must also stop it after readiness or connection failures.

Lifecycle events use standard Python logging under `openenv_openshell` (INFO for
successful transitions, WARNING for cleanup failures). Event messages contain
only fixed names; they omit workload arguments, environment, policy contents,
route data, and raw SDK exceptions. Configure handlers in the calling application.

`provider.metadata` is `None` before creation yields a validated service route,
then exposes an immutable `OpenShellRunMetadata` snapshot with sandbox name/ID,
workspace, image, service URL, UTC creation/health-ready/deletion timestamps, and
installed provider, OpenShell SDK, and OpenEnv versions (missing distributions
are `None`). The SDK version is not a claim about the gateway version.
The snapshot survives cleanup, including `keep_sandbox=True` (which leaves
`deleted_at` unset), and is replaced when the next sandbox creation is attempted.
A rejected start leaves the previous snapshot intact. Deletion time records
confirmed sandbox absence even if client closure subsequently fails. Command,
environment, credentials, and policy contents are never copied into metadata;
caller-supplied image and operational identifiers must be non-secret. The service
URL is validated to exclude credentials, queries, and fragments. `policy_digest`
remains `None` until SEC2 adds verified policy provenance.
See [SPEC.md](SPEC.md) for the design and milestones.

Provider configuration is accepted directly as keyword arguments and validated
without contacting an OpenShell gateway:

```python
from openenv_openshell import OpenShellProvider, OpenShellResources

provider = OpenShellProvider(
    workspace="default",
    command=["/path/in/image/to/server-launcher"],
    service_port=8000,
    startup_timeout_s=120,
    labels={"openenv.run_id": "example-run"},
    providers=["github"],
    resources=OpenShellResources(cpu=2, memory="4Gi"),
)
```

The startup contract requires explicit `command` argv for the selected
image. The path above illustrates configuration; choose the actual image server
launcher, supply required environment through `env_vars`, and establish any
required directory in that command. The adapter preserves argv exactly and
rejects missing/invalid command before gateway access. It does not resolve OCI
ENTRYPOINT/CMD, WORKDIR, or ENV. Omission remains valid for configuration-only
and HTTP readiness use. See the [S6b decision](docs/image-startup.md).

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
Provider startup calls this loader before gateway connection for explicit
policies. Offline validation does not establish runtime policy enforcement.

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
sandbox startup and public cleanup are implemented.

## License

Apache-2.0; see [LICENSE](LICENSE).
