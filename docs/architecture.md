# Provider architecture

`OpenShellProvider` implements OpenEnv's synchronous `ContainerProvider`
operations for one active sandbox. OpenEnv owns the environment protocol and
client session; OpenShell owns workload isolation and service routing. The
package translates between those public contracts without modifying the
environment server. [SPEC.md](https://github.com/rodrigosetti/openenv-openshell/blob/main/SPEC.md) defines requirements; this guide
describes the current implementation and its evidence boundaries.

## Boundaries and traffic

```text
OpenEnv client / trainer
  ├── provider lifecycle → private adapter → OpenShell SDK → gateway
  └── HTTP /health and WebSocket /ws → OpenShell service route → server
                                                               │
                                              policy-controlled egress
                                                               ↓
                                                  declared external endpoints
```

Lifecycle calls use the registered gateway and its SDK authentication. HTTP and
WebSocket application traffic use the returned service URL. These are separate
connections: gateway mTLS does not supply application authentication. Neither
service ingress nor successful health checks grant sandbox outbound access.
The provider never publishes a Docker host port or substitutes a direct
container address for the managed route.

The public configuration uses Python types. `config.py` validates settings,
`policy.py` loads explicit policies, `provider.py` coordinates lifecycle and
health, and `metadata.py` holds state/provenance. `_compat.py` confines the
OpenEnv import contract. `_adapter.py` defines SDK-independent request/result
types and a small typed lifecycle protocol; `_sdk.py` confines the pinned SDK's
generated workload/policy models and public lifecycle calls. Generated types
are not part of the public provider API. Typed fakes and pinned-wheel offline
contracts test this boundary without a gateway.

OpenEnv is pinned to 0.6.0 and OpenShell SDK/gateway to 0.1.2. The adapter rejects
an incompatible SDK or gateway rather than trying an older deletion contract.
See [SDK contract](openshell-sdk-contract.md),
[OpenEnv compatibility](openenv-compatibility.md), and
[compatibility matrix](compatibility-matrix.md) before changing versions.

## Startup and readiness

1. Construction validates configuration and copies mutable inputs without
   connecting to a gateway. `command=None` permits configuration-only health
   checks; a sandbox start requires explicit nonempty argv.
2. `start_container(image, port=None, env_vars=None)` rejects a second start
   while a sandbox or cleanup client remains active. It loads and strictly
   normalizes an explicit policy and validates image, command, environment,
   port, and unsupported keyword arguments before gateway access.
3. It chooses the caller's sandbox name or generates
   `openenv-<sanitized-image-basename>-<random>`, then connects through the
   registered gateway (`gateway=None` selects the SDK's active registration).
   Workspace selects the sandbox namespace; it is not a filesystem mount.
4. The adapter submits image, exact command argv, explicit environment, policy,
   provider instance names, resource requests, labels, and one service exposure
   in the initial create request. Policy is not applied after execution starts.
5. The provider selects the exact `service_urls[service_name]` from the create
   response, validates it, and saves it before `wait_ready`. Later SDK responses
   do not preserve create-time routes. Missing or invalid routes fail startup;
   there is no alternate-service or synthesized-URL fallback.
6. It waits for OpenShell readiness using `startup_timeout_s` (default 120)
   and rejects a different returned sandbox ID. It then returns the saved URL.
   This establishes sandbox readiness, not OpenEnv health.
7. OpenEnv calls `wait_for_ready(base_url, timeout_s=30)` and then uses its own
   `/ws` transport for reset, step, and state. The provider does not implement
   that protocol or change the client's keepalive behavior.

The constructor's `service_port` defaults to 8000. An explicit non-`None`
`start_container` port takes precedence; both must be integers 1–65535,
excluding booleans. `service_name=""` selects the default unnamed exposure;
an explicit name selects only that key. Port configuration selects the sandbox
target for routing, leaving argv and workload listen configuration to the caller.

The command reaches the initial workload unchanged. No shell, second exec,
OCI metadata lookup, image ENV merge, or portable workdir option is added.
Supply required environment explicitly and use an image launcher or an
explicitly selected shell to establish a directory when needed. Image
architecture, utilities, users, and policy paths must fit the compute driver.
The validated local arm64 image ID is not a pullable registry manifest digest.
See [startup contract and evidence](image-startup.md) and
[image constraints](echo-env-image.md).

Health polling preserves a service path prefix and appends `/health`. It accepts
only HTTP 200 before a monotonic deadline, does not follow redirects, and does
not buffer response bodies. Poll interval and request timeout default to 0.5
and 2 seconds; requests and sleeps are bounded by the remaining budget.
HTTPX timeouts apply per operation, so an in-flight request or DNS lookup may
outlast the budget; late success is rejected and no new request begins after
the deadline. HTTP readiness alone proves neither WebSocket operation nor
policy enforcement.

## Failure and cleanup

| Failure point | Public result and cleanup behavior |
| --- | --- |
| Configuration/request validation | `ValueError`/`TypeError`, or `PolicyConfigurationError` for explicit policy failures; no sandbox create |
| SDK/gateway connection or compatibility | Sanitized `OpenShellConnectionError`; no workload create |
| Create or service selection | Sanitized `SandboxCreationError`; startup attempts public cleanup |
| Sandbox readiness or identity mismatch | Sanitized `SandboxReadinessError`; startup attempts public cleanup |
| OpenEnv health deadline | `OpenEnvReadinessTimeout`; OpenEnv's startup path invokes cleanup, while direct provider callers must invoke it |
| Delete, deletion wait, or client close | Sanitized `SandboxDeletionError`; retained state permits an explicit retry |

Startup rollback preserves the primary startup error. If cleanup fails, an
exception note tells the caller to retry `stop_container()`. Cleanup normally
requests deletion, waits for the original sandbox ID to disappear, closes the
SDK client, and clears active state. Successful repeat stop/close calls are
harmless. Client-close failure after confirmed deletion retains the deletion
state, so a retry can release the client without deleting again.

**Current cleanup limitation (SEC8a):** recording the selected name before
create can authorize rollback against a pre-existing same-name sandbox.
Deletion is name-based; identity-aware waiting happens after the destructive
call and does not prevent deletion of a replacement. Thus partial-start
cleanup is implemented but ownership safety is unresolved in this baseline.
The active repair is separate from I7. See the
[security review](security-review.md#cleanup-blast-radius); unique names reduce
collision risk but do not establish a safe deletion contract.

`close()` delegates to `stop_container()`. The inherited context manager returns
the provider without starting a workload and closes it on exit, including when
the body raises. Cleanup failures propagate with raw SDK exception chains
suppressed. `keep_sandbox=True` skips deletion on stop, rollback, and context
exit, closes the client, and clears local ownership; the operator then owns
retention and removal. Metadata retains the sandbox identifiers for inspection.

## State, provenance, and logs

`provider.state` describes active ownership, image, URL, and created/ready/deleted
flags. `provider.metadata` is initially `None`; a validated create-time route
produces an immutable run snapshot containing sandbox name/ID, workspace,
requested image, service URL, explicit policy digest, installed package
versions, and UTC creation/health-ready/deletion timestamps. The SDK version
does not establish the gateway version; the requested image is not a resolved
registry digest. Cleanup retains the snapshot, and a new creation attempt
replaces it. Starts rejected before that attempt leave it intact.

The policy digest is SHA-256 over normalized SDK fields encoded as sorted,
compact UTF-8 JSON. Mapping order, YAML formatting, accepted aliases, and enum
spellings normalize away; list order remains significant. It attests to the
submitted explicit configuration, not enforcement or later policy changes.
When policy is omitted the digest is `None`: the provider cannot attest to
OpenShell's resolved image/default policy. `ready_at` records a successful
health check of the owned route; `deleted_at` records confirmed absence even
if closing the client later fails. Retained sandboxes have no deletion time.

Metadata excludes argv, environment values, credentials, and policy contents.
Names, images, labels, and URLs must still be non-secret caller inputs. Fixed
lifecycle events use standard logging under `openenv_openshell`; package logs
and sanitized public errors omit raw SDK exceptions and workload/route data.
See [security and redaction evidence](security.md).

## Support limits and non-goals

Local runtime evidence covers routed health, short WebSocket sessions, and the
unmodified OpenEnv client's async/sync lifecycle. The integration fixtures,
versions, and run instructions are in the [integration guide](https://github.com/rodrigosetti/openenv-openshell/blob/main/tests/integration/README.md).
Long idle sessions, reconnects, remote routes, service authentication, and remote
image compatibility remain unverified (S5a). A remote URL must work directly
with the unmodified client's HTTP and WebSocket traffic, with valid TLS trust.
The provider does not embed credentials in URLs, disable TLS checks, or bypass
authentication. Unsupported requirements must fail explicitly; local evidence
does not establish remote support.

The package has no scheduler, automatic least-privilege policy generator,
image-startup resolver, credential provisioning service, or alternative OpenEnv
protocol. Resource requests map to upstream fields without establishing runtime
enforcement. The local 0.1.2 VM contract excludes sandbox-specific PID capacity
and availability isolation for hostile workloads; see
[process-capacity limits](process-capacity.md). Trusted verification in a
separate sandbox and publishing reproducible agent trajectories are later
milestones. Isolation of the environment server alone does not protect a
verifier or reward computation that shares agent-controlled state.
