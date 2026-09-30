# OpenShell Python SDK contract

This note records the public OpenShell surface inspected for roadmap task S1.
S1a selects the distribution and confines generated models to the private
adapter; these models are not part of the provider public API.

## Inspected releases

- Inspection date: 2026-09-29.
- Current release: [OpenShell `v0.1.2`][v0.1.2 release], including its official
  [Python wheel] GitHub release asset.
- Previous repository baseline: `openshell==0.0.116` from [PyPI 0.0.116].
- Selected dependency: the official 0.1.2 wheel, pinned by URL and SHA-256 in
  `pyproject.toml` and `uv.lock`.
- Python: 3.11 or newer.

The [Python SDK documentation] recommends using the SDK and gateway from the
same OpenShell release.
The target pair is therefore SDK and gateway `0.1.2`. The official 0.1.2 wheel
is attached to the GitHub release but was not published on PyPI at inspection
time; PyPI still resolves 0.0.116. The repository must not combine the old
0.0.116 SDK with a 0.1.x gateway and call that a supported pair.

[v0.1.2 release]: https://github.com/NVIDIA/OpenShell/releases/tag/v0.1.2
[Python wheel]: https://github.com/NVIDIA/OpenShell/releases/download/v0.1.2/openshell-0.1.2-py3-none-any.whl
[PyPI 0.0.116]: https://pypi.org/project/openshell/0.0.116/
[Python SDK documentation]: https://docs.nvidia.com/openshell/latest/sdk/python

## Public imports and connection

The current lifecycle and service surface is exported from `openshell`:

```python
from openshell import (
    DeletionOutcome,
    DeletionResult,
    GatewayError,
    SandboxClient,
    SandboxError,
    SandboxRef,
    ServiceExposure,
)
```

Use the active gateway registered by the CLI:

```python
SandboxClient.from_active_cluster(
    *,
    cluster: str | None = None,
    timeout: float = 30.0,
    auto_refresh: bool = True,
    write_back: bool = True,
    insecure: bool = False,
    client_credentials: ClientCredentialsAuth | None = None,
) -> SandboxClient
```

`cluster` selects a registered gateway. When omitted, the SDK reads
`OPENSHELL_GATEWAY` and then the CLI's active-gateway file. The constructor
also supports a direct gRPC endpoint:

```python
SandboxClient(
    endpoint: str,
    *,
    tls: TlsConfig | None = None,
    bearer_token: str | Callable[[], str] | None = None,
    client_credentials: ClientCredentialsAuth | None = None,
    timeout: float = 30.0,
    cluster_name: str | None = None,
) -> None
```

Non-loopback client-credentials connections require TLS. The client is a
context manager and `close()` is idempotent. `health()` returns a generated
response with `status` and `version`; the latter is the gateway version to
record and validate.

## Sandbox lifecycle and responses

Every resource operation takes an explicit workspace in 0.1.2.

```python
client.create(
    *,
    workspace: str,
    spec: openshell._proto.openshell_pb2.SandboxSpec | None = None,
    name: str | None = None,
    labels: Mapping[str, str] | None = None,
    service_exposures: Sequence[ServiceExposure] | None = None,
) -> SandboxRef

client.wait_ready(
    name: str,
    *,
    workspace: str,
    timeout_seconds: float = 300.0,
) -> SandboxRef

client.get(name: str, *, workspace: str) -> SandboxRef

client.exec(
    sandbox: str,
    command: Sequence[str],
    *,
    workspace: str,
    stream_output: bool = False,
    workdir: str | None = None,
    env: Mapping[str, str] | None = None,
    stdin: bytes | None = None,
    timeout_seconds: int | None = None,
    no_login_shell: bool = False,
) -> ExecResult

client.delete(
    name: str,
    *,
    workspace: str,
    allow_missing: bool = False,
) -> DeletionResult

client.wait_deleted(
    name: str,
    *,
    workspace: str,
    timeout_seconds: float = 60.0,
    expected_sandbox_id: str | None = None,
) -> None
```

`SandboxRef` exposes `id`, `name`, `workspace`, immutable `labels`, `status`,
workload-template provenance, and immutable `service_urls`. The status exposes
numeric `phase`, `current_policy_version`, and optional `exit_code`.
`create()` rejects an empty returned ID. `delete()` returns `DeletionResult`
with an `outcome` and optional `sandbox_id`; only `COMPLETED` and
`ALREADY_ABSENT` establish synchronous completion, while `ACCEPTED` requires a
wait. Pass the returned identity to `expected_sandbox_id` so deletion waiting
cannot follow a different sandbox that reused the name.

The SDK maps gateway error details to public `GatewayError` values. Local
client validation and polling failures use `SandboxError`. The adapter must
translate both, plus transport failures, without exposing credentials or raw
environment values.

## Service exposure

Service exposure is public and atomic in 0.1.2:

```python
ServiceExposure(target_port: int, service: str = "")

sandbox = client.create(
    workspace="default",
    name="openenv-example",
    spec=spec,
    service_exposures=[ServiceExposure(target_port=8000)],
)
base_url = sandbox.service_urls[""]
```

The empty key identifies the unnamed service. Named exposures use their
service name as the key. The create response is the only sandbox response that
populates `service_urls`; later `get()` calls do not. This makes extracting and
persisting the URL part of the successful create operation.

The gateway routes HTTP and WebSocket traffic to the sandbox loopback port.
Loopback gateways use the `openshell.localhost` routing domain; configured
remote gateways return their routed HTTPS URL.

[service architecture]: https://github.com/NVIDIA/OpenShell/blob/main/architecture/gateway.md

## Workload, policy, providers, and resources

The current 0.1.2 wheel still does not export a public workload/spec builder or
policy YAML loader. Although public `SandboxClient.create()` accepts `spec`,
its annotated type is generated under the explicitly private
`openshell._proto` package. `SandboxTemplateClient` likewise accepts and
returns private generated template models.

S1a explicitly selects the following generated-model boundary for the pinned
release, exercised offline in `tests/unit/test_openshell_contract.py`:

| Concern | 0.1.2 wire field | Finding |
| --- | --- | --- |
| OCI image | `spec.template.image` | Private generated model only |
| Environment | `spec.environment` | Map; higher precedence than template environment |
| Command | `spec.command` | Repeated string |
| Policy | `spec.policy` | Generated `SandboxPolicy`; no public YAML loader |
| Providers | `spec.providers` | Repeated provider names |
| CPU and memory | `spec.template.resources` | Free-form struct; CLI writes limits |
| GPU | `spec.resource_requirements.gpu.count` | Optional unsigned count |
| Object labels | create `labels=` | Stable public convenience argument |
| Services | create `service_exposures=` | Stable public `ServiceExposure` values |

OpenShell 0.1.2 also introduces named workload templates with portable image,
environment, CPU, memory, and GPU fields. The public client can create a
sandbox from an existing template by name, but creating that template still
requires a private generated model. It therefore does not yet let this provider
translate an arbitrary OpenEnv image using only stable public Python types.

### S1a decision: official wheel and confined generated models

Use the [official Python wheel][Python wheel], with SHA-256:

```text
8c409da4f176d42418d92366fe201f47cceef2c0fa432bfbce2bf938649d59cf
```

The dependency metadata includes this hash, and the lock records the same
artifact hash. `uv sync --locked --all-groups` installs it reproducibly. Hatch's
`allow-direct-references` setting is required to build this dependency metadata.
A future PyPI release must be reviewed before replacing the source; the current
direct URL is a development distribution choice, not evidence of PyPI release
readiness for this package.

Select an explicitly tested generated-model dependency rather than waiting for
a public builder or adding subprocess/CLI translation. P2 must confine
`openshell._proto.openshell_pb2` (`SandboxSpec`, `SandboxTemplate`, and resource
models) and `openshell._proto.sandbox_pb2` (`SandboxPolicy` and nested policy
models) to private adapter modules. Provider-facing types must remain ordinary
typed project models/protocols; generated types must not escape that boundary.
Use public `SandboxClient` lifecycle methods and `ServiceExposure`; do not call
private SDK clients, gRPC stubs, or implement a parallel wire model.

The offline contracts prove construction and serialization of image,
environment, providers, CPU/memory struct, GPU requirements, and an embedded
policy, plus service defaults and the required lifecycle keyword signatures.
Policy mapping must use strict conversion (`ignore_unknown_fields=False`)
after schema-aware YAML normalization in SEC1. Unsupported or malformed input
must fail before create; do not substitute an empty/default policy after a
conversion error. The fixture establishes the model shape, not runtime policy
enforcement or correct resource semantics for every compute driver.

P2 must reject an unsupported SDK and check gateway release compatibility
before creating a sandbox. T6 must extend these baseline contracts to the actual
adapter calls, responses, service URL persistence, and deletion outcomes.
Upgrades require a new pin and reviewed contracts, not a widened version range.
Migrate to a public builder when upstream supplies the necessary surface.

S2a verified the local CLI/gateway and VM HTTP/deletion smoke check on 0.1.2;
see [setup evidence](local-openshell-testing.md#verified-setup-012-2026-09-29).
Installing the Python dependency alone does not upgrade the runtime.
S3 selected the arm64 EchoEnv image; S3a verified its routed health/WebSocket
handshake and deletion on 0.1.2 with the explicit image policy fixture.

## 0.0.116 compatibility break

The previous PyPI/lock baseline differs materially from 0.1.2:

- no public `ServiceExposure`, `service_exposures=`, or `service_urls`;
- `delete()` returns `bool`, not `DeletionResult`;
- `wait_deleted()` has no `expected_sandbox_id`;
- `exec()` takes a sandbox ID and has no `workspace` keyword; and
- gateway RPC errors are not mapped to the new public `GatewayError` model.

The adapter must fail with an actionable version error rather than attempting
to support both contracts accidentally.

## Contract decisions for later tasks

1. Keep all OpenShell imports behind the private project adapter.
2. Target an exact SDK/gateway release pair, initially 0.1.2, and reject the
   known-incompatible 0.0.116 SDK before any sandbox is created.
3. Persist the create-time `service_urls` value immediately.
4. Use `SandboxRef.id` and identity-aware deletion waiting.
5. Only private adapter modules may import the S1a-selected generated types;
   retain and extend their offline contracts when implementing P2/T6.
6. The distribution, model decisions, S2a runtime setup, and S3a EchoEnv
   revalidation are complete. S4 can now build the lifecycle spike.
7. Extend contracts for adapter calls, response fields, and deletion outcomes
   in T6.

## P2 private adapter

`src/openenv_openshell/_adapter.py` defines the provider-facing
`SandboxAdapter` protocol and plain `CreateRequest`, `Sandbox`, and `Deletion`
models. The existing typed fake implements this protocol. `_sdk.py` is the
only production module importing OpenShell and its generated models.

`connect(gateway=...)` loads the SDK lazily, verifies its exact distribution
version, and calls public `SandboxClient.from_active_cluster(cluster=...)`.
`gateway` is a registered gateway name, matching the SDK's `cluster` argument;
no insecure TLS override is supplied. A public `health()` call must report
exactly `0.1.2` before sandbox creation. Missing/broken dependencies identify
`uv sync --locked` as the repair; gateway mismatch identifies the required
release. A failed connection check closes the acquired client even when that
cleanup itself fails. No sandbox mutation is retried automatically.

The adapter constructs generated workload inputs privately, retains the
create-time routes as a detached immutable mapping, and uses `timeout_seconds`
and `expected_sandbox_id` for public lifecycle waits. Delete requests use
`allow_missing=True`. Deletion results preserve `completed`, `accepted`,
`already_absent`, or `unknown`, plus the optional sandbox ID. Unknown outcomes
never imply successful cleanup. `close()` releases the client idempotently;
it does not delete a sandbox. Provider ownership and deletion decisions remain
P4/P6/P9 work.

Transport unavailability and authentication/authorization failures become
`OpenShellConnectionError`; other SDK and transport failures become the error
for the operation. Messages and displayed tracebacks omit raw SDK details,
credentials, environment values, and policy contents. The adapter emits no
logs. Policy conversion is strict and accepts only already-normalized wire
field mappings; file loading and schema-aware normalization remain SEC1.
The provider's configuration-to-request translation remains P3.

`tests/unit/test_adapter.py` exercises real SDK response/spec models with
signature-aware client doubles, without a CLI or gateway. These P2 tests
cover the adapter boundary but do not establish runtime enforcement.

## T6 adapter contract fixtures

[`tests/fixtures/openshell-0.1.2.json`](../tests/fixtures/openshell-0.1.2.json)
is the reviewed release snapshot. The offline
[`adapter contract tests`](../tests/unit/test_adapter_contract.py) compare it
with the installed wheel's exact public signatures (including parameter kinds,
defaults, and response annotations), response dataclass fields, health wire
fields, and deletion enum names/values. A method or model mismatch identifies
the contract that needs review.

The same fixture records the adapter's complete lifecycle call sequence and
arguments, including the serialized workload, policy, resources, atomic
service exposure, timeout keywords, missing-sandbox deletion, and original
sandbox identity. Signature-aware doubles return real SDK models. Tests verify
identity translation, unnamed/named routes, detached immutable route storage,
readiness responses without routes, and idempotent client closure. The existing
adapter tests cover all deletion outcomes, including absent IDs and unknown
future enum values. These checks require the locked Python wheel, but no
OpenShell CLI, gateway, or network calls.

For an SDK upgrade, inspect the new wheel, review changes to this snapshot and
the adapter together, update the dependency URL/hash and lock, and run
`make check`. Tests never regenerate or accept a new snapshot automatically.
Annotation-only changes also require explicit fixture review. Passing offline
contracts does not establish routing or policy enforcement on a live runtime;
the selected SDK/gateway pair still needs the roadmap's runtime validation.

## P3 provider request preparation

The provider's private `_create_request()` resolves ordinary configuration into
`CreateRequest` without opening a gateway connection. It takes an explicit,
normalized policy from the policy boundary; YAML loading and validation remain
SEC1 work. P4 will call this preparation step before connecting or creating.

An explicit non-`None` `port` overrides `service_port` and selects only the
sandbox service target. Both named and unnamed services use create-time
exposures. Empty images, invalid ports, malformed environment names/values,
and unsupported `start_container` options are rejected without echoing inputs.
Environment and policy inputs are copied, and their request representations are
redacted. No request preparation logs are emitted.

User labels are retained, with `managed-by=openenv-openshell` and
`openenv.provider=openshell` reserved for provider provenance. Image identity is
retained in the request's image field rather than copied into a length-limited
label. Providers and CPU/memory/GPU requests map directly through the adapter.
Gateway selection uses the configured registered name via the lazy connection
factory. Deadlines and `keep_sandbox` stay in provider configuration for lifecycle
operations; they are not workload fields. Workload startup and image entrypoint
handling remain S6a/P4 work.

`tests/unit/test_create_request.py` exercises these prepared inputs against the
pinned SDK models and a mocked public client. These are offline mapping checks,
not evidence of runtime resource enforcement or automatic image startup.
