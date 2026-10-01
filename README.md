# openenv-openshell

`openenv-openshell` runs Hugging Face [OpenEnv](https://github.com/huggingface/OpenEnv)
environment servers inside NVIDIA [OpenShell](https://github.com/NVIDIA/OpenShell)
sandboxes, under OpenShell filesystem, network, and credential policies. It
implements OpenEnv's `ContainerProvider` interface, so existing OpenEnv clients
and training loops keep working: you swap the provider, not the client.

```python
env = GenericEnvClient.from_docker_image(image, provider=OpenShellProvider(...)).sync()
```

**Pre-alpha.** The provider lifecycle, explicit policies, and cleanup are
implemented and validated on a local OpenShell 0.1.2 gateway with OpenEnv 0.6.0.
It is not yet published to PyPI; install from source. See
[known limitations](#known-limitations) before relying on it.

## Requirements

- Python 3.11+.
- An OpenShell **0.1.2** CLI and gateway with a working compute driver. Follow
  the [local OpenShell setup](docs/local-openshell-testing.md); on Apple Silicon
  this is the native VM driver. `openshell status` must show the gateway
  connected at version 0.1.2.
- The OpenShell 0.1.2 Python SDK (installed below; the `openshell` package on
  PyPI is a different, incompatible release).
- Docker, to build the example images.

## Install

From a checkout (recommended while pre-alpha; includes the SDK and dev tools):

```bash
git clone https://github.com/rodrigosetti/openenv-openshell.git
cd openenv-openshell
uv sync --locked --all-groups
```

Into an existing virtual environment:

```bash
pip install "openenv-openshell @ git+https://github.com/rodrigosetti/openenv-openshell"
pip install 'openshell @ https://github.com/NVIDIA/OpenShell/releases/download/v0.1.2/openshell-0.1.2-py3-none-any.whl#sha256=8c409da4f176d42418d92366fe201f47cceef2c0fa432bfbce2bf938649d59cf'
```

The provider rejects any SDK version other than 0.1.2 before contacting a
gateway. See [SDK installation](docs/releases.md#sdk-and-gateway-prerequisites).

## Quickstart

Run the upstream EchoEnv server in an OpenShell sandbox and talk to it with the
unmodified OpenEnv client. From the repository root, with the gateway running:

```bash
# 1. Build the pinned EchoEnv image (native arm64 for the local VM driver).
docker build -t openenv-openshell-echo:quickstart \
  -f tests/integration/images/echo/Dockerfile tests/integration/images/echo
export OPENENV_OPENSHELL_ECHO_IMAGE_ID="$(docker image inspect --format '{{.Id}}' openenv-openshell-echo:quickstart)"

# 2. Run the quickstart.
uv run python examples/quickstart.py
```

Expected output (the sandbox name is random):

```text
echo: hello from OpenShell
steps: 1
sandbox: oe-quick-d91afc87
deleted: True
```

[`examples/quickstart.py`](examples/quickstart.py) is the whole program:

```python
import os
from secrets import token_hex

from openenv.core.generic_client import GenericEnvClient

from openenv_openshell import OpenShellProvider

provider = OpenShellProvider(
    # The 0.1.2 gateway limits names to 19 characters.
    sandbox_name=f"oe-quick-{token_hex(4)}",
    # Exact server argv; OpenShell 0.1.2 does not run the image CMD for you.
    command=[
        "sh",
        "-c",
        "cd /app/env && uvicorn server.app:app --host 0.0.0.0 --port 8000",
    ],
    service_port=8000,
    policy="examples/policies/image-compatible.yaml",
    labels={"openenv.environment": "echo"},
)
image = os.environ["OPENENV_OPENSHELL_ECHO_IMAGE_ID"]
env = GenericEnvClient.from_docker_image(image, provider=provider).sync()
with env:
    env.reset()
    result = env.step(
        {
            "type": "call_tool",
            "tool_name": "echo_message",
            "arguments": {"message": "hello from OpenShell"},
        }
    )
    print("echo:", result.observation["result"]["data"])
    print("steps:", env.state()["step_count"])
    print("sandbox:", provider.metadata and provider.metadata.sandbox_name)
print("deleted:", provider.state.deleted)
```

What happens: the provider validates the command and policy offline, creates
the sandbox with the policy and service route in one request, waits for
OpenShell and then `/health`, and hands OpenEnv the routed URL. The client
connects over WebSocket. Leaving the `with` block deletes the sandbox and waits
until it is gone; a failed start is rolled back the same way.

To adapt it to your own environment image, change `command`, `service_port`,
`policy`, and any `env_vars` the server needs. OpenShell 0.1.2 does not use
the image's `CMD`, `WORKDIR`, or `ENV`. Read the
[image guide](docs/images.md) and pin the image by digest.

Something wrong? See [troubleshooting](docs/troubleshooting.md).

## Coding-agent demo

The canonical demo runs the upstream OpenEnv coding environment under a strict
policy: it solves a task over the OpenEnv WebSocket, writes to `/workspace`,
reaches `pypi.org`, is denied `~/.ssh`, `/host`, and `example.com`, keeps the
session working, and deletes the sandbox.

```bash
docker build -t openenv-openshell-coding:i8 examples/coding-agent
export OPENENV_OPENSHELL_CODING_IMAGE_ID="$(docker image inspect --format '{{.Id}}' openenv-openshell-coding:i8)"
make demo
```

```text
✓ OpenShell sandbox created (oe-demo-e531c976, policy 5104817a61fe)
✓ OpenEnv server healthy
✓ WebSocket connected
✓ task executed (fizzbuzz via OpenEnv coding_env)
✓ approved filesystem access succeeded (/workspace)
✓ forbidden filesystem access denied (~/.ssh, /host)
✓ approved package index request succeeded (pypi.org)
✓ forbidden network request denied (example.com)
✓ OpenEnv session still healthy after denials
✓ sandbox deleted
```

The gateway needs internet access to `pypi.org` and `example.com`. The
[demo guide](docs/coding-agent-demo.md) explains each check and its limits.

## Documentation

| Guide | Contents |
| --- | --- |
| [Configuration reference](docs/configuration.md) | Every provider option, start arguments, policy, credentials, resources, metadata, errors, logging |
| [Images](docs/images.md) | Preparing images for OpenShell and pinning them immutably |
| [Troubleshooting](docs/troubleshooting.md) | Errors by symptom, diagnostics, cleanup |
| [Policy examples](examples/policies/README.md) | Strict, Hugging Face read-only, and image-compatible policies |
| [Architecture](docs/architecture.md) | Lifecycle, routing, failure recovery, metadata |
| [Security](docs/security.md) | Policy precedence, credentials, enforcement evidence, residual risks |
| [Compatibility matrix](docs/compatibility-matrix.md) | Supported OpenEnv, SDK, and gateway versions |
| [Local OpenShell setup](docs/local-openshell-testing.md) | Installing and checking the gateway and VM driver |

[SPEC.md](SPEC.md) holds the requirements and milestones.

## Known limitations

- Only OpenEnv 0.6.0 and OpenShell SDK/gateway 0.1.2 are supported.
- Validated on the local native arm64 VM driver with locally built images. Their
  image IDs are not pullable registry digests. S5b also validated a digest-pinned
  amd64 EchoEnv image on a remote Docker driver with OIDC; arbitrary images and
  other compute drivers are unverified.
- Generated default sandbox names exceed the 0.1.2 gateway's 19-character
  limit; pass a short `sandbox_name` (tracked as `openenv-openshell-zf3`).
- Remote gateways using the standard mTLS configuration are **not supported**
  for unmodified OpenEnv clients: service routes require a TLS client
  certificate the client cannot present. The provider fails with
  `ServiceAccessError` instead of timing out. S5b validated an OIDC-configured
  remote gateway with the unmodified async/sync client: lifecycle RPCs required
  a bearer token, but service routes were anonymous within the IP-restricted
  network boundary. OIDC gateway authentication does not protect those service
  routes. Edge authentication, HTTP 401/403 service challenges, long idle
  sessions, and reconnects remain unverified. See
  [S5b remote evidence](docs/protocol-spike.md#oidc-remote-gateway-validation-s5b-2026-10-01).
- You must supply the server command, environment, and working directory; OCI
  `ENTRYPOINT`/`CMD`, `ENV`, and `WORKDIR` are not resolved.
- Security milestones are incomplete: name-based cleanup can affect a sandbox
  that reuses the name (SEC8a), and the local VM lane offers no process-capacity
  isolation against hostile workloads. See the [security guide](docs/security.md).

## Development

```bash
uv sync --locked --all-groups
make check        # Ruff format/lint, strict Pyright, unit tests with ≥95% branch coverage
```

Unit tests use typed fakes and need no OpenShell installation or gateway. Tests
that need a real gateway are marked `integration`, live in `tests/integration`,
and are opt-in:

```bash
make openshell-prereqs   # CLI/gateway versions and workspace access
make openshell-smoke     # disposable sandbox with an HTTP service route
OPENENV_OPENSHELL_ECHO_IMAGE_ID=... uv run pytest -m integration --no-cov tests/integration/test_quickstart.py
make integration         # every opt-in runtime test
make security-e2e        # filesystem and network denial jobs
```

The [integration guide](tests/integration/README.md) lists each suite and its
image inputs; [integration CI](docs/integration-ci.md) covers the gated runner.

The [Quality workflow](.github/workflows/quality.yml) runs `make check` and
builds the sdist and wheel on Python 3.11 through 3.14. To reproduce one job:

```bash
export UV_PYTHON=3.12 UV_LOCKED=true
uv lock --check
uv sync --locked --all-groups
make check
uv build --no-build-isolation
```

Release preparation is described in [releases](docs/releases.md). Acceptance
evidence for each milestone is recorded in
[M0](docs/protocol-spike.md#m0-acceptance-verification-2026-09-30),
[M1](docs/provider-acceptance.md), the
[OpenEnv client check](docs/openenv-compatibility.md), and the
[security review](docs/security-review.md). The
[Codex local environment](.codex/environments/environment.toml) runs
`uv sync --locked --all-groups` for new worktrees.

The public repository is
[rodrigosetti/openenv-openshell](https://github.com/rodrigosetti/openenv-openshell);
see the [publication guide](docs/repository-publication.md).

## License

Apache-2.0; see [LICENSE](LICENSE).
