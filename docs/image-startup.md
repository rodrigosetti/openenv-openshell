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

The [comparison test](../tests/integration/test_image_startup.py) passed both
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

## Outcome and proposed API decision

The selected API cannot satisfy automatic image startup in SPEC section 12.3.
Passing an empty command through the current adapter would silently start a
shell. A thin adapter cannot recover OCI CMD, ENTRYPOINT, WORKDIR and ENV from
an arbitrary image reference using this SDK alone. Local `docker inspect`
would violate the remote-caller requirement; copying the EchoEnv command would
only work for the test fixture.

**Proposed explicit startup mode for 0.1.2:** make the already suggested
`command: Sequence[str] | None` constructor option supported and require a
nonempty exact argv until a public upstream image resolver exists. Callers
would supply the image's intended command (including ENTRYPOINT composition
when applicable), required environment through `env_vars`, and an explicitly
chosen command that establishes the required directory. This is an opt-in
workload override, not automatic OCI metadata preservation. Missing command
would fail before create with an actionable compatibility error. Command
inputs and their errors would remain secret-safe. The private adapter would
then gain a command field and pinned argv/environment contracts.

Accepting this proposal requires amending sections 9, 12.3, 36 and the applicable
acceptance claims: image-only quickstarts cannot work on the tested VM lane.
If automatic image startup remains mandatory, P4 instead needs an upstream
public image-startup API (or an explicitly approved registry-resolution
boundary with architecture, authentication, digest and metadata contracts).
A registry resolver alone still needs a supported workdir strategy. Do not
implement that broader integration implicitly inside provider startup.

S6a completes the comparison and records the exact limitation and proposal.
**S6b** tracks the required product/API decision and blocks **P4**. No production
startup behavior or public API changes are authorized by this finding alone;
the current SPEC requirement remains in force. The existing adapter therefore
remains unchanged rather than presenting empty argv as supported image startup.
