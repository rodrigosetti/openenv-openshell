# Engineering Specification: `OpenShellProvider` for OpenEnv

**Status:** Draft / Proposed  
**Project:** `openenv-openshell`  
**Primary component:** `OpenShellProvider`  
**Target ecosystems:** Hugging Face OpenEnv + NVIDIA OpenShell  
**Language:** Python  
**Initial license recommendation:** Apache-2.0 or BSD-3-Clause  
**Document version:** 0.1

---

# 1. Summary

`OpenShellProvider` is an OpenEnv `ContainerProvider` implementation that runs an OpenEnv environment server inside an NVIDIA OpenShell sandbox.

The provider allows existing OpenEnv clients to replace the default local Docker runtime:

```python
env = await CodingEnv.from_docker_image(
    "registry.hf.space/openenv-coding-env:latest",
    provider=OpenShellProvider(),
)
```

while preserving the normal OpenEnv API:

```python
await env.reset()
await env.step(...)
await env.state()
```

The provider is responsible for:

1. creating an OpenShell sandbox from an OpenEnv container image;
2. applying an explicit OpenShell security policy;
3. exposing the OpenEnv server port through an OpenShell-managed service;
4. waiting until the OpenEnv `/health` endpoint becomes ready;
5. returning the externally reachable OpenEnv base URL;
6. cleaning up the sandbox when the OpenEnv client closes;
7. exposing metadata useful for auditing and reproducibility.

The initial implementation MUST remain a thin runtime adapter. It MUST NOT require modifications to an OpenEnv environment server.

A second phase SHOULD add trusted verification: executing evaluation logic in a separate OpenShell sandbox that the agent cannot modify.

---

# 2. Motivation

OpenEnv standardizes agentic execution environments around persistent environment servers with `reset`, `step`, `state`, WebSocket communication, and containerized deployment. Its provider abstraction intentionally permits alternative container and cloud runtimes.

NVIDIA OpenShell provides a runtime specifically designed for autonomous agents with sandbox isolation, filesystem policies, network policy, credential mediation, service exposure, and lifecycle management.

These projects currently solve complementary layers:

```text
OpenEnv
────────────────────────────────────────────
Task/environment semantics
reset / step / state
training integration
reward computation
environment packaging

                 ↓

OpenShellProvider
────────────────────────────────────────────
runtime adapter

                 ↓

OpenShell
────────────────────────────────────────────
sandbox lifecycle
process isolation
filesystem isolation
network enforcement
credential mediation
resource controls
audit / observability
```

`OpenShellProvider` bridges the two layers without changing either protocol.

---

# 3. Source Repositories

Primary upstream repositories:

**Hugging Face OpenEnv**  
[github.com/huggingface/OpenEnv](https://github.com/huggingface/OpenEnv?utm_source=chatgpt.com)

**NVIDIA OpenShell**  
[github.com/NVIDIA/OpenShell](https://github.com/NVIDIA/OpenShell?utm_source=chatgpt.com)

Important OpenEnv references:

**OpenEnv provider/environment specification — RFC 002**  
[OpenEnv RFC 002](https://github.com/huggingface/OpenEnv/blob/main/rfcs/002-env-spec.md?utm_source=chatgpt.com)

**Current `ContainerProvider` implementation**  
[OpenEnv providers.py](https://github.com/huggingface/OpenEnv/blob/main/src/openenv/core/containers/runtime/providers.py?utm_source=chatgpt.com)

**Current `EnvClient` implementation**  
[OpenEnv env_client.py](https://github.com/huggingface/OpenEnv/blob/main/src/openenv/core/env_client.py?utm_source=chatgpt.com)

**OpenEnv environment auto-validation RFC #778**  
[OpenEnv issue #778](https://github.com/huggingface/OpenEnv/issues/778?utm_source=chatgpt.com)

**OpenEnv privileged environment-sidecar RFC #1053**  
[OpenEnv issue #1053](https://github.com/huggingface/OpenEnv/issues/1053?utm_source=chatgpt.com)

**External verifier isolation issue #1232**  
[OpenEnv issue #1232](https://github.com/huggingface/OpenEnv/issues/1232?utm_source=chatgpt.com)

Important OpenShell references:

**OpenShell Python SDK documentation**  
[OpenShell Python SDK](https://docs.nvidia.com/openshell/latest/sdk/python?utm_source=chatgpt.com)

**OpenShell policy schema**  
[OpenShell policy schema](https://docs.nvidia.com/openshell/latest/reference/policy-schema?utm_source=chatgpt.com)

**OpenShell sandbox management**  
[OpenShell sandbox management](https://docs.nvidia.com/openshell/latest/sandboxes/manage-sandboxes?utm_source=chatgpt.com)

**OpenShell protobuf/API definition**  
[OpenShell public API proto](https://github.com/NVIDIA/OpenShell/blob/main/proto/openshell.proto?utm_source=chatgpt.com)

---

# 4. Existing OpenEnv Provider Contract

The current OpenEnv `ContainerProvider` abstraction requires three primary operations:

```python
class ContainerProvider(ABC):
    @abstractmethod
    def start_container(
        self,
        image: str,
        port: int | None = None,
        env_vars: dict[str, str] | None = None,
        **kwargs,
    ) -> str:
        ...

    @abstractmethod
    def stop_container(self) -> None:
        ...

    @abstractmethod
    def wait_for_ready(
        self,
        base_url: str,
        timeout_s: float = 30.0,
    ) -> None:
        ...
```

OpenEnv currently performs the equivalent lifecycle:

```text
provider.start_container(image)
             │
             ▼
       returns base_url
             │
             ▼
provider.wait_for_ready(base_url)
             │
             ▼
 EnvClient connects to base_url/ws
             │
             ▼
     reset / step / state
             │
             ▼
 provider.stop_container()
```

`EnvClient.from_docker_image()` already accepts a custom `ContainerProvider`, which means an external provider implementation can initially work without modifying OpenEnv core.

That property is a major design constraint:

> **MVP SHOULD be implementable as an independent Python package.**

---

# 5. Goals

## 5.1 Functional goals

The provider MUST:

- implement the OpenEnv `ContainerProvider` interface;
- create an OpenShell sandbox from the requested OCI image;
- start the OpenEnv server inside that sandbox;
- expose the OpenEnv server using OpenShell's service mechanism;
- support WebSocket traffic required by OpenEnv;
- return a URL that can be consumed directly by `EnvClient`;
- pass environment variables to the environment;
- delete the sandbox during cleanup;
- handle cleanup after partial startup failures;
- support local OpenShell gateways first;
- support remote OpenShell gateways where the returned service URL is usable by the caller.

OpenShell's current service facility is designed to expose long-running loopback services through a gateway-managed URL, including HTTP/WebSocket workloads.

## 5.2 Security goals

The provider MUST make OpenShell policy enforcement part of the normal execution path.

The default posture SHOULD be:

```text
filesystem: minimum required access
network: deny by default
credentials: unavailable unless explicitly attached
process identity: non-root where possible
OpenEnv server: exposed only through OpenShell service routing
```

## 5.3 Ecosystem goals

The implementation SHOULD:

- require no changes to existing OpenEnv environment containers;
- require no custom OpenShell fork;
- use public OpenShell APIs;
- make upstreaming into OpenEnv straightforward;
- remain usable as a standalone package if upstream inclusion is not immediately accepted.

---

# 6. Non-Goals

The MVP will NOT:

- replace the OpenEnv protocol;
- implement a new agent framework;
- implement a new sandbox runtime;
- replace OpenShell's policy engine;
- automatically infer perfect least-privilege policies;
- redesign OpenEnv reward semantics;
- solve distributed RL orchestration;
- implement OpenShell itself as an OpenEnv environment;
- run the agent separately from the environment server unless the particular OpenEnv environment already does so;
- guarantee hostile-verifier isolation in v0.1.

Trusted external verification is a follow-on feature.

---

# 7. Proposed Package

Initial repository:

```text
openenv-openshell/
├── pyproject.toml
├── README.md
├── LICENSE
├── src/
│   └── openenv_openshell/
│       ├── __init__.py
│       ├── provider.py
│       ├── config.py
│       ├── policy.py
│       ├── errors.py
│       ├── metadata.py
│       └── _compat.py
├── tests/
│   ├── unit/
│   └── integration/
├── examples/
│   ├── echo_env.py
│   ├── coding_env.py
│   └── policies/
│       ├── deny-all.yaml
│       └── hf-minimal.yaml
└── docs/
    ├── architecture.md
    ├── security.md
    └── trusted-verification.md
```

Python import surface:

```python
from openenv_openshell import OpenShellProvider
```

---

# 8. High-Level Architecture

```text
┌─────────────────────────────────────────────┐
│                 User / Trainer              │
│                                             │
│ CodingEnv.from_docker_image(...)            │
└───────────────────┬─────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│               OpenEnv EnvClient             │
│                                             │
│ HTTP health checks                          │
│ WebSocket: /ws                              │
└───────────────────┬─────────────────────────┘
                    │
              returned base_url
                    │
                    ▼
┌─────────────────────────────────────────────┐
│            OpenShell Service Route          │
│                                             │
│ gateway-managed HTTP / WebSocket endpoint   │
└───────────────────┬─────────────────────────┘
                    │
              target port 8000
                    │
                    ▼
┌─────────────────────────────────────────────┐
│              OpenShell Sandbox              │
│                                             │
│ ┌─────────────────────────────────────────┐ │
│ │ OpenEnv Environment Container           │ │
│ │                                         │ │
│ │ 127.0.0.1:8000                          │ │
│ │ /health                                 │ │
│ │ /ws                                     │ │
│ └─────────────────────────────────────────┘ │
│                                             │
│ OpenShell enforcement:                      │
│ • filesystem                               │
│ • network                                  │
│ • process                                  │
│ • credentials                              │
└─────────────────────────────────────────────┘
```

The OpenEnv server SHOULD listen on loopback inside the sandbox where possible.

The provider MUST NOT independently publish the container port through Docker.

All external access SHOULD travel through the OpenShell service exposure.

---

# 9. Public API

## 9.1 Minimal API

```python
from openenv_openshell import OpenShellProvider

provider = OpenShellProvider()

env = await EchoEnv.from_docker_image(
    "registry.hf.space/openenv-echo-env:latest",
    provider=provider,
)
```

## 9.2 Configured API

```python
provider = OpenShellProvider(
    workspace="default",
    policy="./openshell-policy.yaml",
    service_port=8000,
    startup_timeout_s=120,
)
```

Usage:

```python
env = await CodingEnv.from_docker_image(
    image,
    provider=provider,
    env_vars={
        "OPENENV_MAX_CONCURRENT_ENVS": "8",
    },
)
```

## 9.3 Recommended constructor

```python
class OpenShellProvider(ContainerProvider):
    def __init__(
        self,
        *,
        workspace: str = "default",
        sandbox_name: str | None = None,
        policy: str | Path | Mapping[str, Any] | None = None,
        service_port: int = 8000,
        service_name: str = "",
        startup_timeout_s: float = 120.0,
        deletion_timeout_s: float = 60.0,
        health_poll_interval_s: float = 0.5,
        health_request_timeout_s: float = 2.0,
        gateway: str | None = None,
        keep_sandbox: bool = False,
        labels: Mapping[str, str] | None = None,
        providers: Sequence[str] | None = None,
        resources: OpenShellResources | None = None,
        client: SandboxClient | None = None,
    ):
        ...
```

Exact OpenShell SDK object names MUST track the installed stable SDK rather than reimplement its generated RPC model.

---

# 10. Internal State

The provider owns exactly one active sandbox, matching the existing OpenEnv `ContainerProvider` assumption.

Recommended state:

```python
@dataclass
class ProviderState:
    sandbox_name: str | None = None
    sandbox_id: str | None = None
    image: str | None = None
    base_url: str | None = None
    created: bool = False
    ready: bool = False
    deleted: bool = False
```

Additional metadata:

```python
@dataclass(frozen=True)
class OpenShellRunMetadata:
    sandbox_name: str
    sandbox_id: str | None
    workspace: str
    image: str
    service_url: str
    policy_digest: str | None
    created_at: datetime
```

The metadata SHOULD eventually be exportable as part of a reproducible agent run.

---

# 11. Lifecycle

## 11.1 State machine

```text
NEW
 │
 │ start_container()
 ▼
CREATING
 │
 │ SandboxClient.create()
 ▼
PROVISIONING
 │
 │ SandboxClient.wait_ready()
 ▼
SANDBOX_READY
 │
 │ obtain service URL
 ▼
SERVICE_AVAILABLE
 │
 │ wait_for_ready()
 ▼
OPENENV_READY
 │
 │
 │ stop_container()
 ▼
DELETING
 │
 │ SandboxClient.delete()
 │ SandboxClient.wait_deleted()
 ▼
DELETED
```

Failure from any intermediate state MUST trigger best-effort cleanup.

---

# 12. `start_container()`

Signature:

```python
def start_container(
    self,
    image: str,
    port: int | None = None,
    env_vars: dict[str, str] | None = None,
    **kwargs: Any,
) -> str:
    ...
```

## 12.1 Behavior

`start_container()` MUST:

1. reject startup if the provider already owns a live sandbox;
2. determine the target OpenEnv port;
3. resolve the effective OpenShell policy;
4. generate a unique sandbox name if one was not supplied;
5. create the sandbox;
6. configure the OpenEnv server as the sandbox workload;
7. register a service exposure for the OpenEnv server;
8. wait for OpenShell's sandbox `Ready` state;
9. read the service URL returned by OpenShell;
10. store lifecycle metadata;
11. return the service URL.

OpenShell 0.1.2's official Python wheel supports creating, waiting for
readiness, executing commands, deleting, and identity-aware deletion waiting.
It also supports atomic service exposures and returned service URLs. The
repository pins that wheel by release URL and SHA-256. S1a selects a confined,
contract-tested generated-model dependency for workload and policy inputs;
public lifecycle calls remain the runtime boundary. See
[`docs/openshell-sdk-contract.md`](docs/openshell-sdk-contract.md) for the exact
contract and upgrade constraints.

## 12.2 Port semantics

If OpenEnv calls:

```python
provider.start_container(image, port=9000)
```

the provider MUST interpret `port` as the target OpenEnv environment server
port inside the sandbox. An explicit non-`None` `port` MUST take precedence over
the constructor's `service_port`; otherwise use `service_port` (default 8000).
Both inputs MUST be integers from 1 through 65535, excluding booleans. Invalid
explicit values MUST fail before create, without falling back to the constructor.

For example, `OpenShellProvider(service_port=8000).start_container(image,
port=9000)` requests an OpenShell exposure targeting 9000. This selects routing;
it does not rewrite the image command, its listen port, or its environment.
The image workload must already listen on the selected port.

No host port is selected or independently published; OpenShell owns routing.
This is the S6 API decision, not evidence that the spike tested port overrides.

## 12.3 Workload command

Preferred MVP behavior:

- respect the image's normal entrypoint/CMD;
- expose the configured OpenEnv port;
- do not invent a server startup command unless explicitly configured.

S3a/S5 verified a native arm64 EchoEnv image on the local VM driver with its
canonical command supplied explicitly. S4's empty command proved sandbox
readiness only. Automatic OCI entrypoint/CMD execution, working-directory and
image-environment preservation MUST NOT be claimed from those results. **S6a**
tracks validation and selection of a supported startup strategy before P4
implements provider startup. Do not silently start a shell, hardcode an EchoEnv
command, or add a local Docker dependency for remote callers.

Image compatibility is compute-driver-specific. The tested VM image includes
`iproute2`, `nftables`, a discoverable uvicorn executable, and a policy granting
read-only `/app` access. The inspected upstream amd64-only image is not approved
for the native Apple Silicon VM lane. The checked-in `sha256:` image ID is a
local Docker configuration ID, not a pullable registry manifest digest. Remote
validation requires a pullable immutable image compatible with that gateway's
driver (**S5a**). These are tested-image constraints, not universal requirements
for every OpenShell driver. See [image evidence](docs/echo-env-image.md).

Optional future constructor field:

```python
command: Sequence[str] | None
```

This may be useful for images that contain OpenEnv but do not declare the server process as their normal workload.

---

# 13. Service Exposure

The service exposure is central to the design.

OpenShell already supports:

```text
sandbox
   │
   │ target_port=8000
   ▼
service exposure
   │
   ▼
gateway URL
```

The provider MUST request the exposure atomically during sandbox creation.

Conceptual request:

```python
sandbox = client.create(
    workspace=self.workspace,
    name=name,
    spec=workload_spec,
    service_exposures=[
        ServiceExposure(
            service="",
            target_port=port,
        )
    ],
)
```

This is the public 0.1.2 service-exposure contract. The workload `spec` type is
still private. S1a explicitly permits its generated types only inside the
private adapter, backed by the pinned-wheel offline contracts. Generated types
MUST NOT enter the provider public API.

The unnamed service MUST be used by default:

```text
service = ""
```

An explicitly configured `service_name` MUST select the named exposure:

```text
service = "openenv"
```

OpenShell uses gateway-managed URLs for these services, including local `openshell.localhost` addresses for loopback gateways and HTTPS URLs for appropriately configured remote gateways.

The provider MUST select the create response's `service_urls[service_name]`
using the exact configured key, including `""`, and persist it before readiness
polling. Later `get()`/`wait_ready()` responses do not retain these URLs in the
pinned SDK. A missing or unusable selected route MUST fail startup and trigger
cleanup; do not select another service or synthesize a URL. S3a verified a named
local route; S4/S5 verified the unnamed local route.

## 13.1 Service authentication

Gateway SDK authentication and access to a routed environment are separate
contracts. The local S5 route accepted HTTP/WebSocket requests without additional
application credentials; gateway lifecycle calls used mTLS. That local result
MUST NOT imply that a remote service is anonymous or accepts the SDK credentials.

The returned URL must be directly usable by an unmodified OpenEnv client for
both HTTP and WebSocket traffic. The provider MUST NOT embed credentials in the
URL, copy gateway credentials into the workload, disable TLS verification, or
silently bypass a service authentication requirement. Remote service
credentials, certificate trust, and unmodified-client compatibility remain
unverified and are tracked by **S5a**, a prerequisite of the M3 release gate.
Deployments requiring unsupported service authentication must fail explicitly;
remote support MUST NOT be advertised until validated.

---

# 14. WebSocket Support

OpenEnv's `EnvClient` derives its persistent session endpoint as:

```text
<base_url>/ws
```

Therefore the OpenShell service route MUST preserve WebSocket upgrades.

The acceptance test MUST explicitly verify:

```text
HTTP GET /health     → succeeds
WebSocket /ws        → connects
reset()              → succeeds
step()               → succeeds
state()              → succeeds
```

A provider MUST NOT be considered functional based only on the HTTP health endpoint.

S5 verified two reset episodes, four echo steps, state transitions, and ping/pong
after each step over one local routed connection on SDK/gateway 0.1.2. This
establishes short-session liveness. Long idle sessions, reconnect behavior, and
remote keepalive remain unverified. The provider MUST preserve the OpenEnv
client's transport and keepalive behavior and MUST NOT add a substitute protocol
or infer arbitrary idle-duration guarantees. P10/I2 must exercise the unmodified
client over the local route; S5a must repeat protocol and ping/pong checks remotely.
See [protocol evidence](docs/protocol-spike.md).

---

# 15. `wait_for_ready()`

```python
def wait_for_ready(
    self,
    base_url: str,
    timeout_s: float = 30.0,
) -> None:
    ...
```

Readiness has two distinct levels:

```text
OpenShell readiness
        │
        └── sandbox exists and workload started

OpenEnv readiness
        │
        └── environment server responds to /health
```

`start_container()` SHOULD wait for OpenShell readiness.

`wait_for_ready()` MUST wait for **OpenEnv readiness**.

Recommended algorithm:

```python
deadline = monotonic() + timeout_s

while monotonic() < deadline:
    try:
        response = requests.get(
            f"{base_url}/health",
            timeout=2,
        )

        if response.status_code == 200:
            return
    except RequestException:
        pass

    sleep(0.5)

raise OpenEnvReadinessTimeout(...)
```

Future implementation MAY additionally perform a WebSocket handshake before declaring readiness.

Polling controls are constructor settings: `health_poll_interval_s=0.5` and
`health_request_timeout_s=2.0`. They and the per-call `timeout_s` MUST be positive
and finite. Requests and sleeps use at most the remaining monotonic budget;
only HTTP 200 received before the deadline marks `state.ready`. Redirects are
not followed, and health response bodies need not be consumed. HTTP transport
timeouts apply per operation rather than imposing a hard total wall-clock
limit on an in-flight request or DNS lookup. After the deadline no new request
is started and any late success is rejected. Base URLs MUST be absolute HTTP(S)
URLs without embedded credentials, query parameters, or fragments; existing
service path prefixes are preserved. Readiness timeout messages MUST exclude
the URL and raw transport exception text.

---

# 16. `stop_container()`

```python
def stop_container(self) -> None:
    ...
```

The method MUST be idempotent.

Algorithm:

```text
if no active sandbox:
    return

if keep_sandbox:
    clear local ownership only
    return

delete sandbox
wait for deletion
clear state
```

Deletion SHOULD use the selected OpenShell SDK. The target identity-safe
contract is:

```python
deletion = client.delete(
    sandbox_name,
    workspace=workspace,
)

client.wait_deleted(
    sandbox_name,
    workspace=workspace,
    expected_sandbox_id=deletion.sandbox_id,
)
```

The pinned official 0.1.2 wheel implements this contract. The previous
0.0.116 Python SDK instead returns `bool` from `delete()` and does not accept
`expected_sandbox_id` in `wait_deleted()`. The adapter MUST reject that older
contract before creating a sandbox.

---

# 17. Cleanup Guarantees

This is particularly important because OpenEnv calls provider cleanup automatically after startup or connection failures.

The provider MUST correctly handle:

```text
sandbox create succeeds
service creation fails
          ↓
sandbox must be deleted
```

and:

```text
sandbox becomes ready
OpenEnv server never becomes healthy
          ↓
OpenEnv invokes provider.stop_container()
          ↓
sandbox must be deleted
```

`stop_container()` MUST tolerate:

- sandbox already deleted;
- gateway connection failure;
- deletion request succeeding but wait timing out;
- duplicate calls;
- partially initialized provider state.

---

# 18. Policy Configuration

OpenShell policies currently have top-level controls for filesystem, Landlock behavior, process identity, network policies, and network middleware.

The provider SHOULD accept either:

```python
policy="./policy.yaml"
```

or:

```python
policy={
    "version": 1,
    ...
}
```

An explicit policy MUST be loaded, normalized, and strictly converted before
create, then embedded in `SandboxSpec.policy` in the same create request as the
workload and service. Static controls MUST be established before workload
execution; creating first and applying policy afterward is not an acceptable
startup sequence. Invalid policy MUST prevent the create call. S3a/S4/S5 use an
embedded initial policy; the offline adapter contracts verify strict conversion.
SEC1 implements general policy loading. SEC4 verifies on SDK/gateway 0.1.2 that
invalid explicit inputs send no create RPC and leave no sandbox, while a valid
initial policy permits the routed EchoEnv control to execute and be deleted.
The production adapter validates explicit inputs before gateway access and
embeds policy atomically. This adapter test supplies the validated image command
at the SDK boundary; provider startup wiring remains P4. See the
[SEC4 runtime evidence](tests/integration/README.md). These results do not close
filesystem/network denial acceptance (SEC5/SEC6).

The provider MUST NOT silently broaden permissions when a supplied policy fails.

Invalid policy:

```text
fail startup
```

not:

```text
fall back to permissive policy
```

---

# 19. Default Security Policy

The project's default policy SHOULD prioritize compatibility while remaining meaningfully restrictive.

OpenShell itself uses a restrictive baseline when no explicit policy applies, with outbound networking denied unless declared.

For `OpenShellProvider`, two modes are recommended.

## 19.1 `policy_mode="strict"`

Recommended eventual default:

```yaml
version: 1

filesystem_policy:
  read_only:
    - /usr
    - /lib
    - /etc
    - /proc
  read_write:
    - /workspace
    - /tmp

network_policies: {}
```

Exact schema MUST be generated from the current OpenShell schema.

## 19.2 `policy_mode="image"`

Allow OpenShell's policy resolution behavior to select:

```text
explicit sandbox policy
        ↓
image policy
        ↓
restrictive OpenShell default
```

This mode is useful for compatibility testing.

---

# 20. Network Access

The provider SHOULD distinguish two categories of traffic:

### Control-plane traffic

```text
trainer
   ↓
OpenShell service
   ↓
OpenEnv server
```

This is required for OpenEnv itself.

### Agent/environment egress

```text
sandbox process
   ↓
GitHub
Hugging Face
model provider
package registry
etc.
```

This SHOULD remain deny-by-default unless explicitly declared by the policy.

The fact that an environment server is externally reachable MUST NOT imply unrestricted outbound network access from that sandbox.

---

# 21. Credentials

`env_vars` and credentials require different handling.

Ordinary non-secret environment configuration can remain:

```python
env_vars={
    "MAX_CONCURRENT_ENVS": "8",
}
```

Secrets SHOULD eventually use OpenShell providers rather than raw environment variables.

Example future API:

```python
provider = OpenShellProvider(
    providers=[
        "huggingface",
        "github-readonly",
    ],
)
```

Then:

```text
real credential
       │
       ▼
OpenShell provider
       │
       ▼
approved endpoint only
       │
       ▼
sandbox request
```

The goal is that agents do not need unrestricted access to long-lived credential strings.

MVP MAY support `env_vars` exactly as OpenEnv expects, but the documentation SHOULD state that users should prefer OpenShell provider-backed credentials for secrets.

---

# 22. Resource Configuration

Proposed model:

```python
@dataclass(frozen=True)
class OpenShellResources:
    cpu: float | None = None
    memory: str | None = None
    gpu_count: int | None = None
```

Usage:

```python
OpenShellProvider(
    resources=OpenShellResources(
        cpu=4,
        memory="16Gi",
        gpu_count=1,
    )
)
```

These values SHOULD map directly to OpenShell resource configuration.

No additional scheduler abstraction should be invented.

---

# 23. Sandbox Naming

Default name:

```text
openenv-<environment>-<random>
```

Example:

```text
openenv-coding-a7f213
```

Names SHOULD be:

- human-readable;
- unique enough for parallel tests;
- short enough for backend restrictions.

Recommended implementation:

```python
prefix = sanitize(image_basename)
suffix = secrets.token_hex(3)

name = f"openenv-{prefix}-{suffix}"
```

---

# 24. Labels

The provider SHOULD attach metadata labels when supported:

```text
managed-by=openenv-openshell
openenv.provider=openshell
openenv.image=<digest-or-name>
```

Additional optional labels:

```text
openenv.environment=<environment>
openenv.run_id=<run-id>
openenv.task_id=<task-id>
```

Labels MUST NOT contain:

- credentials;
- prompts;
- private task contents;
- user data.

---

# 25. Image Identity

Reproducible runs SHOULD prefer immutable OCI digests:

```text
registry.example/env@sha256:...
```

over:

```text
registry.example/env:latest
```

The provider SHOULD record the image reference it received.

If OpenShell exposes the resolved image digest, the provider SHOULD include it in run metadata.

Future validation MAY warn on mutable tags in reproducibility mode.

---

# 26. Error Model

Custom errors:

```python
class OpenShellProviderError(RuntimeError):
    pass


class OpenShellConnectionError(OpenShellProviderError):
    pass


class SandboxCreationError(OpenShellProviderError):
    pass


class SandboxReadinessError(OpenShellProviderError):
    pass


class OpenEnvReadinessTimeout(OpenShellProviderError):
    pass


class SandboxDeletionError(OpenShellProviderError):
    pass


class PolicyConfigurationError(OpenShellProviderError):
    pass
```

Errors SHOULD include:

```text
workspace
sandbox name
lifecycle phase
underlying exception
```

Errors MUST NOT include:

```text
credentials
bearer tokens
raw secret environment values
```

---

# 27. Logging

Use standard Python `logging`.

Namespace:

```text
openenv_openshell
```

Recommended events:

```text
sandbox.create.started
sandbox.create.completed
sandbox.ready
service.exposed
openenv.health.ready
sandbox.delete.started
sandbox.delete.completed
provider.cleanup.failed
```

Example:

```text
INFO openenv_openshell sandbox.ready
     sandbox=openenv-coding-a7f213
     workspace=default
```

Structured logging support MAY be added later.

---

# 28. Observability and Run Metadata

A valuable extension is making sandbox enforcement information part of an OpenEnv run record.

Potential metadata:

```json
{
  "runtime": "openshell",
  "workspace": "default",
  "sandbox_id": "...",
  "sandbox_name": "openenv-coding-a7f213",
  "image": "...@sha256:...",
  "policy_sha256": "...",
  "service_url": "...",
  "openenv_provider_version": "0.1.0",
  "openshell_version": "0.1.2"
}
```

This metadata provides provenance without exposing private contents.

Phase 2 MAY incorporate OpenShell audit/security events into a published trajectory artifact.

---

# 29. Trusted Verification Extension

This is explicitly **not required for the first provider release**, but should influence the architecture.

OpenEnv is actively discussing verifier integrity and environment security. Its auto-validation work calls out filesystem containment, network egress, ground-truth containment, reward integrity, replayability, and verifier portability as important environment properties.

The trusted-verification extension would implement:

```text
┌──────────────────┐
│ Agent Sandbox A  │
│                  │
│ task execution   │
│ mutable workspace│
└────────┬─────────┘
         │
         │ approved artifacts only
         ▼
┌──────────────────┐
│ Verifier Sandbox │
│ B                │
│                  │
│ clean image      │
│ trusted verifier │
│ no agent process │
└────────┬─────────┘
         │
         ▼
       reward
```

Invariant:

> Agent-controlled state MUST NOT be able to alter verifier startup, verifier execution, or verifier result collection.

The current OpenEnv discussion of verifier isolation is especially relevant:  
[OpenEnv #1232 — Verify sandbox environments outside the agent's sandbox](https://github.com/huggingface/OpenEnv/issues/1232?utm_source=chatgpt.com)

Proposed future API:

```python
result = provider.verify(
    artifact_paths=["/workspace/submission"],
    verifier_image="...",
    verifier_command=["pytest", "-q"],
)
```

This API SHOULD live outside the base `ContainerProvider` interface until an upstream abstraction exists.

---

# 30. Policy Generation Extension

Another future feature is deriving an OpenShell policy skeleton from environment metadata.

Concept:

```text
OpenEnv manifest
OpenEnv declared tools
declared external APIs
declared artifact paths
        │
        ▼
Policy compiler
        │
        ▼
OpenShell policy
```

Potential API:

```python
from openenv_openshell import generate_policy

policy = generate_policy(
    environment="openenv/coding_env",
)
```

The output SHOULD be reviewable YAML, not an opaque generated binary configuration.

The generator MUST treat generated rules as a proposal, not as proof of least privilege.

---

# 31. Compatibility

## 31.1 Python

Initial support:

```text
Python >= 3.11
```

This matches the current OpenShell Python SDK requirement.

## 31.2 OpenEnv

The package SHOULD specify a tested range rather than an unconstrained dependency:

```toml
openenv = ">=X,<Y"
```

Because OpenEnv explicitly describes itself as experimental and subject to API changes, provider compatibility needs continuous testing.

## 31.3 OpenShell

The selected compatibility target is exactly SDK/gateway `0.1.2`. The SDK
dependency is the official GitHub wheel pinned by URL and SHA-256 in
`pyproject.toml` and `uv.lock`; it replaces the incompatible PyPI `0.0.116`
baseline. S1a permits generated workload/policy models only inside the private
adapter with offline contract tests. Do not widen the SDK range until its
model and lifecycle contracts are reviewed and runtime compatibility is tested.

The OpenShell SDK and gateway SHOULD be from the same release family, consistent with NVIDIA's recommendation.

---

# 32. Unit Testing

Use a fake `SandboxClient`.

Coverage MUST include:

### Successful lifecycle

```text
create
wait_ready
return service URL
health succeeds
delete
wait_deleted
```

### Partial startup failures

```text
create fails
wait_ready fails
service URL missing
health never succeeds
```

### Cleanup

```text
stop before start
stop twice
sandbox already absent
delete fails
wait_deleted times out
```

### Configuration

```text
policy path
policy object
port override
workspace override
sandbox name override
environment variables
resource configuration
keep_sandbox
```

Target:

```text
>90% coverage for provider lifecycle code
```

---

# 33. Integration Testing

CI jobs requiring a real OpenShell runtime SHOULD be separated from pure unit tests.

Minimum E2E test:

```text
1. start local OpenShell gateway
2. build or obtain EchoEnv image
3. instantiate OpenShellProvider
4. EchoEnv.from_docker_image(...)
5. reset()
6. step("hello")
7. assert echo == "hello"
8. close client
9. assert sandbox deleted
```

Second E2E:

```text
attempt network egress forbidden by policy
        ↓
request denied
        ↓
OpenEnv session remains functional
```

Third E2E:

```text
agent attempts forbidden filesystem read
        ↓
denied
        ↓
allowed workspace operations continue
```

Fourth E2E:

```text
WebSocket survives multiple reset/step operations
```

---

# 34. Security Tests

Security tests SHOULD be first-class rather than demos.

Examples:

### Filesystem

Attempt:

```text
cat ~/.ssh/id_rsa
cat /host/etc/shadow
```

Expected:

```text
denied
```

### Network

Attempt:

```text
HTTPS request to undeclared domain
```

Expected:

```text
denied
```

### Allowed network

Policy permits:

```text
GET huggingface.co
```

Expected:

```text
allowed
```

while undeclared writes remain denied when the policy supports method/path-level restriction.

### Credential exposure

Agent process SHOULD NOT be able to trivially print provider-managed credential material.

---

# 35. Reference Demo

The repository SHOULD ship one polished demo rather than many shallow examples.

Suggested demo:

## “OpenEnv Coding Agent under OpenShell Policy”

Flow:

```text
Coding task
    │
    ▼
OpenEnv Coding Environment
    │
    ▼
OpenShell sandbox
    │
    ├── allowed: /workspace
    ├── allowed: package install endpoint
    ├── allowed: model inference endpoint
    │
    ├── denied: ~/.ssh
    ├── denied: arbitrary internet
    └── denied: host filesystem
```

Demo script:

```bash
python examples/coding_env.py
```

Output SHOULD show:

```text
✓ OpenShell sandbox created
✓ OpenEnv server healthy
✓ WebSocket connected
✓ task executed
✓ approved filesystem access succeeded
✓ forbidden filesystem access denied
✓ forbidden network request denied
✓ sandbox deleted
```

---

# 36. User Experience

Ideal user workflow:

```bash
pip install openenv-openshell
```

then:

```python
from openenv_openshell import OpenShellProvider
from echo_env import EchoEnv

provider = OpenShellProvider(
    policy="policy.yaml",
)

env = EchoEnv.from_docker_image(
    "registry.hf.space/openenv-echo-env:latest",
    provider=provider,
).sync()

with env:
    result = env.reset()
```

No OpenShell-specific lifecycle logic should be required in the user's training loop.

---

# 37. CLI

A dedicated CLI is NOT required for v0.1.

Possible future helper:

```bash
openenv-openshell doctor
```

Output:

```text
OpenEnv             0.x       ✓
OpenShell SDK       0.1.2     ✓
Gateway             reachable ✓
Workspace default   accessible ✓
Service routing                ✓
WebSocket routing              ✓
```

This would simplify issue reports considerably.

---

# 38. MVP Milestones

## Milestone 0 — Spike

Prove:

```text
OpenEnv EchoEnv container
        ↓
OpenShell sandbox
        ↓
OpenShell service exposure
        ↓
HTTP /health
        ↓
WebSocket /ws
```

Deliverable:

```text
single Python script
```

Success criteria:

```text
reset + step succeed
```

---

## Milestone 1 — Provider

Implement:

```text
OpenShellProvider
start_container
wait_for_ready
stop_container
configuration
cleanup
unit tests
```

Deliverable:

```text
pip-installable repository
```

---

## Milestone 2 — Policy

Add:

```text
explicit policy loading
strict example policy
filesystem denial tests
network denial tests
policy digest metadata
```

---

## Milestone 3 — Upstream-quality integration

Add:

```text
documentation
CI
type checking
linting
OpenEnv compatibility tests
OpenShell compatibility tests
EchoEnv E2E
```

Open an OpenEnv issue/RFC discussion before proposing large upstream changes, since OpenEnv asks contributors to coordinate significant API work publicly.

---

## Milestone 4 — Trusted Verification

Prototype:

```text
agent sandbox
    ↓ artifacts
verifier sandbox
    ↓
reward
```

Connect implementation discussion to OpenEnv #1232 and related security/RFC work.

---

## Milestone 5 — Open Agent Run

Publish:

```text
model revision
environment revision
image digest
OpenShell version
OpenShell policy digest
trajectory
sandbox audit data
verification result
reward
```

as a reproducible Hugging Face dataset/artifact.

---

# 39. MVP Acceptance Criteria

The project is ready for a public v0.1 release when all of the following hold:

- [ ] `OpenShellProvider` subclasses OpenEnv `ContainerProvider`.
- [ ] Existing OpenEnv clients require no source modifications.
- [ ] `from_docker_image(..., provider=OpenShellProvider())` works.
- [ ] The environment container runs inside OpenShell.
- [ ] The environment is reachable only through an OpenShell-managed service.
- [ ] HTTP `/health` succeeds.
- [ ] WebSocket `/ws` succeeds.
- [ ] `reset()` succeeds.
- [ ] `step()` succeeds.
- [ ] `state()` succeeds.
- [ ] Closing the client deletes the sandbox.
- [ ] Startup failures do not leak sandboxes.
- [ ] `stop_container()` is idempotent.
- [ ] Explicit OpenShell policies can be supplied.
- [ ] Denied network traffic is demonstrated.
- [ ] Denied filesystem access is demonstrated.
- [ ] Unit tests run without an OpenShell installation.
- [ ] Real OpenShell E2E tests exist.
- [ ] README contains a copy-paste quickstart.
- [ ] A public demo uses a real Hugging Face OpenEnv environment.

---

# 40. Important Design Decisions

## Decision 1: external package first

Build:

```text
openenv-openshell
```

before modifying:

```text
huggingface/OpenEnv
```

Reason:

```text
faster iteration
no upstream approval needed
real implementation before RFC debate
clean demonstration of abstraction quality
```

After stabilization, upstreaming could mean either:

```text
A. OpenEnv officially documents the external provider

or

B. OpenShellProvider moves into OpenEnv core
```

---

## Decision 2: OpenShell service routing, not host Docker ports

Use:

```text
OpenShell service exposure
```

rather than:

```text
docker -p
```

Reason:

- portable across OpenShell backends;
- respects the gateway abstraction;
- supports local and remote deployment;
- does not bypass the runtime;
- aligns with the public OpenShell API.

---

## Decision 3: no hidden permissive fallback

If policy setup fails:

```text
STARTUP FAILS
```

rather than:

```text
run unrestricted
```

Security failures must be explicit.

---

## Decision 4: trusted verification remains separate initially

Do not overload the base provider API with verifier semantics before OpenEnv has an upstream contract for it.

Implement the runtime bridge first.

Use a second abstraction later:

```python
OpenShellVerifier
```

or:

```python
TrustedVerificationRunner
```

---

# 41. Spike Decisions and Open Questions

S6 records the decisions and limits in [spike-decisions.md](docs/spike-decisions.md).
Questions 3 and 5 are resolved as requirements in sections 12.2 and 18. Questions
1, 4, and 6 have local evidence and explicit follow-up scope below; they are not
unqualified compatibility claims. The remaining questions still apply before v0.1:

1. **Partially answered (S5):** local short-session ping/pong and repeated
   reset/step/state succeed. Remote keepalive remains S5a; unmodified-client
   validation remains P10/I2. Long idle/reconnect behavior is unverified.

2. What is the exact Python SDK API for specifying image, command, environment variables, resource requirements, policy, and `service_exposures` in the currently released OpenShell version?

3. **Resolved (S6):** explicit non-`None` `port` overrides `service_port` and
   denotes the sandbox target port; it does not alter workload configuration.
   See section 12.2.

4. **Partially answered (S3a/S6):** the native VM lane requires a compatible
   architecture, image utilities, executable lookup, and policy paths. The
   pinned arm64 test image is validated; arbitrary images/drivers are not.
   Automatic entrypoint/CMD handling remains S6a; remote image validation S5a.
   See section 12.3.

5. **Resolved (S6):** embed the validated explicit policy in the initial
   `SandboxClient.create()` request. Policy loading/strict conversion precedes
   create; SEC4 verifies invalid explicit input prevents create and workload
   execution on the local runtime through the production adapter.
   See section 18.

6. **Open (S5a):** local services required no extra application credentials,
   independently of gateway mTLS. Remote service authentication is unverified;
   validate it with an unmodified OpenEnv client before claiming support.
   See section 13.1.

7. Does `EnvClient` require any change for authenticated remote service URLs, or can OpenShell provide a directly usable endpoint?

8. Should provider-owned startup eventually be supported:

```python
provider = OpenShellProvider(image=image)
env = EchoEnv(provider=provider)
```

in addition to OpenEnv's existing:

```python
EchoEnv.from_docker_image(image, provider=provider)
```

9. Which OpenEnv environment is best for the canonical integration test after EchoEnv—`coding_env`, `opencode_env`, or a smaller purpose-built security environment?

10. Should trusted verification become part of OpenEnv's provider abstraction or remain a higher-level evaluation primitive?

---

# 42. Proposed Upstream Strategy

The recommended contribution sequence is:

```text
1. Build lifecycle spike
       ↓
2. Publish external repository
       ↓
3. Demonstrate EchoEnv end-to-end
       ↓
4. Open OpenEnv design issue
       ↓
5. Open OpenShell discussion
       ↓
6. Add policy/security demo
       ↓
7. Seek maintainer feedback
       ↓
8. Upstream minimal changes only where needed
```

The first OpenEnv discussion should focus narrowly on:

> **OpenShell as a `ContainerProvider` backend for policy-isolated OpenEnv server execution.**

Do not initially pitch:

```text
new RL framework
new environment protocol
new security standard
new verification API
```

Those can follow from a working integration.

---

# 43. Definition of Success

Technical success:

```python
env = CodingEnv.from_docker_image(
    IMAGE,
    provider=OpenShellProvider(
        policy="policy.yaml",
    ),
).sync()

with env:
    result = env.reset()
```

works exactly as it does with local Docker, except the environment now executes under OpenShell enforcement.

Strategic success is stronger:

```text
OpenEnv maintainers:
"This is a useful provider."

OpenShell maintainers:
"This is a good use of the public runtime APIs."

Users:
"I can run OpenEnv workloads under OpenShell without changing my environment."
```

The project then becomes credible infrastructure at the boundary between open agent training and secure agent execution rather than merely an integration demo.
