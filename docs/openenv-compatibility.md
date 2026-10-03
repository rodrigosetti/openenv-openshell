# OpenEnv public client compatibility

P10 verifies the installed, unmodified `openenv.core.generic_client.GenericEnvClient`
with `OpenShellProvider` through `from_docker_image`. No environment-specific
client package, subclass, source patch, or replacement transport is used.

## Supported version

The tested OpenEnv range is **exactly 0.6.0**, pinned in `pyproject.toml` and
`uv.lock`. The former `>=0.4,<0.7` range was provisional, without version-matrix
evidence. Widen it only after testing factory, protocol, and cleanup contracts
against each added release. This check used Python 3.11.8.

I6 makes the singleton range explicit in the
[client/SDK/gateway matrix](compatibility-matrix.md), with a focused offline
command and a dedicated CI dependency-pair job.

## Local check

Complete the [local setup](local-openshell-testing.md) and build the
[pinned native arm64 EchoEnv image](echo-env-image.md), then run:

```bash
OPENENV_OPENSHELL_ECHO_IMAGE_ID="$(cat tests/integration/images/echo/local-image-id.txt)" \
  uv run pytest -m integration --no-cov tests/integration/test_openenv_client.py -v
```

The test uses the public provider with an initial explicit policy granting the
image's required `/app` access. No additional image environment is required for
this validated workload. The caller's exact argv establishes its directory:

```python
from pathlib import Path
from openenv.core.generic_client import GenericEnvClient
from openenv_openshell import OpenShellProvider

image = Path("tests/integration/images/echo/local-image-id.txt").read_text().strip()
provider = OpenShellProvider(
    sandbox_name="oe-client-example",
    command=[
        "sh", "-c",
        "cd /app/env && uvicorn server.app:app --host 0.0.0.0 --port 8000",
    ],
    policy=Path("tests/integration/images/echo/policy.yaml"),
)
env = GenericEnvClient.from_docker_image(image, provider=provider).sync()
with env:
    env.reset()
    result = env.step({
        "type": "call_tool",
        "tool_name": "echo_message",
        "arguments": {"message": "hello"},
    })
    assert result.observation["result"]["data"] == "hello"
    assert env.state()["step_count"] == 1
assert provider.state.deleted
```

In async code, await the same factory and use `async with env` and awaited
`reset`, `step`, and `state` calls. The factory waits for HTTP health before
connecting `/ws`; client context exit calls provider cleanup. Factory keyword
arguments such as `port` and `env_vars` are forwarded to `start_container`.
The port chooses routing and must match the workload's actual listener.

## Async factory cancellation

`openenv-openshell-iru` remains an upstream lifecycle blocker. In the locked
OpenEnv 0.6.0 wheel, `_BootstrapResult._resolve_async()` consumes the provider
bootstrap before awaiting `client.connect()`. `_connect_async()` catches
`Exception` around `ws_connect`, while `asyncio.CancelledError` derives from
`BaseException`. Cancellation at that await therefore leaves an owned sandbox
without returning a client to the caller. Normal HTTP and WebSocket exceptions
still trigger cleanup; they do not establish cancellation safety.

Use an outer synchronous provider context, entered **before** awaiting the
factory, and retain it through client use:

```python
with provider:
    env = await GenericEnvClient.from_docker_image(image, provider=provider)
    async with env:
        await env.reset()
        # Await step/state and other application work here.
```

Alternatively, keep the provider reference and close it in `finally`:

```python
try:
    env = await GenericEnvClient.from_docker_image(image, provider=provider)
    async with env:
        await env.reset()
finally:
    provider.close()
```

Both patterns use the configured `provider` and `image` above. Cleanup runs
synchronously as the cancelled task unwinds, so a second task cancellation does
not interrupt it at an asyncio await. It can block the event loop for the
deletion wait. Successful cleanup preserves the original cancellation and is
idempotent after normal client close. A cleanup failure can supersede the
cancellation; retain the provider and retry `stop_container()` for confirmation
or inspect it with an operator. `keep_sandbox=True` intentionally retains the
runtime. An ambiguous create still has no proven ownership: these patterns must
not delete its attempted name. The existing identity preflight/name-reuse limit
also remains; see [cleanup guarantees](cleanup-tests.md#sec8a-mitigation-and-remaining-blocker).

Offline regression tests in `tests/unit/test_openenv_client.py` use real
`Task.cancel()` after an event confirms WebSocket connection has begun. They
record the unguarded factory leak and verify context/finally cleanup, the original
cancellation message, one deletion of the original identity, adapter closure,
and cancellation while the client's socket cleanup is awaiting completion.
These replace only external I/O and use the installed, unmodified client.

Verified October 3, 2026 on Python 3.11.8 using a fresh `uv sync --locked`
environment: `make check` passed (473 tests, strict Pyright, Ruff, 99.54%
coverage), and `make compatibility` passed (103 tests). No live gateway was
contacted for this regression/workaround evidence.

This workaround does **not** satisfy the automatic factory cancellation
guarantee. Closing the issue requires a reviewed supported upstream fix and
dependency pin, compatibility checks, and a disposable runtime cancellation
control. Do not patch OpenEnv at import time or substitute its transport.

## Evidence and limits

Verified September 30, 2026 with SDK/gateway 0.1.2 and the native Apple Silicon
VM driver: **both runtime tests passed**. Each mode completed HTTP health, two
reset episodes, four echo steps, state checks, and client context cleanup.
Before fallback teardown, the test asserted deleted provider state and timestamps;
an independent SDK listing confirmed sandbox absence. Sandboxes
`oe-p10-d4b780b8` (async) and `oe-p10-731a7a2e` (sync) were deleted.

Offline tests replace only gateway/HTTP/WebSocket I/O, exercising upstream
bootstrap, message dispatch, route-prefix preservation, default keepalive
arguments, forwarded startup inputs, repeated close, and cleanup after health
or WebSocket connection failure in both modes. `tests/openenv_client.py` supplies
test-only structural types for OpenEnv's incompletely typed bootstrap/dispatch
API; it casts the installed class without wrapping its behavior.

This local check does not validate remote authentication, long idle sessions,
reconnects, other OpenEnv releases, arbitrary images, or other compute drivers.
The image ID is local Docker configuration identity, not a pullable registry
digest. I2 extends this check with the I1 runtime fixture and broader EchoEnv
assertions. S5a ran this test against a remote mTLS gateway. Both modes failed
explicitly with `ServiceAccessError`, because the route requires a TLS client
certificate. See [remote evidence](protocol-spike.md#remote-gateway-validation-s5a-2026-09-30).
Security denial acceptance remains SEC5/SEC6.

S5b also ran this suite on a remote OIDC-configured Docker-driver gateway,
using the pinned amd64 registry image. Both modes passed without a TLS client
certificate or service bearer token. The SDK alone used OIDC for lifecycle
RPCs. See [OIDC evidence](protocol-spike.md#oidc-remote-gateway-validation-s5b-2026-10-01).
