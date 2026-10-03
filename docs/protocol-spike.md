# Routed protocol spike (S5)

The opt-in [protocol test](https://github.com/rodrigosetti/openenv-openshell/blob/main/tests/integration/test_protocol_spike.py) extends
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
to `default`. The image input accepts a local `sha256:` image ID or a
registry repository pinned by manifest digest (`registry/repo@sha256:...`);
tags are rejected.
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
through OpenShell's service route. Other hostnames use normal DNS and must use
HTTPS/WSS with certificate verification. S5a validated that branch remotely
(see below). Untrusted certificates and client-certificate demands fail
immediately rather than as a health timeout.
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

## Remote gateway validation (S5a, 2026-09-30)

S5a repeated the probe against a remote OpenShell 0.1.2 gateway on a disposable
GCE VM (`us-east1-b`, e2-standard-2, Ubuntu 24.04 amd64). The gateway ran the
pinned `ghcr.io/nvidia/openshell/gateway:0.1.2` container with the Docker
compute driver and the standard mTLS configuration: a private CA from
`generate-certs`, `client_ca_path` set, mTLS user authentication, and no OIDC.
The server certificate carried the wildcard SAN `*.104-196-50-8.sslip.io`,
which is what enables sandbox service URLs under that domain. The firewall
admitted only the tester's address. [Remote gateway setup](remote-gateway-testing.md)
lists the exact configuration. The VM, firewall rule, and gateway were deleted
afterwards.

The image was pulled anonymously from GHCR by manifest digest:

```text
ghcr.io/rodrigosetti/openenv-openshell-echo@sha256:02ea3505fc0b0a451778442ca2994c6be94a45ae4572358899b41b98c1df60a0
```

It is the pinned [Dockerfile](https://github.com/rodrigosetti/openenv-openshell/blob/main/tests/integration/images/echo/Dockerfile)
built for linux/amd64
(`sha256:f7bac7ca74ba3950b98508e838a3fe2ee5a90fd46334cea13875dfb83030f1c8`),
plus the [Docker-driver layer](https://github.com/rodrigosetti/openenv-openshell/blob/main/tests/integration/images/echo/Dockerfile.docker-driver).
See [image evidence](echo-env-image.md#docker-driver-variant-s5a).

The client trusted the gateway's private CA through `SSL_CERT_FILE`, set to a
bundle of the public roots plus that CA. Setting only the private CA also
replaces the public roots for uv and other tools. Certificate verification
stayed enabled throughout.

### Results

| Client | TLS client certificate | Result |
|---|---|---|
| Raw probe, this test | none | Fails in 2.7 s: `Service route requires a TLS client certificate` |
| Raw probe, this test | gateway client certificate | Passes: health, two episodes, four echo steps, state, ping/pong |
| Unmodified OpenEnv client, async and sync ([P10 test](https://github.com/rodrigosetti/openenv-openshell/blob/main/tests/integration/test_openenv_client.py)) | none (cannot present one) | Fails: `ServiceAccessError: OpenShell service route requires a TLS client certificate` |

Every run deleted its sandbox and verified absence by the original ID, and the
gateway listed no sandboxes afterwards.

With the gateway's client certificate, the remote route
`https://default--oe-s4-196d7cbf3f.104-196-50-8.sslip.io:8080/` (sandbox ID
`85cc9027-8e34-4144-b25a-60a1596cc3f5`) passed HTTP health and the full
WebSocket session over verified HTTPS/WSS in 21.8 s. Gateway routing,
WebSocket upgrades, and short-session ping/pong therefore work remotely.

The service route shares the gateway's multiplexed listener. With
`client_ca_path` and no OIDC, that listener demands a client certificate at the
TLS layer. A connection without one receives the TLS 1.3
`certificate_required` alert, before any HTTP exchange. The same request with
the gateway client certificate reached the router and returned HTTP 404 for a
nonexistent sandbox. OpenEnv's client has no option for presenting a client
certificate. The provider must not copy gateway credentials into the URL or
workload (see SPEC section 13.1).

### Conclusions

- **Remote mTLS gateways are not supported for unmodified OpenEnv clients.**
  The provider now fails explicitly with `ServiceAccessError` at readiness
  instead of timing out, for both a required client certificate and an
  untrusted route certificate.
- Remote routing, HTTPS/WSS, and ping/pong are validated when the client can
  satisfy the gateway's TLS requirements.
- Not validated: OIDC or edge-authenticated gateways, where bearer-only
  clients may connect without a certificate; HTTP 401/403 service
  challenges; long idle sessions and reconnects. HTTP 401/403 keep the existing
  retry-until-timeout behavior because none was observed. S5b below subsequently
  validated an OIDC gateway with the unmodified client.
- The OpenShell 0.1.2 Docker driver rejects images that resolve to UID 0 and
  needs a workdir the workload identity can write. The VM-lane image did not
  meet either requirement.

### Commands

```bash
OPENSHELL_GATEWAY=openenv-s5a \
SSL_CERT_FILE=/path/to/public-roots-plus-gateway-ca.pem \
OPENENV_OPENSHELL_ECHO_IMAGE_ID="$(cat tests/integration/images/echo/remote-image-ref.txt)" \
  uv run pytest -m integration --no-cov tests/integration/test_protocol_spike.py \
  -v --log-cli-level=INFO
```

Add `OPENENV_OPENSHELL_PROBE_CLIENT_CERT_DIR=~/.config/openshell/gateways/openenv-s5a/mtls`
to present the gateway client certificate (`tls.crt` and `tls.key`). This
validates transport only. It is not an unmodified-client result. The same
environment, without that variable, runs `tests/integration/test_openenv_client.py`.

## M0 acceptance verification (2026-09-30)

With all M0 prerequisites closed, the protocol test above was rerun on the same
pinned image, SDK/gateway 0.1.2, `default` workspace, and native Apple Silicon VM
setup. `make openshell-prereqs` passed, including authenticated gateway access
and workspace access. The test passed in 16.37 seconds with sandbox
`oe-s4-5e60df02cb`, ID `1f7f16d7-84c7-474d-856b-8f62f0271f3a`, through:

```text
http://default--oe-s4-5e60df02cb.openshell.localhost:17670/
```

HTTP health, two WebSocket reset episodes, four exact echo results, state
transitions, and ping/pong all passed. The lifecycle helper then deleted the
sandbox and verified absence using the original sandbox ID. This satisfies
M0's acceptance criterion: EchoEnv reset and step through an OpenShell-managed
service, followed by sandbox deletion.

`UV_CACHE_DIR=/private/tmp/openenv-openshell-m0-uv-cache UV_NO_SYNC=1 make check`
passed formatting, lint, strict typing, and 239 unit tests with 99.69% production
branch coverage against the installed environment. Gateway checks and the
protocol test required execution outside the network sandbox; the initial
sandboxed prerequisite check could not connect to localhost.

M0 is a local spike gate. Production provider startup/cleanup, unmodified-client
integration, automatic image startup (S6a), remote validation (S5a), and security
enforcement acceptance remain their respective downstream tasks.

## OIDC remote gateway validation (S5b, 2026-10-01)

The disposable GCE VM `openenv-s5b-gateway` ran Ubuntu 24.04 amd64,
`e2-standard-2`, in `us-east1-b`, using the OpenShell 0.1.2 Docker driver and
Keycloak 26.0.8. Its firewall admitted port 8080 only from the tester's public
IP. The routing domain was `35-229-78-209.sslip.io`. The gateway image resolved
to `sha256:2fe4dad9118e14ab80a8258b545ea6e6cd74c3469e24ad4e6610f964d98913a2`;
Keycloak resolved to
`sha256:09a381c715ab0b111835b70f2905955274843a219c6f27efb348e4d9f4086858`.
The EchoEnv image was the same manifest-pinned amd64 image used for S5a above.

[The OIDC bootstrap](examples/remote-oidc-gateway-bootstrap.sh) and
[reproduction commands](remote-gateway-testing.md#oidc-variant-s5b) record the
complete fixture. Keycloak's issuer and discovery/JWKS endpoints used numeric
loopback HTTP on the VM with the gateway's explicit development acknowledgement.
Remote gateway and service traffic used HTTPS/WSS with certificate verification
and a public-roots-plus-private-CA bundle; verification was never disabled.
This tests the service-routing authentication boundary, not production IdP
transport, browser login, token renewal, or a shared multi-user deployment.

The gateway retained its guest/client CA but disabled mTLS user authentication
and enabled OIDC. In the pinned
[listener configuration](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/crates/openshell-server/src/cli.rs),
`require_client_auth` is `has_client_ca && !has_oidc`. Gateway startup confirmed
OIDC discovery and one usable signing key loaded from Keycloak. The imported
service account token had audience `openshell-cli` and role `openshell-admin`.

The isolated SDK configuration contained the CA and OIDC token, with **no TLS
client certificate or key**. Protected `list(workspace="default")` calls using
CA-only TLS returned `UNAUTHENTICATED` with a missing token and with an invalid
token; the valid Keycloak bearer succeeded and health reported version 0.1.2.
The unmodified OpenEnv client received no bearer token or TLS client identity.

### Results

| Check | Service credentials | Result |
|---|---|---|
| Raw protocol probe | None | HTTP health, two episodes, four echo steps, state, ping/pong passed |
| Unmodified OpenEnv 0.6.0 async client | None | Health, two episodes, six echo steps including Unicode, state, client cleanup passed |
| Unmodified OpenEnv 0.6.0 sync client | None | Same assertions and cleanup passed |

The final combined run reported **3 passed in 79.57 seconds**. Its protocol
sandbox was `oe-s4-f2927e7a91`, ID `c2e011ba-ad99-4a0a-a45a-06256f33d445`,
using:

```text
https://default--oe-s4-f2927e7a91.35-229-78-209.sslip.io:8080/
```

The async and sync provider sandboxes were `oe-e2e-2d7f2af057` and
`oe-e2e-8a14a88a36`. Each client close deleted its sandbox; the tests checked
provider deletion metadata and gateway absence before fallback fixture cleanup.
The protocol helper verified absence with the original sandbox ID. A final
protected gateway list returned zero sandboxes.

An earlier combined run passed the protocol probe but failed both client tests
in their additional health assertion: `httpx.Client(trust_env=False)` ignored
`SSL_CERT_FILE`. Provider readiness itself had already passed. The assertion
now passes `ssl.create_default_context()` explicitly, retaining both CA
verification and disabled proxy lookup. The OpenEnv client and provider
transport were unchanged. Cleanup succeeded for those failed attempts too.

### Support boundary

This tested OIDC configuration supports the unmodified client. **OIDC protects
gateway lifecycle RPCs, not the service routes in this deployment.** Service
routes admitted anonymous HTTP/WebSocket traffic within the IP-restricted
network boundary. Do not infer per-user service access control from successful
gateway authentication or generalize this result to an authenticating edge
proxy. Standard remote mTLS remains unsupported as established by S5a.

No HTTP 401/403 service challenge was observed. Transient startup HTTP 502
responses recovered through the existing retry path. Provider behavior was not
changed: observed TLS challenges still fail explicitly with `ServiceAccessError`
and retain offline regression tests; HTTP 401/403 challenge handling remains
unvalidated and retains its existing retry behavior. Long idle sessions,
reconnects, and edge authentication remain unverified.

`UV_CACHE_DIR=/private/tmp/openenv-s5b-uv-cache UV_NO_SYNC=1 make check` passed
formatting, lint, strict typing, and 457 unit tests with 99.52% production branch
coverage. `sh -n` passed for the new bootstrap, and `git diff --check` passed.
The disposable VM, boot disk, firewall rule, and isolated credential directory
were removed after validation; the active local gateway was never changed.
