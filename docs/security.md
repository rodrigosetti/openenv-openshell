# Security boundaries and credentials

The [SEC8 security review](security-review.md) records the checked boundaries,
runtime evidence, and unresolved acceptance findings. SEC8a mitigates name
collisions and repeated deletion requests. A replacement between identity lookup
and deletion remains possible (SEC8c), and the local VM lane has no established
sandbox PID bound. SEC8b resolves the capacity contract through the scope
exclusion below; SEC8c retains the atomic-deletion requirement. Completion
of the review is not security milestone approval. Resource request mapping
does not prove runtime resource enforcement.

## Policy selection and enforcement ownership

The [architecture guide](architecture.md) explains lifecycle and routing.
OpenShell enforces the submitted policy; the provider validates and translates
configuration. An explicit `policy` path or mapping is loaded and strictly
converted before gateway access, then embedded with command and service exposure
in the initial create. There is no create-first/apply-later window or fallback
to a broader policy when explicit input fails.

With `policy=None`, the adapter leaves the policy field absent and delegates
selection to OpenShell: image policy, then the runtime's restrictive default.
It does not automatically select `examples/policies/deny-all.yaml`. Review and
pin an image's baked policy before relying on that precedence. `policy_mode`
is proposed in SPEC and is not an implemented constructor argument.

The strict [policy examples](https://github.com/rodrigosetti/openenv-openshell/blob/main/examples/policies/README.md) request required
Landlock, explicit non-root identity, reviewed read-only paths, bounded writable
paths, and no undeclared egress. Paths/users must exist in the selected image
with suitable Unix permissions. A grant does not create paths or override file
ownership. The compatibility example uses best-effort Landlock and writable
workdir discovery, and omits an explicit non-root identity; it provides a
different posture. Configuration validity does not prove runtime enforcement.

The loader rejects unsupported fields/types, duplicate and merge keys, YAML
anchors/aliases, unsafe tags, nulls, and unsupported versions. YAML files are
limited to 1 MiB and mappings to 64 nesting levels. Strict conversion is an
offline schema check; gateway semantic acceptance, kernel support, and actual
denials require runtime evidence. A digest records normalized submitted fields,
not the effective image/default policy or proof of enforcement.

## Ingress, egress, and gateway access

SDK lifecycle traffic uses gateway credentials from the registered host-side
configuration. OpenEnv health and WebSocket traffic use an OpenShell-managed
service route. Sandbox outbound requests are separately governed by network
policy; publishing a service does not allow internet egress. Neither a reachable
gateway nor HTTP health proves WebSocket compatibility or authorization.

The local tested route requires no additional application credential. Remote
service authentication and trust remain unverified (S5a); gateway mTLS cannot
be assumed to authorize an OpenEnv service request. Service URLs must be absolute
HTTP(S) without embedded credentials, query parameters, or fragments. The
provider preserves path prefixes, avoids health redirects, and never disables
TLS verification or exposes a substitute Docker port. Validate both HTTP and
WebSocket use with an unmodified client before claiming remote support.

## Commands, labels, and cleanup ownership

Exact caller argv is supplied to the initial workload without interpolation or
an added shell. Argument metacharacters remain data unless the caller explicitly
chooses a shell. That shell's script and the workload remain trusted caller
configuration. Ordinary environment values and argv may contain secrets and
reach the workload even though request representations and public errors omit
them. Do not log raw configuration or SDK objects in application code.

Management labels identify the adapter but do not authorize deletion. Validation
rejects recognizable sensitive label keys; it cannot identify a secret hidden
under an innocuous key. Keep labels, names, image references, and metadata public
and free of prompts, credentials, or private task contents.

SEC8a rejects collision rollback, refuses deletion without a confirmed create
identity, and checks the current identity before the first delete. Cleanup
retries only confirm deletion of the original ID. Ambiguous creates require
operator inspection; failed deletion attempts may also require operator action
if confirmation keeps timing out. Errors and retry state remain sanitized.

The pinned API still deletes by name. A replacement after identity lookup can
be deleted before the identity-aware waiter runs; SEC8c tracks the required
atomic upstream operation. Reserve unique names and avoid reuse while this
limitation remains, without treating that practice as a guarantee. See
[cleanup behavior and limits](cleanup-tests.md#sec8a-mitigation-and-remaining-blocker).
`keep_sandbox=True` intentionally leaves workloads running, including after
failed startup, and releases local ownership; operators must remove retained
sandboxes. It does not retain or own operator-created credential providers.

## Process capacity and availability

The v0.1 security contract excludes a guaranteed sandbox-specific process/thread
budget on the local OpenShell 0.1.2 native VM lane. A hostile or accidental
process burst can exhaust guest capacity, interrupt the OpenEnv server or other
workloads sharing capacity, and consume host resources. Filesystem and network
enforcement do not establish availability isolation. CPU/memory/GPU serialization
also does not establish runtime enforcement. Operators requiring process capacity
isolation must independently validate an enforcing runtime/compute driver.
See [SPEC section 22.1](https://github.com/rodrigosetti/openenv-openshell/blob/main/SPEC.md#221-process-capacity-sec8b-scope-decision) and
the [evidence and scope decision](process-capacity.md).

Filesystem enforcement is exercised by [SEC5's runtime test](https://github.com/rodrigosetti/openenv-openshell/blob/main/tests/integration/test_filesystem_security.py).
It uses synthetic SSH/host-shadow canaries with an explicit readable control,
requires permission-denied errors under strict rules, checks workspace/temp
writes, and verifies continued use of the same OpenEnv WebSocket session.
See the [fixture build and run instructions](https://github.com/rodrigosetti/openenv-openshell/blob/main/tests/integration/README.md#sec5-filesystem-enforcement).
The canaries are guest image files; the test never reads real host credentials.

Prefer OpenShell provider-backed credentials for secrets. Use `env_vars` for
ordinary workload configuration, such as concurrency limits. Raw environment
values are readable by sandbox processes; request repr redaction and safe error
messages do not make those values secret inside the sandbox.

OpenShell manages credential material separately and gives workload processes
opaque environment placeholders. Its proxy resolves those references for
approved outbound requests. Credential attachment and network authorization
must both be configured; attaching a provider is not proof that a request is
allowed or that its credential scope is least privilege. Review the provider
profile's endpoints, methods, paths, and binary paths for the actual image.
See NVIDIA's [provider guide](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/docs/how-it-works/providers/overview.mdx)
and the [pinned 0.1.2 guide](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/docs/how-it-works/providers/overview.mdx).

## Configure credentials outside the workload

Create a provider in the target gateway/workspace before selecting its name.
The pinned 0.1.2 CLI requires a corresponding provider profile. Import a reviewed
profile first; upstream examples need adaptation to your image and intended
permissions. List available profiles with:

```bash
openshell provider list-profiles --workspace default
```

For a reviewed `github` profile, create an instance by looking up the credential
in the CLI's host environment:

```bash
# Set GITHUB_TOKEN using your host's secret-management workflow first.
openshell provider create --workspace default --name github-readonly \
  --type github --credential GITHUB_TOKEN
```

Passing only the environment key keeps the secret out of command arguments and
shell history. The name `github-readonly` does not enforce read-only access;
use a suitably scoped token and review the profile/policy restrictions. Never
put secret values into labels, image references, service URLs, or policy files.
Gateway lifecycle credentials are separate from workload provider credentials;
do not copy gateway credentials into the workload.

## Select provider instances explicitly

```python
from openenv_openshell import OpenShellProvider

provider = OpenShellProvider(
    workspace="default",
    providers=["github-readonly"],
)
# Ordinary start_container configuration (also supply exact command argv):
# env_vars={"MAX_CONCURRENT_ENVS": "8"}
```

`providers` contains existing **instance names**, not provider types, credential
values, or environment keys. Configuration copies the sequence to an immutable
tuple; request preparation and the adapter preserve its order in
`SandboxSpec.providers`. Omission/`None` and an empty sequence select no
providers. This package does not discover host secrets, create providers, infer
providers from images/environment variables, or substitute another provider.
Provider resolution and authorization belong to the gateway. Existing
non-empty-string validation remains in effect.

Configuration and create-request mapping are implemented and tested offline.
Public startup and cleanup are implemented, subject to the SEC8c atomic-deletion
limitation above. Provider provisioning is an operator action, separate from sandbox
cleanup; this package does not own or delete an operator's provider.

## SEC7 credential visibility check

The opt-in [runtime test](https://github.com/rodrigosetti/openenv-openshell/blob/main/tests/integration/test_managed_credentials.py)
creates a uniquely named provider profile and provider with a random synthetic
credential, then selects it through production request preparation and the
production adapter. The test supplies the validated image command through the production
`command` configuration and adapter mapping. P4 separately verifies provider
startup in `tests/integration/test_provider_startup.py`.

It captures a full environment print from the initial workload and from a new
exec process. Both must contain a present credential placeholder, contain no
synthetic secret anywhere in the captured output, and retain a readable
ordinary environment control. The routed EchoEnv health and reset/step/state
control must also pass. Cleanup checks sandbox absence after identity-aware
deletion and deletes the disposable provider and profile. Captured environment
and CLI output are not logged.

This demonstrates that managed material is not trivially printable through
those environment reads on the tested local SDK/gateway/image. It does not
prove resistance to every exfiltration technique, credential rewriting at an
endpoint, remote compatibility, or filesystem/network denial acceptance.
Run instructions and recorded evidence are in the
[integration guide](https://github.com/rodrigosetti/openenv-openshell/blob/main/tests/integration/README.md#sec7-managed-credential-visibility).

## Error and log redaction checks

[T5's offline tests](https://github.com/rodrigosetti/openenv-openshell/blob/main/tests/unit/test_secret_safety.py) exercise the public
provider through the production SDK adapter with synthetic credential, bearer
token, environment-value, and command-argument sentinels. They inspect public
exception messages, formatted tracebacks, rollback notes, and captured DEBUG
log records, including exception attachments. Coverage includes gateway health,
create/readiness failures, delete/deletion-wait/client-close failures, failed
rollback followed by retry, HTTP transport errors, and successful lifecycle
logging. Sensitive argv and environment still reach the intended workload.

These tests require no gateway and check package error/reporting behavior with
an SDK double. They do not establish that external SDK versions, application
log handlers, or sandbox processes redact secrets. Operational identifiers,
image references, labels, and service URLs must remain non-secret as described
above; raw environment values are readable inside the sandbox.

## Network enforcement checks

[SEC6's runtime tests](https://github.com/rodrigosetti/openenv-openshell/blob/main/tests/integration/test_network_security.py) compare
deny-by-default egress with one explicit HTTPS destination for the tested
image's Python interpreter. They require successful reads of each destination
under its allow policy, permission/proxy denials under deny policies, continued
reset/step/state over the same OpenEnv connection, and sandbox deletion.
An externally reachable environment does not grant its workload outbound access.
See the [run instructions and limits](https://github.com/rodrigosetti/openenv-openshell/blob/main/tests/integration/README.md#sec6-network-security).
