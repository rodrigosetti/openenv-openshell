# EchoEnv test image (S3 / S3a)

## Rejected registry candidate (history)

Inspected on 2026-09-29:

```text
registry.hf.space/openenv-echo-env@sha256:5e6068b14b13cf829ccaefe0549e1dea0199f9509f056a3c90f748cf72271348
```

This is the immutable manifest resolved from the upstream `latest` tag, not
an approved image for the local VM lane. Do not substitute `latest` in future
spikes. The registry currently returns a single Linux **amd64** manifest,
not a multi-platform index. The Apple Silicon setup from
[the S2 guide](local-openshell-testing.md) uses the native VM driver.

Image configuration inspection established:

- No configured entrypoint; working directory `/app`.
- CMD: `sh -c 'cd /app/env && uvicorn server.app:app --host 0.0.0.0 --port 8000'`.
- Target port: **8000**, including the image's exposed-port metadata and
  healthcheck. Do not assume the current Space documentation's port 7860
  applies to this digest.
- Python search path `/app/env:/app/src`; executable search path starts with
  `/app/.venv/bin`.
- Healthcheck requests `http://localhost:8000/health`.
- OCI revision label: `2faae32750487168419afb4f1f8dc4a9efaac5c7`.
  This is an inherited label, not proof of the EchoEnv source revision.

## Runtime and protocol evidence

A disposable Docker container with `--platform linux/amd64`, no published host
ports, and the configured uvicorn command (bound to loopback for this probe)
returned HTTP 200 with `{"status":"healthy"}` from `/health`. A
`websockets.sync.client.connect('ws://127.0.0.1:8000/ws')` handshake succeeded.
Importing `server.app:app` also showed `/health` as an HTTP route and `/ws` as
an `APIWebSocketRoute`. These checks establish image-level endpoints only;
OpenShell routing and the full reset/step/state session remain S5 work.

The installed `server/echo_environment.py` implements an **MCP-only** echo
environment. Its tool `echo_message` accepts a `message` argument. Although
`models.py` still defines `EchoAction`, the server rejects legacy actions.
For this candidate, a future hello step must use `CallToolAction` with
`tool_name="echo_message"` and `arguments={"message": "hello"}`; do not
assume `EchoAction(message="hello")` works. Client compatibility must be
verified before approving the candidate.

## Local driver blocker

CLI/gateway 0.0.116, workspace `default`, native macOS VM driver:

```bash
openshell sandbox create --workspace default --name oe-s3-echo \
  --from registry.hf.space/openenv-echo-env@sha256:5e6068b14b13cf829ccaefe0549e1dea0199f9509f056a3c90f748cf72271348 \
  --detach -- sh -c 'cd /app/env && uvicorn server.app:app --host 0.0.0.0 --port 8000'
```

The driver fetched and unpacked the image, then failed at VM supervisor startup:
`ProcessExited: VM process exited with status 0`. The image is amd64-only and
`command -v ip` inside it returned no executable. S2 separately established
that the VM lane requires `iproute2`. The provisioning output does not isolate
which incompatibility caused this failure; neither requirement can be assumed
satisfied.

The failed sandbox was deleted with `openshell sandbox delete`; the subsequent
workspace sandbox list was `[]`. No service was exposed for this failed VM.
Docker probe containers used `--rm`.

This failed candidate is retained as investigation history. The selected native
image below resolves the S3 compatibility blocker. S3a revalidated it with the
SDK/gateway 0.1.2 pair selected by S1a; see the release-specific evidence below.

## Reproduce inspection

```bash
docker buildx imagetools inspect registry.hf.space/openenv-echo-env:latest
docker buildx imagetools inspect \
  registry.hf.space/openenv-echo-env@sha256:5e6068b14b13cf829ccaefe0549e1dea0199f9509f056a3c90f748cf72271348 \
  --format '{{json .Image}}'
```

The upstream [deployment tutorial][deployment] names this registry repository.
Its mutable documentation is not the source of truth for this pinned image's
port, action model, or architecture; inspect the digest before changing it.

[deployment]: https://github.com/huggingface/OpenEnv/blob/main/tutorial/02-deployment.md

## Selected local arm64 image

The [Dockerfile](https://github.com/rodrigosetti/openenv-openshell/blob/main/tests/integration/images/echo/Dockerfile) builds the native
VM test image from upstream EchoEnv source. Its immutable local Docker image ID
is recorded in [local-image-id.txt](https://github.com/rodrigosetti/openenv-openshell/blob/main/tests/integration/images/echo/local-image-id.txt):

```text
sha256:21f3855dde019fb73eccc853f0d14308fbca702b30357add0bbb0cbc898a18f6
```

This is a **local image configuration ID**, not a registry manifest digest.
It is available on this workstation and accepted directly by the local VM
adapter. It cannot be pulled from a registry. The tag
`openenv-openshell-echo:s3` is a build alias only; run validation by ID. Rebuilds
can produce different IDs because of build timestamps; inspect the new ID,
rerun validation, and update the recorded pin deliberately. Registry publishing
is not required for the local spike and has not been performed.

Pinned build inputs:

- Source commit `4f4c85fb9038f43efc2f51858a27638277f16355`, with source archive
  SHA-256 `3409c6641adb65cb6268d301101ad69226ae1aa147e79377cc1b0b711aa8e538`.
- Python 3.12 slim multi-platform base and uv 0.11.20 by digest in the recipe.
- Upstream EchoEnv `uv.lock`, installed with `uv sync --frozen --no-dev`.
  This lock selects server package `openenv==0.3.1` and `fastmcp==3.1.1`.
  This is the test server's dependency set, not a change to the provider's
  supported client dependency range. Client protocol compatibility remains S5/P10.
- Debian trixie snapshot `20260928T000000Z`, adding `iproute2` and `nftables`.
  Disabling Release-file expiry is limited to this historical snapshot;
  signed package verification remains enabled.

The workload CMD remains the upstream `sh -c 'cd /app/env && uvicorn
server.app:app --host 0.0.0.0 --port 8000'`. The image has no entrypoint,
exposes target port 8000, and healthchecks `/health`. The EchoEnv source is
unmodified and retains the MCP `echo_message` action contract.

VM 0.0.116 did not inherit the image's PATH when starting the supplied
canonical command: the first arm64 attempt exited 127. A symlink from
`/usr/local/bin/uvicorn` to the locked virtual-environment executable preserves
the upstream command while making it discoverable on the runtime's default
PATH. The CLI defaults to a shell rather than the image CMD, so the probe reads
and explicitly supplies the image's configured command. Production handling of
image configuration belongs to the adapter/spike decisions.

### Build and validate

Run from the repository root after the S2a prerequisites are ready:

```bash
docker build --platform linux/arm64 -t openenv-openshell-echo:s3 \
  -f tests/integration/images/echo/Dockerfile tests/integration/images/echo
docker image inspect openenv-openshell-echo:s3 --format '{{.Id}}'

# Use the recorded ID if already present, or the inspected ID after rebuilding.
OPENENV_OPENSHELL_ECHO_IMAGE_ID="$(cat tests/integration/images/echo/local-image-id.txt)" \
  uv run pytest -m integration --no-cov tests/integration/test_echo_image.py -v --log-cli-level=INFO
```

The opt-in [image integration test](https://github.com/rodrigosetti/openenv-openshell/blob/main/tests/integration/test_echo_image.py)
requires CLI/gateway 0.1.2, checks architecture and CMD, creates a unique labeled
sandbox with the [image policy fixture](https://github.com/rodrigosetti/openenv-openshell/blob/main/tests/integration/images/echo/policy.yaml),
exposes port 8000 through OpenShell, polls routed `/health`, verifies `/ws` upgrade,
logs runtime diagnostics, and deletes the
sandbox in `finally`, including after a failed create or probe. It checks that
the uniquely labeled sandbox disappears using `sandbox list --selector ... --names`,
which avoids depending on the release-specific JSON pagination shape. Each CLI operation and
probe has a timeout. The marker excludes it from unit runs; without an image ID
it skips without touching Docker or OpenShell. Coverage is disabled only for
this image-only probe because it does not execute provider code; `make check`
retains the package's 95% coverage floor.

The WebSocket probe connects its TCP socket to loopback while preserving the
OpenShell route's Host header. This avoids requiring system DNS resolution of
`*.openshell.localhost`, without bypassing gateway service routing or opening a
Docker host port. It tests a handshake, not a reset/step/state session.

### Historical verified outcome: 0.0.116 (2026-09-29)

CLI/gateway 0.0.116, workspace `default`, native Apple Silicon VM: image
provisioning, HTTP 200 `/health`, and WebSocket `/ws` upgrade passed through a
named OpenShell service. The integration test confirmed deletion. The failed
exploratory arm64 sandboxes were also deleted.

The exploratory VM console reported Landlock unavailable and no runtime
`pids.max` cgroup limit. These are runtime security limitations, not evidence of
filesystem/resource enforcement. No gateway or policy settings were weakened.
The final image includes `nftables` to address the observed missing-utility
warning. Security acceptance remains in the SEC lane; S3 proves workload/image
compatibility only. Remote gateways and full OpenEnv sessions remain unverified.

### Verified outcome: 0.1.2 (2026-09-29)

S3a used the same pinned arm64 image ID above, without rebuilding or changing
its upstream workload command. CLI/gateway were both 0.1.2, workspace `default`,
with the native VM configuration validated by S2a. The probe checks both versions
before creating a sandbox and remains separate from the provider implementation.

The first attempt (`oe-echo-ae114892`, ID
`06fada07-f02d-41a2-94b1-d94a5c169391`) booted but exited with status 126 and
never became healthy. Its effective baseline filesystem policy did not include
`/app`, which contains the virtual-environment executable and server source.
Unlike the historical runtime, its guest console reported Landlock available
(ABI v6), applying a V3 ruleset with 13 applied rules and none skipped. These
observations suggested a filesystem-access failure; the runtime did not provide
a per-path denial identifying the exact failing syscall. The probe's `finally`
block deleted this failed sandbox and confirmed absence.

The checked-in image policy copies the observed 0.1.2 baseline and adds only
read-only `/app` access. It keeps `include_workdir: true`, the baseline writable
`/tmp` and `/dev/null`, `landlock.compatibility: best_effort`, and empty
`network_policies`. It is explicitly supplied through `--policy` before workload
activation. No gateway controls or policy validation settings were weakened.
This is a test-image compatibility policy, not a provider default or the SEC3
policy example deliverable.

With that policy, `oe-echo-b9822aee` (ID
`fe46859f-a10e-41f4-9176-985e97587605`) passed HTTP 200 with a healthy status at
`http://default--oe-echo-b9822aee--echo.openshell.localhost:17670/health`
and a WebSocket handshake at the same route's `/ws`. Initial service connections
were refused while uvicorn started; the bounded health polling handled this.
Runtime logs confirmed the canonical command, initial policy loading, and
successful service relays. Deletion and the unique-label absence check passed.
The opt-in test passed in 16.03 seconds. After tightening the healthy-status
assertion, the final probe passed again in 16.49 seconds. A separate workspace
listing confirmed no sandboxes remained. `make check` passed 93 unit tests with
100% branch coverage, formatting/lint checks, and strict typing.

Security limits observed during the 0.1.2 run:

- The guest console still warned that runtime cgroup `pids.max` is unavailable;
  a PID limit must be supplied by the runtime/compute driver before claiming it.
  [SEC8's review](security-review.md) rechecked the process hierarchy and records
  the capacity observations. [SEC8b's decision](process-capacity.md) explicitly
  excludes the PID guarantee from this lane's v0.1 contract and M2 acceptance.
- Landlock was reported available and applied in both the failed baseline
  attempt and the successful final probe (14 rules applied, none skipped),
  improving on 0.0.116's unavailable warning. This does not prove the SEC filesystem denial
  acceptance criteria or strict Landlock behavior; the fixture uses best effort.
- The host supervisor could not open `/var/log` for rotation and used stderr
  logging. It did not prevent workload startup, routing, or deletion.

S3a establishes pinned-image workload, routed health/WebSocket handshake, and
cleanup compatibility on 0.1.2. Full reset/step/state sessions were validated
by S5 and remote gateway behavior by S5a (below). Enforcement acceptance remains
the SEC lane.

## Docker-driver variant (S5a)

The remote S5a gateway used the OpenShell 0.1.2 **Docker** driver on linux/amd64.
That driver has two image requirements the VM lane does not enforce. It resolves
the policy identity, or the image `Config.User` if none is set, to one non-root
UID and rejects UID 0. The resolved identity must also be able to enter and
write the workdir. The pinned image runs as root in root-owned `/app/env`. The
sandbox therefore entered the error phase with `ControlSupervisorStartFailed`:
`image workspace validation failed ... identity in the image: Permission denied`.

S5a first built the unchanged [Dockerfile](https://github.com/rodrigosetti/openenv-openshell/blob/main/tests/integration/images/echo/Dockerfile)
for linux/amd64 and pushed it to a public GHCR package:

```text
ghcr.io/rodrigosetti/openenv-openshell-echo@sha256:f7bac7ca74ba3950b98508e838a3fe2ee5a90fd46334cea13875dfb83030f1c8
```

[`Dockerfile.docker-driver`](https://github.com/rodrigosetti/openenv-openshell/blob/main/tests/integration/images/echo/Dockerfile.docker-driver)
adds a UID 1000 `sandbox` account on top of that digest, with `WORKDIR /sandbox`
and `USER sandbox`. The EchoEnv code and venv stay root-owned and readable. The
canonical command still changes into `/app/env`. The result, recorded in
[`remote-image-ref.txt`](https://github.com/rodrigosetti/openenv-openshell/blob/main/tests/integration/images/echo/remote-image-ref.txt),
passed remote readiness and the full protocol probe:

```text
ghcr.io/rodrigosetti/openenv-openshell-echo@sha256:02ea3505fc0b0a451778442ca2994c6be94a45ae4572358899b41b98c1df60a0
```

Rebuilding the layer produces a different digest, because account creation
records a date. Pin the recorded digest instead of rebuilding.

```bash
docker buildx build --platform linux/amd64 --provenance=false --sbom=false \
  -f tests/integration/images/echo/Dockerfile.docker-driver \
  -t ghcr.io/OWNER/openenv-openshell-echo:docker-driver --push \
  tests/integration/images/echo
```

The local arm64 VM-lane image and its pinned ID are unchanged. This variant has
not been validated on the VM lane.
