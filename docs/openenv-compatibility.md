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
assertions; S5a retains remote validation. Security denial acceptance remains SEC5/SEC6.
