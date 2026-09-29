# Local OpenShell integration setup

This guide prepares a workstation for the opt-in integration tests. Unit tests
must not depend on these prerequisites.

The supported local path is an Apple Silicon macOS or supported Linux host with
an OpenShell CLI and gateway plus one configured compute driver. OpenShell's
current support matrix lists Docker 28+, Podman 5.x, Kubernetes 1.29+, and the
host-dependent MicroVM driver. See the [support matrix][support]. Keep the Python SDK and gateway in the same
OpenShell release family.

## 1. Install the runtime

Follow the official [OpenShell installation guide][install]. The project
lockfile currently selects SDK `0.0.116`, so pin the CLI and gateway to the
matching release rather than accepting the installer's latest release:

This verifies the currently locked `0.0.116` pair. The product specification
targets `0.1.2`; S1a must resolve its SDK distribution and model boundary before
that pair can be selected. See the [SDK contract](openshell-sdk-contract.md).
Repeat this smoke test when the supported SDK/gateway pair changes.

```bash
curl -LsSf https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh \
  | OPENSHELL_VERSION=v0.0.116 sh
openshell status
```

On macOS, the package-managed gateway normally listens at
`https://localhost:17670` and can be inspected or restarted with Homebrew:

```bash
brew services list
brew services restart openshell
```

Choose one compute backend before testing. On Apple Silicon, the tested path
uses OpenShell's native `vm` driver, backed by Hypervisor.framework. Apple's
`container` CLI is not a built-in OpenShell compute driver. Docker and Podman
are also options; see the [compute-driver reference][drivers].

Install the guest disk formatter and build the small prerequisite image:

```bash
brew install e2fsprogs
docker build -t openenv-openshell-prerequisites:0.0.116 \
  tests/integration/images/prerequisites
```

This uses Docker Desktop to build and store an OCI image. Sandbox execution
uses the VM driver. To avoid a local Docker daemon entirely, build the image
elsewhere, publish it to a registry, and use its immutable reference for both
VM image settings and `OPENENV_OPENSHELL_SMOKE_IMAGE`.

The supplied [VM configuration](examples/gateway-vm.toml) selects `vm` explicitly
(it is never auto-detected) and uses the small image for both the workload and
bootstrap disk. On a fresh Homebrew installation, install it with:

```bash
install -m 0644 docs/examples/gateway-vm.toml \
  /opt/homebrew/var/openshell/gateway.toml
brew services restart openshell
openshell status
```

For an existing gateway, merge these settings into its active configuration
instead of replacing that file. The user configuration at
`~/.config/openshell/gateway.toml` takes precedence over the Homebrew file.

The PyPI `openshell` dependency in this project is the Python SDK; it does not
install the CLI or gateway. The preflight requires CLI `0.0.116` by default.
Set `OPENENV_OPENSHELL_VERSION` only when intentionally testing another
SDK/gateway pair.

## 2. Select a workspace

The integration setup defaults to the `default` workspace. To use another
workspace, export it explicitly:

```bash
export OPENSHELL_WORKSPACE=team-ml
openshell sandbox list --workspace "$OPENSHELL_WORKSPACE"
```

An authorization failure here must be fixed before running tests. For a shared
gateway, ask a platform or workspace administrator for membership; local
gateways without OIDC role configuration treat authenticated users as platform
administrators. See the [workspace guide][workspaces] for role details.

## 3. Verify prerequisites and service routing

The non-mutating check confirms that the CLI can reach its active gateway and
access the selected workspace. It also reports whether local Docker or Podman
is reachable; a remote, Kubernetes, or MicroVM-backed gateway does not require
a local container daemon.

```bash
make openshell-prereqs
```

Then run the smoke test:

```bash
make openshell-smoke
```

The smoke test creates a uniquely named, disposable sandbox from the local
prerequisite image, starts a loopback HTTP server on port 8000, exposes that
port with `openshell service expose`, requests the returned gateway-managed URL,
and deletes the sandbox on success, failure, or interruption. It validates the
compute driver and HTTP service route needed by the provider; WebSocket protocol
verification belongs to roadmap task S5.

Override the image or target port when a driver or registry policy requires it:

```bash
OPENENV_OPENSHELL_SMOKE_IMAGE=registry.example/test/prerequisites:0.0.116 \
OPENENV_OPENSHELL_SMOKE_PORT=8080 \
make openshell-smoke
```

If cleanup reports a warning, inspect and remove the named sandbox before
retrying:

```bash
openshell sandbox list --workspace "${OPENSHELL_WORKSPACE:-default}"
openshell sandbox delete --workspace "${OPENSHELL_WORKSPACE:-default}" <name>
```

## 4. Run integration tests

After the smoke test passes, install the project dependencies and run the
opt-in lane:

```bash
uv sync --all-groups
make integration
```

Keep real-gateway tests marked `integration`; the default `make check` lane
must remain hermetic and must not create sandboxes. There are no automated
integration tests yet; the standalone smoke check is the S2 verification lane.

## Verified setup (2026-09-29)

On Apple Silicon macOS, CLI and gateway `0.0.116` authenticated over mTLS at
`https://localhost:17670`; the `default` workspace was accessible. Gateway logs
confirmed `openshell-driver-vm`. With `e2fsprogs` installed and the supplied
Python/iproute2 image built locally, the smoke test completed a successful HTTP
request through `http://default--<sandbox>--openenv-smoke.openshell.localhost:17670/`.
The script deleted the sandbox, and `sandbox list --output json` returned `[]`.

Important release-specific findings:

- `0.0.116` uses `service expose` after creation; it has no create `--expose`
  option. `sandbox create --output json` also conflicts with a trailing command.
- Sandbox names are limited to 19 characters; the check uses a short name.
- A plain Python image failed VM compatibility validation because `iproute2`
  was absent. The supplied image adds it. Alpine and unmodified Python slim
  images also exited during Docker provisioning; the cause was not established.
- VM disk preparation failed until `e2fsprogs` was installed. The driver finds
  the Homebrew keg without adding it to the shell's `PATH`.
- HTTP routing can initially return `502` while the workload starts after VM
  readiness. The check retries 30 times with a two-second request timeout.

The base Python image is pinned by digest in the Dockerfile; Debian packages
are resolved at build time. This prerequisite image is separate from S3's
EchoEnv image investigation and does not establish OpenEnv/WebSocket support.

[drivers]: https://docs.nvidia.com/openshell/latest/reference/sandbox-compute-drivers
[install]: https://docs.nvidia.com/openshell/latest/about/installation
[workspaces]: https://docs.nvidia.com/openshell/latest/how-it-works/workspaces
[support]: https://docs.nvidia.com/openshell/reference/support-matrix

See [S3 image findings](echo-env-image.md) for the immutable candidate and the
remaining architecture/VM compatibility blocker.
