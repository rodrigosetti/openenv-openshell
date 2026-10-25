# Compatibility matrix

I6 tests the dependency range endpoints supported by this repository. Both
ranges are exact pins, so the oldest and newest supported pair are the same:

| OpenEnv client | OpenShell SDK | OpenShell gateway | Runtime evidence |
| --- | --- | --- | --- |
| 0.10.0 | 0.1.2 official hash-pinned wheel | 0.1.2 | Local Apple Silicon VM / native arm64 EchoEnv |

OpenEnv's former `>=0.4,<0.7` range was narrowed in P10 to the release actually
validated. The current 0.10.0 client pin includes the upstream factory
cancellation fix; 0.6.0 is retained below only as historical evidence.
OpenShell 0.0.116 lacks the required service and deletion contracts;
the adapter rejects it. No additional releases are supported by this matrix.
An exact pin is a bounded range, not evidence for adjacent versions. See
[OpenEnv compatibility](openenv-compatibility.md) and the
[OpenShell SDK contract](openshell-sdk-contract.md) for the upstream boundaries.

## Offline and CI checks

```bash
uv sync --locked --all-groups
make compatibility
make check
```

`make compatibility` runs the reviewed dependency-bound test, unmodified
OpenEnv factory/protocol/cleanup tests in async and sync modes, real SDK model
and signature snapshots, and production adapter contracts. It also checks
rejection of incompatible SDK/gateway versions before create and cleanup of a
client acquired for an incompatible gateway. It uses no CLI or live gateway.
The focused command disables coverage collection; `make check` retains the
repository-wide coverage requirement.

The Quality workflow has a dedicated dependency-pair matrix on Python 3.11.
Its matrix labels are checked against both installed versions and the reviewed
pair; relabeling a job cannot make an untested pair appear supported. Installation
uses the lock and the exact official SDK wheel URL/hash, rather than the unrelated
older PyPI SDK. I13 keeps that pin in the development group and in
`requirements-openshell.txt`; the dependency-bound test checks both. Published
metadata omits the SDK URL because package indexes reject direct references.
Users install the exact SDK separately following the [release instructions](releases.md).
The full quality job separately exercises Python 3.11–3.14.
Local execution does not establish that those hosted CI jobs have run.

## Live pair validation

Verified October 24, 2026 on Python 3.11.8 with OpenEnv **0.10.0** and official
SDK/gateway **0.1.2**, local Apple Silicon native VM driver, and the unchanged
arm64 image `sha256:21f3855dde019fb73eccc853f0d14308fbca702b30357add0bbb0cbc898a18f6`:
all three live client tests passed in 52.14 seconds. Both client modes completed
health, two episodes, six steps, state, and client-owned cleanup. The cancellation
case observed a real pending handshake, preserved the original cancellation
message, and confirmed deletion by state, metadata, and independent name/ID
absence before fixture teardown. Sandboxes `oe-e2e-109c81c02f` (async),
`oe-e2e-c32aec61c7` (sync), and `oe-e2e-9bc5d22f90` (cancellation) were deleted.

The initial runtime attempt failed before creation because the idle local
gateway reported an internal missing-socket error. Independent listings were
empty. Restarting that service restored provisioning without changing its
version, authentication, driver configuration, image, or policy.

The 0.10.0 review also passed `make check` (471 unit tests, Ruff, strict Pyright,
99.54% branch-inclusive coverage), all 101 `make compatibility` checks, and a
strict documentation build. Before the upgrade, both new factory cancellation
controls failed on 0.6.0 because no delete was attempted. The lock changes only
OpenEnv's version/artifact hashes and its new edge to the already locked
`jsonschema` dependency; no OpenShell dependency is widened.

After [local runtime setup](local-openshell-testing.md), run:

```bash
OPENENV_OPENSHELL_ECHO_IMAGE_ID="$(cat tests/integration/images/echo/local-image-id.txt)" \
  uv run --locked pytest -m integration --no-cov \
  tests/integration/test_openenv_client.py -v
```

The runtime fixture checks gateway 0.1.2 and workspace access before startup.
Each mode verifies routed HTTP health, two reset episodes, six echo steps
including Unicode and multiline input, state, client close, and independent
confirmation that the sandbox is absent before fallback teardown.

Verified September 30, 2026 on Python 3.11.8 with the installed OpenEnv 0.6.0
and official SDK/gateway 0.1.2: both live cases passed (43.13 seconds), and
all 88 focused offline compatibility checks passed. This repeats the pair's
runtime evidence using the current I2 test rather than inferring support from
the earlier spike.

This validates the client/SDK/gateway pair on the documented local image and
driver. It does not validate arbitrary images, other compute drivers, remote
service authentication (S5a), long idle sessions, or reconnect behavior. A CI
offline pass alone must not be recorded as runtime compatibility.

## Adding a supported pair

Review the new OpenEnv factory/transport/cleanup API and OpenShell wheel,
generated models, lifecycle signatures, and gateway release together. Update
the private adapter and reviewed snapshots as needed, then exercise the proposed
oldest and newest pairs in isolated dependency environments and matching live
gateways. Run both offline contracts and the live EchoEnv test for every pair
before widening dependency bounds or changing SPEC.md's exact target. Record
driver/image and runtime evidence here, and update the Quality matrix and
dependency-bound test together. Do not silently mix release families or infer
support from dependency resolution alone.
