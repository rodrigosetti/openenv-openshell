# Image startup validation (S6a)

## Runtime comparison, 2026-09-30

SDK, CLI and gateway: **0.1.2**. Workspace: `default`. Compute driver: native
Apple Silicon VM. Both attempts used the unchanged image and initial policy
from [S3a](echo-env-image.md), an atomic unnamed service targeting 8000, and
identity-aware deletion in `finally`.

Image configuration ID:

```text
sha256:21f3855dde019fb73eccc853f0d14308fbca702b30357add0bbb0cbc898a18f6
```

Inspection confirmed no ENTRYPOINT, WORKDIR `/app/env`, and CMD:

```json
["sh", "-c", "cd /app/env && uvicorn server.app:app --host 0.0.0.0 --port 8000"]
```

The image also declares PATH beginning `/app/env/.venv/bin`, PYTHONPATH
`/app/env`, and PYTHONUNBUFFERED `1`. These are image metadata, not evidence
that the VM runtime injects them.

| Request | Observation | Cleanup |
| --- | --- | --- |
| `spec.command` omitted | `oe-s4-452d069446`, ID `edca7776-b470-45f0-8f56-4f2c0d794ac8`, reached Ready. Routed health never succeeded within the 10-second observation window; no protocol session was possible. | Original ID deletion/absence verified. |
| Exact image CMD supplied | `oe-s4-2541c7f11b`, ID `c05650c8-13ad-4a7b-9d55-ef6c648e1ada`, reached Ready. Routed HTTP 200/healthy, two reset episodes, four echo steps, state transitions, and ping/pong passed. | Original ID deletion/absence verified. |

The [comparison test](https://github.com/rodrigosetti/openenv-openshell/blob/main/tests/integration/test_image_startup.py) passed both
cases in 32.61 seconds. The omitted-command case asserts the known limitation;
it does **not** establish successful workload startup. The bounded observation
alone would not prove CMD can never start; the source contract below explains
why it does not. The successful command includes its own `cd` and benefits from
the image's uvicorn symlink, so it proves neither automatic WORKDIR selection
nor image PATH preservation. This image has no ENTRYPOINT; nonempty ENTRYPOINT
composition was not runtime-tested. Remote drivers remain S5a scope.

Reproduce after the local prerequisites are ready:

```bash
OPENENV_OPENSHELL_ECHO_IMAGE_ID="$(cat tests/integration/images/echo/local-image-id.txt)" \
  uv run pytest -m integration --no-cov tests/integration/test_image_startup.py \
  -v --log-cli-level=INFO
```

The test skips without an explicit image ID. It does not inspect images through
Docker or introduce a Docker dependency into the production adapter.

## Pinned upstream contract

Inspected release-tagged sources, rather than the moving latest documentation:

- [Gateway create](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/crates/openshell-server/src/grpc/sandbox.rs#L463)
  leaves an omitted command empty and requests a TTY. Its comment explicitly
  selects an interactive login shell, not OCI CMD.
- [MainProcessConfig](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/crates/openshell-core/src/sandbox_env.rs#L38)
  carries nonempty command argv verbatim. Empty argv is the scratch-shell
  sentinel. The [sandbox boundary](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/crates/openshell-sandbox/src/boundary_server.rs#L2853)
  resolves that sentinel to an executable login shell with `-l`.
- [VM supervisor launch](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/crates/openshell-driver-vm/src/driver.rs#L939)
  supplies `/sandbox` as the workload workdir. The guest init's `/` workdir is
  separate. No OCI WORKDIR selection appears in this VM launch path.
- [VM environment merge](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/crates/openshell-driver-vm/src/driver.rs#L5527)
  merges template environment then spec environment, so explicit spec values
  win. This becomes authenticated boundary `child_env` during provisioning.
  Image ENV is not an input to that merge. Guest boot environment is separately
  driver-owned. These are source findings, not live environment assertions.
- [SandboxSpec and SandboxTemplate](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/proto/openshell.proto#L1017)
  provide command and environment fields, but no portable startup workdir or
  image-config inspection operation. Named workload templates likewise carry
  image/environment/resources, not automatic ENTRYPOINT/CMD resolution.
  The proto comment about gateway normalization is less precise than the
  implementation: the actual gateway retains empty argv and the boundary
  selects the shell. Neither path selects OCI CMD.

The pinned Python SDK has public lifecycle/exec APIs but no public image-config
resolver. `exec(workdir=...)` configures a separate exec operation, not the
canonical create-time workload. It is not a substitute for startup semantics.
Driver-specific envelopes do not establish a portable supported workdir API.

## Adopted API decision (S6b, 2026-09-30)

S6b adopts explicit startup for SDK/gateway 0.1.2 and amends SPEC sections 9,
12.3, 36, 39, and the usage examples. Automatic OCI metadata resolution is
outside the v0.1 contract. No upstream capability is needed before P4.

`OpenShellProvider(command=server_argv)` accepts the caller's exact intended
workload argv, including ENTRYPOINT composition. Callers supply required image
environment through `env_vars` and select a command that establishes the
working directory. There is no portable `workdir` option and no automatic
image ENV merge, registry resolver, or local Docker inspection.

Configuration-only construction may omit command, but request preparation must
reject it before gateway access/create. Supplied commands must be a nonempty
sequence of NUL-free strings with a nonblank executable; bare strings/bytes are
rejected. Empty subsequent arguments, whitespace, shell syntax, and argument
order are preserved verbatim. Shell interpretation occurs only if the caller
explicitly invokes a shell. Unknown startup kwargs are rejected; constructor
command has no per-start override. Errors and representations omit argv.

The private `CreateRequest.command` maps directly to `SandboxSpec.command` in
the atomic workload/policy/service request. The adapter also rejects empty or
malformed argv before gateway access. Offline tests verify exact command and
environment transmission, defensive copying, secret-safe diagnostics, and
no-RPC rejection. The typed fake retains the command. The SEC4 integration
control now supplies its command through the production adapter instead of
injecting it at the mocked SDK call.

P4 now implements `start_container`, including local validation before connection,
create-time route capture, readiness, and best-effort failed-start deletion.
See the [P4 runtime control](https://github.com/rodrigosetti/openenv-openshell/blob/main/tests/integration/README.md#p4-provider-startup).
Public cleanup remains P6/P7 and release acceptance gates remain open.
The S6a runtime evidence above covers the explicit fixture command on the local
VM; remote images/drivers remain S5a.

### S6b validation

On 2026-09-30, `make check` passed lint, strict typing, and 268 unit tests with
99.40% branch-inclusive coverage. The revised
`tests/integration/test_policy_before_execution.py` passed in 27.39 seconds on
the same pinned image and SDK/gateway 0.1.2: invalid policies sent no create RPC,
exact request argv reached the SDK, routed health and repeated WebSocket
reset/step/state plus ping/pong passed, and `oe-sec4-4937f442` deletion/absence
was verified. This exercises the production adapter, not provider lifecycle.
