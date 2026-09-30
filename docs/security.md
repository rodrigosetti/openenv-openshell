# Credentials and provider selection

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
# Ordinary start_container configuration, once startup is implemented:
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
Public `start_container()` is implemented; `stop_container()` remains pending
P6, so this example does not claim a complete public client lifecycle. Provider provisioning is an operator action, separate from sandbox
cleanup; this package does not own or delete an operator's provider.

## SEC7 credential visibility check

The opt-in [runtime test](../tests/integration/test_managed_credentials.py)
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
[integration guide](../tests/integration/README.md#sec7-managed-credential-visibility).
