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
startup, HTTP health, and the routed EchoEnv protocol. Public `stop_container`
remains P6; this test uses SDK teardown and verifies sandbox absence.

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
