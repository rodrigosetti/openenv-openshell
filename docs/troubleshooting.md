# Troubleshooting

Provider errors are deliberately terse: they never include SDK text, argv,
environment, policy contents, or routes, because those can hold secrets. Use
OpenShell's own tools for detail.

## First checks

```bash
openshell status                                   # gateway reachable, version 0.1.2
openshell sandbox list --workspace default         # leftover sandboxes
openshell logs <sandbox-name> --since 10m          # gateway and sandbox logs
make openshell-smoke                               # driver + service routing (from a checkout)
```

To inspect a failing sandbox, construct the provider with `keep_sandbox=True`
and a known `sandbox_name`. The sandbox then survives cleanup; delete it
yourself afterwards with `openshell sandbox delete <name>`.

Enable lifecycle logging to see how far startup got (`sandbox.create.started`,
`sandbox.create.completed`, `service.exposed`, `sandbox.ready`, ...):

```python
import logging

logging.basicConfig(level=logging.INFO)
```

## Errors by symptom

### `ValueError: OpenShell 0.1.2 requires explicit command argv`

No `command` was configured. OpenShell does not run the image's `CMD`; pass the
server argv. See [command](configuration.md#command).

### `PolicyConfigurationError: Invalid explicit policy`

The policy failed offline validation, before any gateway call. Check it with:

```bash
uv run python -c 'from openenv_openshell.policy import load_policy; load_policy("policy.yaml")'
```

Common causes: missing `version: 1`, a misspelled field, YAML anchors, or both
`filesystem` and `filesystem_policy`. See [policy](configuration.md#policy).

### `OpenShellConnectionError`

The gateway is unreachable, unauthenticated, or the `gateway` name is not
registered. Run `openshell status`, check `OPENSHELL_GATEWAY` and the `gateway=`
argument, and confirm workspace access with `openshell sandbox list
--workspace <name>`. On macOS, `brew services restart openshell` restarts a
Homebrew gateway.

The provider also refuses to run with an OpenShell SDK other than 0.1.2. Install
the pinned wheel; see [installation](https://github.com/rodrigosetti/openenv-openshell/blob/main/README.md#install).

### `SandboxCreationError` on every start

The gateway rejected the create request. Generated default names fit the 0.1.2
gateway's **19-character** limit. If you set `sandbox_name`, keep it within that
limit and unique in the workspace.

Other causes: a name already in use in the workspace, a `providers` entry that
does not exist, or a policy the gateway rejects semantically (for example
deprecated `tls: terminate`). `openshell logs --source gateway` shows the
gateway's reason.

### `SandboxReadinessError`

The sandbox was created but never became ready within `startup_timeout_s`.
Look at `openshell logs <name>` with `keep_sandbox=True`. Usual causes:

- **Image not available to the driver.** A local image ID only works on the
  machine that built it; a registry image must be pullable by the gateway.
- **Wrong architecture.** amd64 images fail on the Apple Silicon VM lane.
- **Missing `iproute2`** in the image (VM driver).
- **Policy blocks the server.** A policy without read access to the server's
  code (for example `/app`) makes the workload exit. Grant the paths it needs.
- **Root image on the Docker driver.** Add a non-root `USER`; see
  [image requirements](images.md#make-the-image-runnable-under-openshell).
- **Slow first boot.** Pulling or unpacking a large image can take longer than
  the default 120 s; raise `startup_timeout_s`.

### `OpenEnvReadinessTimeout: OpenEnv health readiness timed out`

The sandbox is running but `/health` never returned 200. Check that:

- `service_port` (or the `port` argument) matches the port the server listens on;
- the server binds `0.0.0.0`, not `127.0.0.1`;
- the command actually starts the server (wrong directory, executable not on the
  runtime `PATH`, or missing `env_vars` make it exit); see
  [image requirements](images.md);
- the server has enough time; OpenEnv's own health timeout applies when using
  `from_docker_image`.

Brief `502` responses while the server boots are normal and retried.

### `ServiceAccessError`

The service route uses TLS the client cannot satisfy. Two messages:

- *route certificate is not trusted*: point `SSL_CERT_FILE` at a CA bundle that
  includes the gateway's CA.
- *route requires a TLS client certificate*: the gateway uses standard mTLS for
  service routes. Unmodified OpenEnv clients cannot present a client
  certificate, so this setup is **not supported**. Use a local gateway, or a
  gateway whose service routes do not require client certificates. The tested
  [S5b OIDC configuration](protocol-spike.md#oidc-remote-gateway-validation-s5b-2026-10-01)
  works, but its service routes are anonymous within the network boundary.
  Gateway OIDC authentication alone does not secure them.

### `SandboxDeletionError`

Deletion or confirmation failed. Call `provider.stop_container()` (or `close()`)
again to retry confirmation of the original identity. After a deletion attempt,
retries do not send another delete request. If confirmation keeps timing out,
an operator must verify ownership before removing the sandbox.

If create returned no identity, automatic deletion is refused. Inspect
`provider.state.sandbox_name` and gateway records; the attempted name alone does
not establish ownership. Once ownership is independently confirmed, remove the
sandbox and check the list:

```bash
openshell sandbox delete --workspace default <name>
openshell sandbox list --workspace default
```

Only delete sandboxes you own: deleting by name can remove a different sandbox
that reused the name (see the [cleanup ownership finding](security-review.md#cleanup-blast-radius)).

## Other problems

**The policy seems not to apply.** `policy_digest` records what was submitted,
not enforcement. Landlock `best_effort` (used by the image-compatible example)
may degrade when the runtime cannot enforce Landlock; use `hard_requirement` to fail
instead. See the [security guide](security.md).

**Network requests from the sandbox fail.** Policies declare no egress unless
you add `network_policies` rules for the exact binary, host, and port. Inbound
service routing does not need an egress rule.

**`make demo` or the quickstart says to set an image variable.** Build the image
and export its ID as shown in the [README](https://github.com/rodrigosetti/openenv-openshell/blob/main/README.md#quickstart).

**`uv sync` cannot install `openshell`.** The SDK is installed from its official
release wheel, not PyPI's unrelated `openshell` package; see
[installation](https://github.com/rodrigosetti/openenv-openshell/blob/main/README.md#install).

## Reporting issues

Include the output of `openshell status`, the provider, OpenShell SDK, and
OpenEnv versions from `provider.metadata`, the compute driver, the image
reference, and the exception type. Remove tokens, prompts, and private paths
from logs before sharing.
