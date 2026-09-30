# OpenShell 0.1.2 policy examples

These examples target the exact SDK/gateway 0.1.2 pair in `uv.lock`.
Their field shapes are checked offline against the installed release wheel;
they are reviewable starting points, not evidence of live enforcement.
The production provider's startup/cleanup and `policy_mode` API are still
pending. Do not pass `policy_mode="strict"` or `policy_mode="image"` today.

| Example | Intended use | Tradeoff |
| --- | --- | --- |
| `deny-all.yaml` | Strict filesystem/identity starting point; no declared agent egress | Requires Landlock support and an image with a `sandbox` user/group |
| `hf-minimal.yaml` | Same strict posture, with read-only REST access to `huggingface.co:443` for `/usr/bin/curl` | Allows reads across that host; does not support every Hub download flow |
| `image-compatible.yaml` | Image-baked policy for compatibility experiments | Best-effort Landlock and automatic writable workdir broaden the posture |

## Strict example

Validate the explicit policy from the repository root without a gateway:

```bash
uv run python -c 'from openenv_openshell.policy import load_policy; load_policy("examples/policies/deny-all.yaml")'
```

The configuration accepted by the provider is:

```python
from openenv_openshell import OpenShellProvider

provider = OpenShellProvider(policy="examples/policies/deny-all.yaml")
```

This constructs configuration only; `start_container()` remains unimplemented.
The adapter embeds a loaded explicit policy in the initial create request.
An invalid explicit policy must stop startup, never trigger image/default
selection. See [SPEC sections 18–19](../../SPEC.md#18-policy-configuration).

Strict examples explicitly disable `include_workdir`, keep `/app` read-only,
and allow writes only to `/workspace`, `/tmp`, and `/dev/null`. Prepare those
paths in the image with suitable permissions for the `sandbox` user/group.
Install code and dependencies under the listed read-only trees. The current
EchoEnv probe image does not provision this identity; adapt the image before
using these strict examples. `hard_requirement` requires Landlock enforcement;
an unsupported runtime must fail instead of degrading to best effort.

These paths are a portable starting point, not universal least privilege.
`/etc`, `/proc`, and system library trees contain more than a particular task
may need; narrow them after measuring workload requirements. Do not place
secrets in allowed paths. Unix permissions still apply; a policy grant does
not create directories or override ownership. No host filesystem mounts or
credential providers are requested by these YAML files.

Empty `network_policies` declares no agent egress. OpenShell-managed inbound
HTTP/WebSocket service routing is a separate control-plane mechanism, not an
outbound grant. `deny-all` does not mean every filesystem operation is denied.

## Minimal Hugging Face reads

`hf-minimal.yaml` adds one binary/host/port rule with REST inspection and
`enforcement: enforce`. The access preset is `read_only`; audit mode would
allow violations. TLS handling is left automatic. The release's
[protobuf schema](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/proto/sandbox.proto)
marks `tls: terminate` and `tls: passthrough` as deprecated and rejected by
gateway validation, even though protobuf conversion accepts their enum names.

The rule requires `/usr/bin/curl` in the image and a client that supports
OpenShell's proxy/TLS trust configuration. Python requests, git, package
registries, model APIs, subdomains, and download/CDN redirect hosts are not
declared. A full Hub client may need additional reviewed binary and endpoint
rules. Add only the destinations and operations the workload requires; avoid
wildcard hosts as a compatibility shortcut. This example attaches no secrets.

## Image-mode selection example

Image mode is a selection strategy, not a `policy_mode` YAML field. The
intended order in SPEC is explicit sandbox policy, then image policy, then
OpenShell's restrictive default. Image contents are trusted configuration:
inspect and pin the image and its policy before relying on that strategy.

For an image you control, bake the compatibility example into its Dockerfile:

```dockerfile
# Build with the repository root as the context.
COPY examples/policies/image-compatible.yaml /etc/openshell/policy.yaml
```

At the existing adapter boundary, omitting an explicit policy preserves the
SDK's image discovery behavior. `tests/unit/test_policy_examples.py` checks
that `CreateRequest(policy=None)` leaves `SandboxSpec.policy` absent. This is
an offline selection example; it does not implement provider image mode.
The pinned wheel's `openshell/sandbox.py` (`_default_spec`) documents discovery
at `/etc/openshell/policy.yaml`. The adapter must preserve absence rather than
send an empty policy message. `load_policy(None)` deliberately raises: it is
an explicit-policy loader, not an image/default selector.

`image-compatible.yaml` keeps egress undeclared but uses `best_effort` and
`include_workdir: true`; the selected workdir can become writable even if it
contains application code. Its omitted process stanza does not request a
non-root identity. Review the actual image/default policy: another image may
declare broader filesystem or network access. This policy mirrors the
[EchoEnv probe fixture](../../tests/integration/images/echo/policy.yaml) whose
local evidence is documented in [echo-env-image.md](../../docs/echo-env-image.md).
Compatibility does not establish least privilege.

## Validation limits

The offline tests load all three files with the project's strict loader,
round-trip their exact fields through the 0.1.2 `SandboxSpec.policy`, and
check the intended filesystem, identity, and network grants. They require no
OpenShell CLI or gateway. Schema validity alone cannot establish kernel support,
image users/paths, TLS inspection, or gateway semantic acceptance.

SEC4 must demonstrate policy application before execution; SEC5 and SEC6
must demonstrate filesystem and network denial on the real runtime. Those
checks, and the remaining provider lifecycle work, are required before treating
these examples as a supported end-to-end quickstart.
