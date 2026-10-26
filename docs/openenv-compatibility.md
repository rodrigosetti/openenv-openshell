# OpenEnv public client compatibility

P10 verifies the installed, unmodified `openenv.core.generic_client.GenericEnvClient`
with `OpenShellProvider` through `from_docker_image`. No environment-specific
client package, subclass, source patch, or replacement transport is used.

## Supported version

The tested OpenEnv range is **exactly 0.10.0**, pinned in `pyproject.toml` and
`uv.lock`. The former `>=0.4,<0.7` range was provisional, without version-matrix
evidence. Widen it only after testing factory, protocol, and cleanup contracts
against each added release. The current check uses Python 3.11.8.
OpenEnv 0.6.0 is no longer the supported client pin because cancellation during
factory connection can leak the provider.

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
    restricted_alpha_cleanup_acknowledged=True,
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

OpenEnv 0.10.0 includes [upstream PR #1309](https://github.com/openenv/OpenEnv/pull/1309),
merged at `4b0104b63f18129f04066e01fc974c010ee42d92` and listed in the
[0.10.0 release](https://github.com/openenv/OpenEnv/releases/tag/v0.10.0).
When a task is cancelled during the initial WebSocket connection after provider
startup, the unresolved factory calls client cleanup before propagating the
original `CancelledError`, including its message. No provider transport patch
or client subclass is needed. The three `ContainerProvider` lifecycle methods
retain their signatures; bootstrap remains lazy. The reviewed connection call
now also passes `additional_headers=None` by default.

`test_public_factory_task_cancellation` synchronizes real `Task.cancel()` with
the connection await. It checks a single deletion and deletion wait bound to
the confirmed ID, cleared ownership, adapter closure, and idempotent later
cleanup. Its failure control verifies that a deletion error does not replace
cancellation and that provider state permits an explicit confirmation retry.
`test_cancellation_during_socket_cleanup` separately cancels a connected client's
socket close and checks provider deletion plus a later socket drain. Existing
health/connection failure and async/sync protocol controls remain in the suite.

Cleanup is best effort if the gateway itself fails. Keep the provider reference
so its state can be inspected and `provider.close()` retried; retries confirm
the original identity rather than sending another name-based delete. When a
create response is ambiguous, ownership remains unknown and cleanup requires
operator inspection. The factory fix does not resolve the
[SEC8c atomic deletion limitation](cleanup-tests.md#sec8a-mitigation-and-remaining-blocker),
prove cancellation during every lifecycle phase, or add process-exhaustion
protection. An outer `with provider:` or `try/finally: provider.close()` can
remain useful for caller-owned cleanup, but is no longer required to work
around the initial factory connection leak on the pinned client.

The opt-in runtime cancellation control starts a real ASGI workload inside
OpenShell. It serves health and reports receipt of `/ws` while deliberately
leaving its handshake pending. The test cancels the unmodified factory only
after observing that receipt through the gateway route, then checks deletion
state, metadata, and independent SDK absence by name and ID before fixture
fallback cleanup. No runtime transport or lifecycle method is replaced.

## Evidence and limits

On October 24, 2026, OpenEnv 0.10.0 passed both EchoEnv client modes and the
real-handshake cancellation control on SDK/gateway 0.1.2 and the native arm64 VM
lane (three tests, 52.14 seconds). Every sandbox was independently absent before
fixture cleanup. Offline checks passed 471 unit tests and 101 compatibility
tests. Exact image, sandbox names, and upgrade evidence are recorded in the
[compatibility matrix](compatibility-matrix.md#live-pair-validation).

Historical baseline: verified September 30, 2026 with OpenEnv 0.6.0 and SDK/gateway 0.1.2 and the native Apple Silicon
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
reconnects, arbitrary images, or other compute drivers.
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
