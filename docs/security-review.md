# SEC8 security review

Reviewed 2026-09-30 against SPEC.md sections 5, 8, 12–24, 26–27, and 34.
The review covers the production provider/private adapter at local main
`85fa66b`, OpenEnv 0.6.0, and OpenShell SDK/gateway 0.1.2 on the native arm64 VM
lane. It records evidence and unresolved findings; it does **not** approve the
M2 security milestone or establish remote/runtime-independent enforcement.

## Findings and disposition

| Boundary | Evidence | Result and limit |
| --- | --- | --- |
| Initial policy | `policy.load_policy`, `_sdk.normalize_policy`, SEC4, `test_start_container.py` | Explicit policy is validated before gateway connection and embedded atomically with argv and service exposure. Invalid input fails locally. Omitted policy delegates to image/runtime defaults; it does not select the strict example. |
| Non-root identity | `test_security_review.py` | Hard-required Landlock and explicit `sandbox` user/group preserve UID/EUID and GID/EGID 1000, exclude supplementary root group, and permit workspace writes in the initial workload and exec. Configuration does not automatically select that identity for arbitrary images. |
| Filesystem | `test_filesystem_security.py` | Readable synthetic canaries become EACCES/EPERM under strict Landlock; initial workload and exec retain workspace/temp writes and OpenEnv protocol. SEC5 intentionally removes process identity to isolate Landlock from Unix ownership checks. Guest canaries do not establish host-mount safety. |
| Egress | `test_network_security.py` | Empty policy denies both tested HTTPS destinations; a single-host policy permits its destination and denies the other. Positive controls require HTTP 200 with certificate verification. This is destination enforcement, not exhaustive bypass or method enforcement testing. |
| Ingress | `_sdk.SDKAdapter.create`, `test_create_request.py`, I2 | One exact target port/service key is requested through OpenShell; the provider never publishes Docker host ports. Route validation rejects credentials/query/fragment and readiness avoids redirects. Local routes accept application requests without credentials; remote authentication remains S5a. |
| Command injection | `config.validate_command`, `_sdk.SDKAdapter.create`, `test_create_request.py`, `test_openshell_contract.py` | Exact argv is copied into the initial workload without shell interpolation or an added exec. Empty subsequent arguments and metacharacters remain argument data. A caller-selected shell executes the caller's shell program; the example's fixed shell command is an explicit choice. |
| Labels | `config._validate_labels`, `provider._create_request`, `test_config.py` | Keys/shapes are constrained, recognizable sensitive keys are rejected, and management labels override caller values. This heuristic cannot recognize secrets under an innocuous key: all labels must be public operational data. Labels are not ownership authorization. |
| Credentials/errors/logs | SEC7, `test_secret_safety.py` | Synthetic managed material is absent from tested environment prints; ordinary environment values remain readable. Public lifecycle messages, formatted tracebacks, retry notes and package logs omit synthetic secrets. Third-party/application logs and intentional inspection of raw exception objects are outside that evidence. |
| CPU/memory/GPU | `_sdk.SDKAdapter.create`, `test_adapter.py`, `test_openshell_contract.py` | Requested values reach the pinned wire fields. No runtime capacity/enforcement guarantee follows from serialization; different drivers may interpret these requests differently. |
| PID capacity | `test_security_review.py`, S3a console evidence | No visible `pids.max` file was found in the process's cgroup hierarchy. Both probes reported soft/hard RLIMIT_NPROC 7698. That per-user limit is not proof of a sandbox-specific process budget. SEC8b must establish a supported bound or an explicit SPEC/milestone scope decision. |
| Cleanup | `provider.start_container`, `provider.stop_container`, `_sdk.SDKAdapter.delete`, pinned SDK `DeleteSandboxRequest` | **High severity: name-based rollback can delete an unowned sandbox.** Identity-aware waiting verifies disappearance after a destructive request; it does not constrain the delete. SEC8a is required before M2 acceptance. |

## Cleanup blast radius

Before calling create, the provider records the selected name as owned. Every
create exception then enters `stop_container()`. An SDK `ALREADY_EXISTS`
response therefore triggers `delete(name, workspace=..., allow_missing=True)`
against the pre-existing sandbox. If the provider has no recorded ID, it adopts
the deletion acknowledgement's ID and waits for that sandbox to disappear.
A sanitized error and successful cleanup can mask deletion of another workload.

The offline reproduction used a signature-constrained `SandboxClient` double
through the production adapter: health returned 0.1.2, create raised a gRPC
ALREADY_EXISTS error, and delete acknowledged `pre-existing-id`. Assertions
confirmed exactly one name-based delete followed by a deletion wait for
`pre-existing-id`. No real operator sandbox was used for this reproduction.

The same risk applies when an owned sandbox disappears and its name is reused
before a cleanup retry. The current tests preserve the original **wait** ID
even when delete acknowledges a replacement; that does not prevent deleting
the replacement. The pinned public delete call and generated request have no
expected-ID condition. A separate lookup before delete alone would leave a
race. SEC8a must establish a fail-closed ownership/deletion contract, test
collision and replacement safety, and retain partial-start cleanup where
ownership can be proved. Until repaired, reserve unique names and avoid name
reuse; this reduces collision risk but is not a security guarantee.

## Resource gap and milestone decision

This adapter has no PID-limit option. The pinned process policy exposes only
`run_as_user` and `run_as_group`; CPU/memory template limits and GPU requests
are separate fields. The reviewed lane's absent cgroup PID file and inherited
RLIMIT_NPROC are recorded as a limitation, not silently interpreted as runtime
enforcement. The diagnostic only reads identity, cgroup files and limits; it
does not fork children or stress the host. Missing visible files alone do not
prove that no other driver/host capacity control exists.

SEC8b requires either evidence of a supported runtime/driver bound or an
explicit change to SPEC.md and milestone acceptance excluding that guarantee.
No guest-side limiter, private runtime fork, or weakened policy is introduced.
M2 has direct dependencies on **SEC8a** and **SEC8b**, in addition to this review,
so completing SEC8 cannot be mistaken for security acceptance. Architecture
documentation and audit exports must carry these limitations until resolved.

## Reproduce the runtime review

Use the synthetic filesystem fixture built by
[SEC5's instructions](../tests/integration/README.md#sec5-filesystem-enforcement).
The SEC8 policy retains strict Landlock, the non-root identity, empty egress,
and `include_workdir: false`; it adds read-only `/sys/fs/cgroup` solely for
diagnostics. It checks both initial workload and exec, continued routed
reset/step/state, client-owned deletion, and an independent absence listing.

```bash
OPENENV_OPENSHELL_ECHO_IMAGE_ID="$(docker image inspect --format '{{.Id}}' \
  openenv-openshell-filesystem:sec5)" \
  uv run pytest -m integration --no-cov \
  tests/integration/test_security_review.py \
  tests/integration/test_filesystem_security.py \
  tests/integration/test_network_security.py -v --log-cli-level=INFO
```

The tested fixture image is
`sha256:56f8d4785e74fe015c2f7f587ae5fe834b06c6cc6875a53ba913c25ffeec65b7`.
Use a deliberately validated compatible image when reproducing elsewhere.

Verified with that fixture on 2026-09-30: all four cases passed in 152.21
seconds (strict identity, filesystem allow/deny, and both network destination
cases). Each sandbox's deletion was independently confirmed. Both SEC8 probes
reported UID/GID 1000, `pids_max: []`, and `rlimit_nproc: [7698, 7698]`.
`make check` passed Ruff, strict Pyright, and 416 unit tests with 99.50%
branch-inclusive coverage. The offline collision reproduction confirmed the
cleanup finding above. These passing controls leave SEC8a and SEC8b open.
