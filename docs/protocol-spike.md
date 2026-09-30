# Routed protocol spike (S5)

The opt-in [protocol test](../tests/integration/test_protocol_spike.py) extends
the [S4 lifecycle experiment](lifecycle-spike.md) with a probe that runs while
the sandbox is alive. It uses the pinned SDK's atomic unnamed service exposure,
the S3a policy and image, and the image's explicit canonical command. It does
not exercise the production provider or establish automatic image CMD handling.
The lifecycle helper still deletes the sandbox in `finally` and waits for
absence with the original ID, including when the protocol probe fails or is
interrupted. Offline tests cover those new failure paths.

Run after the [local setup](local-openshell-testing.md) and
[image preparation](echo-env-image.md):

```bash
OPENENV_OPENSHELL_ECHO_IMAGE_ID="$(cat tests/integration/images/echo/local-image-id.txt)" \
  uv run pytest -m integration --no-cov tests/integration/test_protocol_spike.py \
  -v --log-cli-level=INFO
```

Without the image variable the test skips before acquiring a client. The SDK
selects the active gateway or `OPENSHELL_GATEWAY`; `OPENSHELL_WORKSPACE` defaults
to `default`. The current image input accepts only validated local image IDs.
Coverage is disabled for this runtime-only experiment; `make check` retains the
production coverage gate.

## Protocol and transport

The test polls `/health` for up to 60 seconds with two-second HTTP timeouts and
requires HTTP 200 plus `status: healthy`. It then opens `/ws`, performs two
episodes on the same connection, and checks:

- Each reset returns an observation, `done: false`, and reward zero.
- State starts at step count zero and has a nonempty episode ID.
- Each episode sends `hello` and `hello again` to the MCP `echo_message` tool.
- Each tool observation has no error and returns the exact requested text.
- State retains the episode ID and increments the step count after each step.
- A WebSocket ping receives a pong after every step.
- The second reset creates a new episode ID. The session then sends `close`.

The pinned server is OpenEnv 0.3.1 with FastMCP 3.1.1. Its reset observation
serializes as an empty object because its serializer omits metadata. Its
`CallToolObservation.result` is a FastMCP object with `data: "hello"` and
`is_error: false`, rather than a bare string. The probe sends the normal OpenEnv
wire envelope: `type: step`, with `data` containing `type: call_tool`,
`tool_name: echo_message`, and `arguments: {message: hello}`. This establishes
wire compatibility; unmodified client/provider API validation remains P10.

For local `*.openshell.localhost` routes, HTTP and WebSocket TCP connections go
to gateway loopback while retaining the returned route's Host header. No system
DNS changes or Docker port publishing are needed. All requests still pass
through OpenShell's service route. Other hostnames use normal DNS, and HTTPS/WSS
retain certificate verification; that branch has not been validated remotely.
WebSocket open/close timeouts are five seconds and each receive is bounded to
ten seconds. Ping/pong checks establish short-session liveness, not a long idle
or reconnect guarantee.

## Verified local outcome (2026-09-29)

SDK/gateway 0.1.2, workspace `default`, native Apple Silicon VM, and local image:

```text
sha256:21f3855dde019fb73eccc853f0d14308fbca702b30357add0bbb0cbc898a18f6
```

Sandbox `oe-s4-2c7093fb20`, ID `18db1706-00e0-4697-a678-42459fa58b54`,
passed health, both episodes, all four echo steps, state assertions, and
ping/pong through:

```text
http://default--oe-s4-2c7093fb20.openshell.localhost:17670/
```

Deletion and identity-aware absence verification passed. The test completed in
16.44 seconds. Two earlier assertion failures exposed the serialization details
above; both failed attempts also completed sandbox deletion and absence checks.
The policy and gateway settings were unchanged. `make check` passed formatting,
lint, strict typing, and 171 unit tests with 100% production branch coverage.
The check used the already installed environment (`UV_NO_SYNC=1`) because the
sandbox's fresh uv cache could not fetch the pinned wheel over the network.

## Remote gateway findings and remaining scope

`openshell gateway list --output json` reports exactly one registered gateway:
`openshell`, local, active, mTLS, `https://localhost:17670`. No remote gateway or
remote workspace credentials are available. The local service itself required
no additional application credentials. This says nothing about a remote
service's authentication requirements.

Remote health/WebSocket sessions, certificate behavior, and service
authentication remain unverified. The checked-in image ID is a local Docker
configuration ID and cannot be pulled remotely. Beads **S5a** tracks obtaining
authorized remote access and a pullable immutable image, extending the opt-in
probe, and validating an unmodified OpenEnv client. It blocks the M3 release
gate. S6 must preserve these unknowns when resolving spike questions; this local
result does not close M0, prove security enforcement, or establish remote support.
