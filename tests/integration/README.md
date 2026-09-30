# Integration tests

Tests in this directory exercise real transports or an OpenShell runtime.
Mark each test with `@pytest.mark.integration`; they are excluded from the
default unit-test run configured in `pyproject.toml`.

`test_http_readiness.py` uses a local HTTP server and needs no OpenShell gateway:

```bash
uv run pytest -m integration tests/integration/test_http_readiness.py --no-cov
```

Before running tests that require an OpenShell gateway, complete the
[local OpenShell setup](../../docs/local-openshell-testing.md) and ensure
`make openshell-smoke` passes.

For the native arm64 EchoEnv image, follow the [S3 build and validation
guide](../../docs/echo-env-image.md). Its opt-in test requires
`OPENENV_OPENSHELL_ECHO_IMAGE_ID` and CLI/gateway 0.1.2; without the image ID
it skips before touching a runtime. It supplies the image-specific
[policy fixture](images/echo/policy.yaml), which extends the runtime baseline
with read-only `/app` access and retains deny-by-default egress. This image-only
probe uses `--no-cov`
because it does not execute provider code. Unit coverage remains enforced by
`make check`.

The [S5 protocol probe](../../docs/protocol-spike.md) uses the same explicit
image opt-in and SDK lifecycle helper to verify routed health, two reset/step/state
episodes, echo results, WebSocket ping/pong, and identity-aware deletion:

```bash
OPENENV_OPENSHELL_ECHO_IMAGE_ID="$(cat tests/integration/images/echo/local-image-id.txt)" \
  uv run pytest -m integration --no-cov tests/integration/test_protocol_spike.py \
  -v --log-cli-level=INFO
```

## S6a image startup comparison

See [the startup evidence](../../docs/image-startup.md) for the omitted-command
limitation and explicit-command protocol success on SDK/gateway 0.1.2.

```bash
OPENENV_OPENSHELL_ECHO_IMAGE_ID="$(cat tests/integration/images/echo/local-image-id.txt)" \
  uv run pytest -m integration --no-cov tests/integration/test_image_startup.py \
  -v --log-cli-level=INFO
```

Both cases verify deletion. The negative case records that Ready alone does
not establish image startup; it expects routed health to time out. Revisit this
assertion when upgrading to a runtime with automatic image startup support.

## SEC4 policy before execution

SEC4 exercises policy loading and the production adapter against the real
gateway. Invalid YAML and malformed direct adapter policies must send no create
RPC, and a label-filtered runtime listing must confirm no sandbox exists. The
valid control asserts the normalized policy is embedded before the create RPC,
runs EchoEnv through the atomic route, and verifies identity-aware deletion:

```bash
OPENENV_OPENSHELL_ECHO_IMAGE_ID="$(cat tests/integration/images/echo/local-image-id.txt)" \
  uv run pytest -m integration --no-cov tests/integration/test_policy_before_execution.py \
  -v --log-cli-level=INFO
```

Verified on 2026-09-30 with SDK/gateway 0.1.2 and the pinned native arm64 image:
invalid inputs sent no create RPC and produced no sandbox; the valid control
passed HTTP health, two reset/step/state episodes, four echo steps and ping/pong;
`oe-sec4-7096bbed` was deleted and absence confirmed. `make check` passed 247
unit tests with 99.38% branch-inclusive coverage, lint and strict typing.

The test supplies the previously validated EchoEnv command in `CreateRequest`
through the S6b production adapter translation. Provider lifecycle remains P4.
S6a documents why omitted commands cannot start this image on the selected runtime. This verifies
the loader/adapter gate and initial policy submission; it does not establish
gateway rejection of every semantically invalid policy, filesystem/network
denials (SEC5/SEC6), automatic image command handling, or a complete provider
lifecycle. P4 must load explicit policy before connecting/creating and preserve
this atomic submission path.

## SEC7 managed credential visibility

The SEC7 test requires CLI/SDK/gateway 0.1.2 and the same pinned image. It imports
its own uniquely named profile, creates a provider with a random synthetic
credential, and selects the instance through production request preparation and
the adapter. It sends no requests to credential endpoints and uses no real
service secrets. Both initial workload and exec environment prints must show a
present opaque placeholder, exclude the synthetic secret, and retain a readable
ordinary environment control. Routed EchoEnv health and protocol provide the
positive workload control. Sandbox deletion is verified by identity and absence;
the temporary provider and profile are then deleted. Runtime setup failures
fail the opted-in test rather than silently skipping credential verification.

```bash
OPENENV_OPENSHELL_ECHO_IMAGE_ID="$(cat tests/integration/images/echo/local-image-id.txt)" \
  uv run pytest -m integration --no-cov tests/integration/test_managed_credentials.py \
  -v --log-cli-level=INFO
```

The explicit image command uses production `command` configuration and adapter
mapping while P4 startup wiring remains pending. See [security guidance](../../docs/security.md)
for the credential boundary and limits of this test.

Verified on 2026-09-30 with CLI/SDK/gateway 0.1.2 and the pinned native arm64
EchoEnv image: initial workload and exec environment prints contained opaque
credential placeholders and no synthetic secret; the ordinary environment
control remained readable. Routed health, two reset/step/state episodes, four
echo steps, and ping/pong passed. Sandbox absence and disposable provider/profile
cleanup succeeded. `make check` passed 271 unit tests, Ruff, strict Pyright, and
99.40% branch-inclusive coverage. This is a local credential visibility result;
endpoint rewriting and remote credential behavior remain unverified.

## P4 provider startup

The production provider now loads explicit policy before connecting, submits exact
argv/environment through the adapter, captures the selected create-time route,
and waits for sandbox readiness. This opt-in runtime test exercises provider
startup, HTTP health, and the routed EchoEnv protocol. P6 extends teardown to
call public `stop_container()` twice and independently verify sandbox absence
through the SDK. Unit tests cover identity-safe waits, partial initialization,
keep_sandbox, uncertain acknowledgements, and retry after deletion/wait/close
failures.

```bash
OPENENV_OPENSHELL_ECHO_IMAGE_ID="$(cat tests/integration/images/echo/local-image-id.txt)" \
  uv run pytest -m integration --no-cov tests/integration/test_provider_startup.py \
  -v --log-cli-level=INFO
```

Verified on 2026-09-30 with the local SDK/gateway 0.1.2 and pinned arm64 image:
provider startup and HTTP health passed; routed WebSocket passed two reset/step/state
episodes, four echo steps and ping/pong. Sandbox `oe-p4-0eeac947` deletion and
absence were verified. This does not establish unmodified-client lifecycle or
remote service support (P10/I2/S5a).

P6 verified on 2026-09-30 with the local SDK/gateway 0.1.2 and pinned arm64
image: provider startup, HTTP health, two WebSocket reset/step/state episodes,
and four echo steps passed. Public cleanup deleted `oe-p4-9665df1a`; a second
stop was harmless, local ownership was cleared, and the independent SDK listing
confirmed absence. `make check` passed Ruff, strict Pyright, and 310 unit tests
with 99.48% branch-inclusive coverage (provider 100%). This local result does not
establish remote service support or unmodified-client lifecycle behavior.

P9 extends this test to four cleanup paths: `stop_container()`, `close()`,
normal provider context exit, and context exit after a body exception. Each path
checks cleared ownership and independently confirms sandbox absence. Verified
on 2026-09-30 with local SDK/gateway 0.1.2 and the pinned arm64 image: all four
cases passed routed health, WebSocket protocol, and deletion checks. `make check`
passed Ruff, strict Pyright, and 334 unit tests with 99.48% branch-inclusive
coverage (provider 100%). Offline tests additionally cover pre-start close,
repeated cleanup, keep_sandbox, partial startup rollback, and retry after
delete/wait/client-close failures on context exit.

## P7 failed-start cleanup

`test_provider_startup.py` also injects failures at the real adapter boundary:
create completes but its response is lost, the selected service URL is absent,
and readiness fails after create. Each case verifies automatic rollback through
public cleanup and independent label-filtered sandbox absence. A workload that
never serves health verifies timeout followed by public cleanup, matching the
OpenEnv teardown contract. Direct provider callers must stop after health or
connection failure; readiness itself does not delete the sandbox.

Run the P4/P6 control and P7 failures with the same image opt-in command above.
Unit tests additionally cover state-update failures, secret-safe rollback retry
notes, recovery of identity after a lost create response, delete/wait/close retry,
uncertain acknowledgements, and debug retention. Rollback uses `stop_container()`
and preserves the sanitized startup error; failed cleanup adds a fixed exception
note instructing the caller to retry. Successful keep-mode rollback releases
local ownership and leaves the sandbox running for inspection.

Verified on 2026-09-30 with local SDK/gateway 0.1.2 and the pinned arm64 image:
all five provider integration cases passed, including the healthy routed
WebSocket control and all four failure scenarios; all sandbox absence checks
passed. Both loopback HTTP readiness tests also passed (seven integration tests
total). `make check` passed Ruff, strict Pyright, and 340 unit tests with 99.47%
branch-inclusive coverage (provider 100%). Unmodified-client integration and
remote service support remain P10/I2/S5a.

After incorporating P8 logging/metadata and P9 close/context cleanup from `main`,
`make check` passed 365 unit tests, Ruff, strict Pyright, and 99.50% coverage
(provider 100%). The combined runtime suite passed all ten cases: four healthy
cleanup paths, four failed-start/health cleanup paths, and two loopback HTTP
readiness cases. Independent SDK absence checks passed for every runtime sandbox.

## I1 reusable runtime fixture

New EchoEnv and security E2E tests can request `openshell_runtime` from
`conftest.py`. They must carry the `integration` marker. Without an explicit
`OPENENV_OPENSHELL_ECHO_IMAGE_ID`, the fixture skips before gateway access.
Once opted in, gateway/version/workspace failures fail the test. The fixture
connects to an existing registered local gateway; it does not install or restart
runtime services. Prepare that gateway using the local setup guide above.

`OPENSHELL_GATEWAY` selects a registered gateway (otherwise the active gateway
is used), and `OPENSHELL_WORKSPACE` selects the workspace (default `default`).
The image variable may contain the validated local image ID or an explicitly
selected compatible OCI image. The default command and policy target the
checked-in EchoEnv image; other workloads must supply their exact command and
policy to `openshell_runtime.provider(command=..., policy=...)`. Image selection
does not build an image or infer its startup metadata.

```python
@pytest.mark.integration
def test_workload(openshell_runtime: Runtime) -> None:
    provider = openshell_runtime.provider()
    url = provider.start_container(openshell_runtime.image)
    provider.wait_for_ready(url, timeout_s=30)
    # Exercise the client or security checks here.
```

The fixture registers each uniquely named provider before startup. Teardown
runs on normal exit, assertion/setup failure, Ctrl-C, and catchable SIGTERM,
including interruption during create/readiness. It cleans every registered
provider, retries a cleanup failure once, restores the prior SIGTERM handler,
and reports persistent cleanup failure without hiding a primary test failure.
Create providers through this factory to receive those guarantees. No Python
finalizer can handle SIGKILL, host termination, or a permanently unavailable
gateway; cleanup failures remain explicit and require retrying the named sandbox.

Pytest's `OpenShell E2E` teardown report section contains generated sandbox
names and fixed lifecycle flags before and after cleanup. It excludes argv,
environment, policy contents, image references, service URLs, raw SDK output,
and credentials. For runtime troubleshooting use the named sandbox and the
local setup guide's workspace listing commands.

Run the healthy workload and SIGTERM controls, which independently confirm
sandbox absence through the public SDK:

```bash
OPENENV_OPENSHELL_ECHO_IMAGE_ID="$(cat tests/integration/images/echo/local-image-id.txt)" \
  uv run pytest -m integration --no-cov tests/integration/test_runtime_fixture.py -v
```

Offline controls in `tests/unit/test_runtime_fixture.py` exercise body and
startup interruptions, signal restoration, cleanup retries, continued cleanup
of other providers, and sanitized diagnostics. I2 and I3 use this fixture for
their client and security acceptance work; these fixture controls do not close
those acceptance gates.

Verified on 2026-09-30 with local SDK/gateway 0.1.2 and the pinned native arm64
image: both healthy and SIGTERM controls passed routed HTTP/WebSocket protocol
and independent sandbox absence checks. `make check` passed Ruff, strict
Pyright, and 380 unit tests with 99.50% provider-package coverage.
