# OpenEnv under OpenShell

Run Hugging Face OpenEnv environment servers inside NVIDIA OpenShell sandboxes,
with filesystem, network, and credential policies. `OpenShellProvider` implements
OpenEnv's `ContainerProvider`: existing clients and training loops keep their
normal reset, step, state, and close operations.

**Pre-alpha, installed from source.** The tested pair is OpenEnv **0.6.0** with
OpenShell SDK/gateway **0.1.2**. Start with the
[known limitations](getting-started.md#known-limitations), including cleanup
ownership and process-capacity risks, before relying on sandbox isolation.

## Run your first environment

1. Check [requirements and install from source](getting-started.md#requirements).
2. Set up the [local OpenShell gateway](local-openshell-testing.md).
3. Run the [validated EchoEnv quickstart](getting-started.md#quickstart).
4. Prepare [your environment image](images.md) and choose
   [provider configuration](configuration.md).
5. Review [policies and security](security.md), then try the
   [coding-agent demo](coding-agent-demo.md).

Commands in this manual run from the repository root. The validated local lane
uses native arm64 images on the VM driver. The compatibility guide distinguishes
that lane from the tested remote OIDC deployment and unsupported remote mTLS
service access.

## Find answers

Use Search to look up options, errors, and policy behavior.
[Troubleshooting](troubleshooting.md) starts with gateway, SDK, and image checks;
[compatibility](compatibility-matrix.md) records the exact supported versions.
Repository scripts, policies, Dockerfiles, and tests are linked to their GitHub
source so you can inspect the executable configuration.

## Engineering evidence

The Engineering reference section contains architecture, contracts, test results,
and historical experiments. Historical versions and proposals are evidence,
not additional support claims. The
[specification](https://github.com/rodrigosetti/openenv-openshell/blob/main/SPEC.md)
is the source of truth for requirements and milestone gates. See
[documentation contributions](documentation.md) to edit or preview this manual.
