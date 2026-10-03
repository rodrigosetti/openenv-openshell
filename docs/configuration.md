# Configuration reference

`OpenShellProvider` is configured with keyword arguments. Construction validates
every value offline and never contacts a gateway; the gateway is first used by
`start_container()`. All names below are importable from `openenv_openshell`.

```python
from openenv_openshell import OpenShellProvider, OpenShellResources

provider = OpenShellProvider(
    sandbox_name="oe-train-0001",
    command=["sh", "-c", "cd /app/env && uvicorn server.app:app --host 0.0.0.0 --port 8000"],
    service_port=8000,
    policy="policy.yaml",
    labels={"openenv.run_id": "run-42"},
    providers=["huggingface"],
    resources=OpenShellResources(cpu=2, memory="4Gi"),
)
```

## Provider options

| Option | Default | Meaning |
| --- | --- | --- |
| `command` | `None` | **Required to start.** Exact workload argv for the image's server. See [command](#command). |
| `policy` | `None` | Explicit OpenShell policy: YAML path (`str`/`Path`) or mapping. `None` lets OpenShell choose the image or gateway default policy. See [policy](#policy). |
| `service_port` | `8000` | Guest port the server listens on; OpenShell exposes it as a managed service route. |
| `service_name` | `""` | Optional service name (lowercase letters, digits, hyphens). Empty uses the sandbox's unnamed service. |
| `sandbox_name` | generated | Generated and explicit names fit the 19-character OpenShell 0.1.2 gateway limit. Explicit names must use lowercase letters, digits, or hyphens and start/end with a letter or digit; longer names fail during construction before gateway access. |
| `workspace` | `"default"` | OpenShell workspace that owns the sandbox. Not read from `OPENSHELL_WORKSPACE`; pass it explicitly. |
| `gateway` | `None` | Registered gateway name. `None` uses `$OPENSHELL_GATEWAY`, then the CLI's active gateway. |
| `startup_timeout_s` | `120.0` | Budget for OpenShell to report the sandbox ready. |
| `deletion_timeout_s` | `60.0` | Budget to confirm the sandbox is gone after deletion. |
| `health_poll_interval_s` | `0.5` | Delay between `/health` probes. |
| `health_request_timeout_s` | `2.0` | Per-probe HTTP timeout, capped by the remaining budget. |
| `keep_sandbox` | `False` | Leave the sandbox running on stop/close (for debugging). You then delete it yourself. |
| `labels` | `{}` | Non-secret operational labels. See [labels](#labels). |
| `providers` | `()` | Names of existing OpenShell credential providers to attach. See [credentials](#credentials). |
| `resources` | `None` | `OpenShellResources(cpu=, memory=, gpu_count=)` requests. See [resources](#resources). |

Ports, timeouts, and resource values must be positive and finite. Invalid values
raise `ValueError` or `TypeError` at construction.

## `start_container` arguments

OpenEnv calls `provider.start_container(image, port=None, env_vars=None)`;
`from_docker_image(image, provider=..., port=..., env_vars=...)` forwards these.

- `image`: OCI reference or local image ID handed to OpenShell. Prefer an
  immutable reference; see [image guidance](images.md).
- `port`: overrides `service_port` for this start. It must match the workload's
  real listener.
- `env_vars`: environment for the initial workload, sent exactly as given.
  OpenShell 0.1.2 does not merge image `ENV`; pass what the server needs here.
  Values are readable by sandbox processes, so do not use this for secrets.

Unknown keyword arguments are rejected.

## Command

OpenShell 0.1.2 does not resolve OCI `ENTRYPOINT`, `CMD`, `WORKDIR`, or `ENV`.
Without a command it starts a login shell, so the server never runs. The
provider therefore requires `command` before it contacts the gateway:

- Pass a sequence of strings, not a single string. Argv is sent verbatim; there
  is no shell unless you invoke one (`["sh", "-c", "..."]`).
- Include ENTRYPOINT composition yourself and change into the server's directory
  in the command if it depends on one.
- Use an absolute path or a binary on the runtime's default `PATH`; the image's
  `PATH` is not guaranteed to apply.

Read the image's configuration to build the command:

```bash
docker image inspect <image> --format '{{json .Config.Entrypoint}} {{json .Config.Cmd}} {{.Config.WorkingDir}}'
```

Errors and `repr()` never include argv. See the
[startup decision](image-startup.md) for the upstream evidence.

## Policy

`policy` accepts a YAML path or a mapping in OpenShell 0.1.2's policy format.
It is loaded and validated before any gateway call and submitted atomically in
the create request, so the workload never runs without it.

```python
from openenv_openshell.policy import load_policy

load_policy("policy.yaml")  # offline validation, same as the provider uses
```

- `version: 1` is required. `filesystem_policy` is accepted as an alias for
  `filesystem`. Nested fields use exact snake_case SDK names. Network `tls`,
  `enforcement`, and `access` accept short spellings (`enforce`, `read_only`)
  or protobuf enum names.
- Unknown fields, wrong types, nulls, duplicate keys, anchors/aliases, unsafe
  tags, and multiple documents raise `PolicyConfigurationError`. Files are
  limited to 1 MiB and 64 nesting levels. Errors omit paths and contents.
- Nothing is added to your policy. An invalid explicit policy never falls back
  to the image or default policy.
- `provider.metadata.policy_digest` is the SHA-256 of the normalized submitted
  policy (sorted keys, compact JSON), so formatting and alias choices do not
  change it. It records what was submitted, not that it was enforced. It is
  `None` when no explicit policy was given.

Start from [the policy examples](https://github.com/rodrigosetti/openenv-openshell/blob/main/examples/policies/README.md): a strict
deny-all, a minimal Hugging Face read rule, and the image-compatible policy the
quickstart uses. The [security guide](security.md) explains precedence and what
is enforced.

## Labels

Labels are copied and validated at construction. Keys are at most 128
characters (`A-Za-z0-9._/-`); values are at most 256 characters, and spaces are
the only whitespace allowed. Keys that name secrets or private data (`token`,
`password`, `secret`, `credential`, `prompt`, `api-key`, `user-data`,
`task-content`) are rejected. The provider adds `managed-by=openenv-openshell` and
`openenv.provider=openshell`.

Never put tokens, prompts, task contents, or user data in labels.

## Credentials

Prefer OpenShell provider-backed credentials for secrets. `providers` names
credential providers that already exist in the workspace and attaches them to
the sandbox; it does not create them. Use `env_vars` only for ordinary
configuration: raw environment values are visible to every sandbox process even
though the provider redacts them from errors and representations. See
[configure credentials](security.md#configure-credentials-outside-the-workload).

## Resources

`OpenShellResources(cpu=2, memory="4Gi", gpu_count=1)` is passed through to
OpenShell. These are requests, not proof of enforcement. The local 0.1.2 VM
lane has no validated process (PID) limit; see the
[process-capacity scope](process-capacity.md).

## Environment variables

| Variable | Read by | Effect |
| --- | --- | --- |
| `OPENSHELL_GATEWAY` | OpenShell SDK | Gateway used when `gateway=None`. |
| `SSL_CERT_FILE` | HTTPX readiness probe | CA bundle that trusts a private gateway route certificate. Verification is never disabled. |
| `OPENENV_OPENSHELL_ECHO_IMAGE_ID` | quickstart, tests | EchoEnv image for `examples/quickstart.py` and the integration tests. |
| `OPENENV_OPENSHELL_CODING_IMAGE_ID` | demo | Image for `make demo`. |
| `OPENSHELL_WORKSPACE` | demo, tests | Workspace for the demo and integration tests (not the provider). |

## Lifecycle and cleanup

- `start_container()` creates the sandbox with command, policy, and service in
  one request, waits for OpenShell readiness, and returns the service URL. It
  refuses to start while it still owns a sandbox.
- On any startup failure it deletes what it created and raises the original,
  sanitized error. If that rollback fails, the exception carries a note telling
  you to call `stop_container()` again.
- `stop_container()` deletes the sandbox and waits until its original identity
  is gone. Repeated calls are harmless. Failures raise `SandboxDeletionError`
  and keep enough state to retry.
- `close()` and `with OpenShellProvider(...) as provider:` do the same. Entering
  the context does not start a sandbox.
- OpenEnv clients call `stop_container()` when the client closes and after a
  health timeout. If you call `start_container()` yourself, also stop the
  provider after readiness or connection failures.

## Readiness

`wait_for_ready(base_url, timeout_s=30.0)` polls `<base_url>/health` until HTTP
200 and sets `provider.state.ready`. Non-200 responses and transport errors are
retried; redirects are not followed and the body is not read. TLS failures that
retrying cannot fix (untrusted route certificate, required client certificate)
raise `ServiceAccessError` at once. Timeouts raise `OpenEnvReadinessTimeout`
without the URL. HTTP health does not prove the WebSocket works.

## Run metadata

`provider.metadata` is `None` until creation returns a service route, then an
immutable `OpenShellRunMetadata`: sandbox name and ID, workspace, image, service
URL, policy digest, UTC created/ready/deleted times, and installed provider,
OpenShell SDK, and OpenEnv versions. It survives cleanup and is replaced on the
next start. It never contains command, environment, credentials, or policy
contents. `image` is the reference you passed, so pin it to record exactly what
ran.

## Errors

All provider errors derive from `OpenShellProviderError` and carry fixed,
secret-safe messages; raw SDK text is never included.

| Exception | Raised when |
| --- | --- |
| `ValueError` / `TypeError` | Invalid configuration, missing `command`, unknown start options |
| `PolicyConfigurationError` | The explicit policy cannot be loaded or validated |
| `OpenShellConnectionError` | The gateway cannot be reached or authenticated |
| `SandboxCreationError` | The gateway rejected the create request or returned no service route |
| `SandboxReadinessError` | The sandbox did not become ready (failed to boot, workload crashed, timeout) |
| `OpenEnvReadinessTimeout` | `/health` did not return 200 in time |
| `ServiceAccessError` | TLS rejects the route in a way the OpenEnv client cannot satisfy |
| `SandboxDeletionError` | Deletion or confirmation failed; call `stop_container()` again |

See [troubleshooting](troubleshooting.md) for causes and fixes.

## Logging

Lifecycle events go to the standard `logging` logger `openenv_openshell`
(INFO for transitions, WARNING for cleanup failures). Messages are fixed event
names without argv, environment, policy, routes, or SDK errors. Configure
handlers in your application:

```python
import logging

logging.basicConfig(level=logging.INFO)
```
