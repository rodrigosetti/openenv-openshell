# One-file lifecycle spike (S4)

The standalone [Python experiment](https://github.com/rodrigosetti/openenv-openshell/blob/main/tests/integration/_lifecycle_spike.py)
uses the pinned OpenShell 0.1.2 SDK to create the selected EchoEnv image with
an atomic, unnamed service on target port 8000, wait for OpenShell readiness,
and obtain the create-time routed URL. It then deletes the sandbox and waits
for absence using its original ID. The returned URL describes the completed
experiment; its sandbox has already been deleted.

Run from the repository root after the [local setup](local-openshell-testing.md)
and [image preparation](echo-env-image.md):

```bash
uv sync --locked --all-groups
uv run python -m tests.integration._lifecycle_spike
```

The script defaults to the checked-in local image ID and `default` workspace.
`OPENENV_OPENSHELL_ECHO_IMAGE_ID` can select another deliberately validated
immutable local ID, and `OPENSHELL_WORKSPACE` selects the workspace. The public
SDK selects the CLI's active gateway or `OPENSHELL_GATEWAY`; TLS settings are
unchanged. SDK and gateway must both be exactly 0.1.2.

The opt-in integration wrapper requires the image environment variable so the
ordinary integration lane does not unexpectedly create this sandbox:

```bash
OPENENV_OPENSHELL_ECHO_IMAGE_ID="$(cat tests/integration/images/echo/local-image-id.txt)" \
  uv run pytest -m integration --no-cov tests/integration/test_lifecycle_spike.py \
  -v --log-cli-level=INFO
```

Coverage is disabled for this standalone runtime experiment only; `make check`
still enforces the production package's coverage threshold.

## Boundaries and failure handling

The spike is separate from `src/openenv_openshell` and does not implement the
production provider's start/stop methods. Its generated workload and policy
models are confined to this experimental compatibility file. Runtime operations
use public `SandboxClient` calls and `ServiceExposure`, consistent with the
[S1a model decision](openshell-sdk-contract.md#s1a-decision-official-wheel-and-confined-generated-models).
Signature-aware offline tests in
[`test_lifecycle_spike.py`](https://github.com/rodrigosetti/openenv-openshell/blob/main/tests/unit/test_lifecycle_spike.py) exercise its
actual SDK inputs, route persistence, failures, interruption, and deletion ID.

The embedded fixed policy matches the S3a image fixture: read-only `/app` plus
the observed baseline, writable `/tmp` and `/dev/null`, best-effort Landlock,
and no network-policy entries. Policy is included in the create request before
workload activation. This is image compatibility evidence; general YAML loading
and security enforcement acceptance remain the SEC tasks. The command field is
left empty to exercise the SDK/runtime's image handling. OpenShell readiness
alone does not establish which command executes or that the OpenEnv server is
healthy; that must be investigated with S5 protocol checks before S6 decisions.

Create uses a fresh name and label. A `finally` block attempts deletion even if
create fails before returning an ID, readiness fails, a route is missing, or
startup receives Ctrl-C/SIGTERM. If a create response is lost, deletion's returned
ID supplies the identity for the absence waiter. An unconfirmed deletion without
an ID fails cleanup. Cleanup failure makes a successful startup fail, and is
reported separately when preserving an earlier startup failure. The caller
closes the SDK client through its context manager. RPCs use a 30-second client
timeout, readiness has a 120-second budget, and deletion waiting has 60 seconds.

CLI failures omit raw SDK errors and tracebacks. Cleanup failures log only the
sandbox name to inspect. Forced process termination or repeated interruption
can prevent cleanup; inspect the logged name with the workspace CLI and remove
that sandbox if necessary. The script never deletes unrelated sandbox names.

## Verified local outcome (2026-09-29)

The opt-in test passed on SDK/gateway 0.1.2, workspace `default`, native macOS
VM compute, using the selected arm64 local image ID:

```text
sha256:21f3855dde019fb73eccc853f0d14308fbca702b30357add0bbb0cbc898a18f6
```

Sandbox `oe-s4-8d9dd92274`, ID `7dfb88f4-5743-4c5a-9ac8-f32698823cf2`,
reached OpenShell readiness with the create-time route:

```text
http://default--oe-s4-8d9dd92274.openshell.localhost:17670/
```

The SDK deleted it and its identity-aware absence wait passed. The test completed
in 8.24 seconds. `make check` passed formatting, linting, strict typing, and
169 unit tests with 100% production package branch coverage. This establishes the S4 lifecycle and atomic route contract on
the selected local runtime. It does not establish health, WebSocket, reset,
step, state, remote gateways, or the Milestone 0 gate; those remain S5/S6 work.

The subsequent [S5 protocol probe](protocol-spike.md) supplies the pinned image's
explicit command and runs health/reset/step/state before this helper deletes
the sandbox. The original standalone S4 invocation still leaves command empty
and checks lifecycle only. S5 records local protocol evidence and remote unknowns.
