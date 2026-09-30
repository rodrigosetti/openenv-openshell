# Spike decisions (S6)

These decisions apply to the pinned OpenShell SDK/gateway **0.1.2** pair.
They guide provider implementation; the provider's start/stop methods are
still pending. Existing runtime evidence comes from the separate S3a/S4/S5
experiments. S6 changes requirements and documentation, not runtime behavior.

| Question | Decision and evidence | Remaining validation |
| --- | --- | --- |
| Target-port precedence | Explicit non-`None` `start_container(port=...)` overrides constructor `service_port`; otherwise use `service_port`, default 8000. Validate before create. The value is the sandbox target port and does not change the workload's listen port. The spike tested 8000 only. | P3/T2 must test overrides, defaults, and invalid inputs. |
| Service naming | Default to the unnamed service (`""`); use an explicit `service_name` unchanged. Create the exposure atomically and persist the exact matching create-time URL before readiness polling. Fail and clean up if that route is missing or unusable. S3a verified a named route; S4/S5 verified the unnamed route. | P3/P4/T2 must exercise both names, route selection, and missing-route cleanup through the provider. |
| Image constraints | Compatibility is driver-specific. Use the validated native arm64 image for the Apple Silicon VM lane. Its utilities, executable lookup, and read-only `/app` policy are required by the tested setup. S6a found omitted command selects a shell; explicit CMD passes health/protocol. | S6b selects explicit caller argv/environment/directory; P4 must wire startup; **S5a:** the Docker driver needs a non-root identity and a writable workdir; the remote run used a digest-pinned amd64 variant (see image evidence). |
| Service authentication | The local HTTP/WebSocket route needed no extra application credentials; SDK lifecycle calls used mTLS. Treat these as separate authentication contracts. Preserve TLS verification and require a URL usable by the unmodified client; do not embed secrets in it or bypass authentication. | **S5a result:** a remote mTLS gateway's service route requires a TLS client certificate, which the unmodified client cannot present. The provider fails with `ServiceAccessError`. Private-CA trust works through `SSL_CERT_FILE` with verification on. OIDC/edge gateways remain unverified. |
| WebSocket keepalive | Preserve OpenEnv's client transport behavior. S5 proved two episodes, four echo steps, state transitions, and ping/pong on one local connection. That evidence covers short active sessions. | P10/I2 must validate the unmodified local client. **S5a:** the remote HTTPS/WSS route passed two episodes, four echo steps, and ping/pong when the client presented the gateway certificate. Long idle and reconnect behavior remain unverified. |
| Initial policy | Load and strictly convert an explicit policy before create; embed it in the same request as workload and service exposure. Never create first and install static policy afterward or replace an invalid explicit policy with a default. S3a/S4/S5 supplied initial policy; P2/T6 verify strict conversion offline. | SEC1 owns general loading/normalization; SEC4 must prove invalid policy prevents execution. SEC5/SEC6 own denial tests. |

The normative requirements are in [SPEC.md](../SPEC.md), sections 12.2–14,
18, and 41. See the [SDK contract](openshell-sdk-contract.md) for the exact
create-time service map and generated-model boundary.

## Image startup is a separate prerequisite

[The image investigation](echo-env-image.md) found a usable native VM image
with the upstream canonical command and a runtime-discoverable uvicorn
executable. [S4](lifecycle-spike.md) left `spec.command` empty and established
sandbox readiness, without health or protocol checks. [S5](protocol-spike.md)
supplied the canonical command explicitly before proving health and protocol.
Neither experiment proves automatic OCI entrypoint/CMD handling, working
directory, or image environment preservation.

S6a's [completed comparison](image-startup.md) confirms the missing automatic
startup contract on 0.1.2. **S6b adopts explicit startup:** configure exact argv
with `command`, supply required image environment via `env_vars`, and choose a
command that establishes the directory. Automatic OCI metadata resolution is
outside v0.1. Request preparation and the adapter reject missing/invalid argv
before gateway access and preserve valid argv verbatim. P4 implements lifecycle
wiring; it has no remaining startup API decision. Remote validation remains S5a.

## Evidence boundaries

- [S3a image evidence](echo-env-image.md#verified-outcome-012-2026-09-29)
  records the successful named route, initial image policy, failed baseline
  startup, and cleanup. The fixture uses best-effort Landlock; observed applied
  rules do not establish filesystem-denial acceptance or strict enforcement.
- [S4 lifecycle evidence](lifecycle-spike.md) records atomic unnamed exposure,
  create-time URL capture, readiness, and identity-aware deletion.
- [S5 protocol evidence](protocol-spike.md) records health, repeated protocol
  operations, ping/pong, cleanup, and the local-only gateway inventory. No remote
  endpoint or workspace credentials were available.
- The release-pinned upstream [VM driver reference][vm] describes an
  experimental compute driver and its image preparation. This supports keeping
  driver compatibility explicit; runtime proof still comes from the local
  experiments above.
- The release-pinned upstream [API definition][api] specifies authorization
  for lifecycle RPCs. It does not establish authentication of a deployment's
  routed HTTP/WebSocket service; S5a must test that separately.

S6 can close once these decisions are recorded and downstream dependencies
match them. That does not close M0/M3, S6a, or the security acceptance tasks.
The existing S5a issue already blocks M3; no duplicate remote issue is needed.

[vm]: https://github.com/NVIDIA/OpenShell/blob/v0.1.2/crates/openshell-driver-vm/README.md
[api]: https://github.com/NVIDIA/OpenShell/blob/v0.1.2/proto/openshell.proto
