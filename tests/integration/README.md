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

The test supplies the previously validated EchoEnv command only at the SDK
boundary because S6a/P4 have not implemented provider startup. This verifies
the loader/adapter gate and initial policy submission; it does not establish
gateway rejection of every semantically invalid policy, filesystem/network
denials (SEC5/SEC6), automatic image command handling, or a complete provider
lifecycle. P4 must load explicit policy before connecting/creating and preserve
this atomic submission path.
