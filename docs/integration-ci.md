# Gated OpenShell integration CI

`.github/workflows/integration.yml` is manual (`workflow_dispatch`), separate
from Quality. It runs the I2 async/sync EchoEnv cases, SEC5 filesystem control,
and both SEC6 network cases sequentially. Push and pull request events do not
start it. The hosted gate job explains why runtime work is skipped when the
repository variable `OPENENV_OPENSHELL_CI_ENABLED` is not exactly `true`, or the
dispatch is not on `rodrigosetti/openenv-openshell` main. Disabled runs do not
queue a self-hosted job. Once enabled, missing configuration or unavailable
runtime capabilities fail, rather than silently skip acceptance tests.

## Provision before enabling

Use a dedicated self-hosted macOS ARM64 runner with labels `self-hosted`,
`macOS`, `ARM64`, and `openshell-0.1.2`. This targets the locally validated native
VM lane; the custom label is an operator capability assertion, not proof that
any arbitrary runner supports OpenShell. The workflow does not install or
restart a gateway, create cloud infrastructure, or build/publish images.

1. Follow [local runtime setup](local-openshell-testing.md). Under the runner
   service account, register an OpenShell 0.1.2 gateway and ensure SDK mTLS
   credentials, workspace access, compute capacity, service DNS/routing, and
   certificate trust work. Keep credentials in that account's OpenShell store;
   never put them in workflow variables or image environment. Use a dedicated
   gateway/workspace with no unrelated workloads or production credentials.
2. Build the [validated EchoEnv image](echo-env-image.md) and the synthetic SEC5
   canary image using [integration setup](../tests/integration/README.md).
   Confirm architecture, exact argv, policy paths, required utilities, and image
   availability for this compute driver. The checked-in local Docker image ID
   cannot be assumed present on a different host. SEC6 needs working gateway
   internet access to `huggingface.co` and `example.com`, with TLS verification.
3. Create the `openshell-integration` GitHub environment, restrict its deployment
   branch to main, and configure required reviewers where available. Only
   trusted main code may use this runner. Restrict the runner's access to this
   repository; do not use it for pull request jobs. GitHub environments do not
   isolate self-hosted runner processes; see the
   [GitHub environment documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments).
4. Set these **environment variables in GitHub Settings**, not secrets:
   `OPENSHELL_GATEWAY` (registered gateway name), `OPENSHELL_WORKSPACE` (optional,
   defaults to `default`),
   `OPENENV_OPENSHELL_ECHO_IMAGE_ID`, `OPENENV_OPENSHELL_FILESYSTEM_IMAGE_ID`, and
   `OPENENV_OPENSHELL_NETWORK_IMAGE_ID`. Use the compatible EchoEnv image for
   the echo/network variables and the synthetic canary image for filesystem.
   Set the **repository** variable `OPENENV_OPENSHELL_CI_ENABLED=true` last;
   environment variables are not available to the hosted gate job.
5. Dispatch **OpenShell integration** on main. The workflow uses read-only
   repository permissions, no persisted checkout credentials, pinned actions,
   locked Python 3.11 dependencies, and no dependency cache on the runtime host.
   Runtime runs share one concurrency group and do not cancel an active run.
   An enabled run with no online matching runner queues until one is available;
   job execution timeouts do not bound time waiting in the queue. Disable the
   repository gate while the runner is offline.

## Local reproduction and diagnostics

With the gateway and three image variables set under the provisioned account
(workspace defaults to `default`):

```bash
uv sync --locked --all-groups
uv run python -m tests.integration._ci
```

The script checks all image opt-ins and an explicit gateway name before starting
pytest. The shared fixture then verifies SDK/gateway 0.1.2 and workspace access
before any provider startup. Failed image compatibility, route, protocol,
positive security control, or cleanup assertions fail their suite. Successful
pytest exit is accepted only with exactly 2/1/2 executed cases and no skips,
failures, or errors in the locally generated JUnit reports. Reports are temporary
and are not uploaded. Unit coverage remains enforced separately by `make check`.

Each suite has a 600-second wall-clock budget. On timeout the supervisor sends
SIGTERM to the subprocess group, allowing 180 seconds for fixture teardown,
then SIGKILL if necessary. A timed-out suite fails with exit 124 even if cleanup
succeeds. The workflow job has a 45-minute backstop, and dependency installation
has a 10-minute timeout. Cancellation is best effort: repeated interruption,
SIGKILL, host loss, and an unavailable gateway cannot guarantee cleanup.

Pytest `-rA --show-capture=all` exposes the fixture's **OpenShell E2E** sections
for passing and failing cases: generated sandbox names and fixed lifecycle flags,
plus sanitized cleanup failure messages. Inspect these sections in the runtime
step, particularly after an interruption. Independent absence checks remain in
the tests before fallback teardown, so fallback cleanup cannot hide a client
cleanup regression. Do not publish raw SDK/gateway dumps or guest environment.
For persistent cleanup failure or forced termination, use the reported name and
the setup guide to inspect the dedicated workspace and delete only confirmed
CI-owned sandboxes. Never bulk-delete unrelated workloads.

The workflow and local runner controls are validated without configuring GitHub
or registering a runner. A hosted execution must be recorded after the owner
provisions the environment and pushes the workflow. This CI lane does not
establish remote service support or close S5a/M3 acceptance.

Validated on 2026-09-30 through the exact local CI entry point with the registered
`openshell` gateway, SDK/gateway 0.1.2, and the native arm64 EchoEnv/SEC5 images:
all five cases passed (2 EchoEnv, 1 filesystem, 2 network), with independent
sandbox absence checks and visible sanitized teardown sections. Offline controls
verify missing-input rejection, incomplete/skipped/failed report rejection,
catchable timeout cleanup, and forced termination of an unresponsive child.
`make check` passed 424 unit tests, Ruff, strict Pyright, and 99.50% coverage;
actionlint 1.7.12 accepted the workflow and custom runner-label configuration.
