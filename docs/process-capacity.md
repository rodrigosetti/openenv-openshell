# Process-capacity scope decision (SEC8b)

On 2026-09-30, SEC8b adopts the explicit scope-decision outcome permitted by its
acceptance criteria. For v0.1 on the local OpenShell SDK/gateway 0.1.2 native
arm64 VM lane, a guaranteed sandbox-specific process/thread budget and protection
against process-exhaustion denial of service are excluded. This resolves the
contract question; it does not fix or demonstrate runtime PID enforcement.
[SPEC section 22.1](https://github.com/rodrigosetti/openenv-openshell/blob/main/SPEC.md#221-process-capacity-sec8b-scope-decision) governs
this decision and M2 acceptance must preserve the limitation.

## Evidence and interpretation

| Evidence | What it establishes |
| --- | --- |
| [S3a VM console](echo-env-image.md#verified-outcome-012-2026-09-29) warns that `pids.max` is unavailable | The validated image/runtime lane has a recorded PID-control gap. |
| [SEC8 read-only initial-workload and exec diagnostics](security-review.md#resource-gap-and-milestone-decision) on 2026-09-30: `pids_max: []`, `rlimit_nproc: [7698, 7698]`, UID/GID 1000 | No PID cgroup limit was visible along the process's cgroup hierarchy; an inherited per-user limit is present, but no sandbox-specific bound was established. |
| [Pinned policy schema](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/proto/sandbox.proto): `ProcessPolicy` | Process policy configures user/group identity only. |
| [Pinned resource schema](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/proto/openshell.proto): `ResourceCapabilities`, `SandboxResources` | Portable resource fields describe CPU, memory, and GPU, without a portable PID-budget field. |
| `OpenShellResources` and [adapter contracts](openshell-sdk-contract.md#workload-policy-providers-and-resources) | The provider maps CPU/memory/GPU requests; it exposes no process-capacity setting. Wire tests do not establish runtime enforcement. |

The SEC8 diagnostic used disposable fixture image
`sha256:56f8d4785e74fe015c2f7f587ae5fe834b06c6cc6875a53ba913c25ffeec65b7`.
It inspected `/proc/self/cgroup`, visible ancestor `pids.max` files, and
RLIMIT_NPROC in the initial workload and an exec process. It created no child
process load. Missing guest-visible files do not prove that host/driver controls
are absent. No fork-to-failure experiment or new enforcement test was run for
SEC8b; the decision relies on the existing diagnostic and pinned API boundary.

## Residual risk and responsibility

A process burst may exhaust the guest, stop OpenEnv health/protocol responses,
affect other workloads sharing capacity, and consume host resources. Non-root
execution and Landlock do not establish a per-sandbox process quota. Neither
the inherited RLIMIT_NPROC nor finite VM memory proves the desired isolation.
The local VM lane must not be advertised as providing availability isolation
for hostile workloads, even after M2's filesystem/network controls pass.

The runtime/compute driver owns capacity enforcement. Operators needing it must
choose and validate an enforcing deployment before relying on that guarantee.
Dedicated disposable capacity reduces shared-workload exposure but does not
prove PID enforcement. This provider adds no guest limiter, arbitrary resource
struct keys, runtime fork, policy weakening, or hidden fallback.

Any future guarantee needs a supported upstream setting, evidence of its effective
sandbox-specific bound and enforcement owner, coverage of initial and exec
processes (including threads where relevant), and bounded non-destructive
positive/negative controls with cleanup. Remote gateways and other compute
drivers require their own evidence; neither support nor lack of enforcement
is inferred from this local decision.

M2 remains gated on its other dependencies, including SEC8a cleanup ownership
safety. Closing SEC8b records this scope decision only and does not close M2.
