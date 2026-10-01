# M1 provider acceptance

M1 verifies the provider milestone in SPEC.md sections 11–17, 32, and 38.
Its gate requires an existing OpenEnv client, lifecycle unit coverage above 90%,
cleanup for startup failure paths, and a passing `make check`.

## Acceptance evidence

| Requirement | Evidence |
| --- | --- |
| Implements the OpenEnv provider contract | `tests/unit/test_package.py` checks the upstream `ContainerProvider` type; the public factory tests exercise `start_container`, `wait_for_ready`, and `stop_container`. |
| Existing client works without source changes | `tests/integration/test_openenv_client.py` uses installed OpenEnv 0.6.0 `GenericEnvClient.from_docker_image` in async and synchronous modes. Both modes exercise routed HTTP health, WebSocket connection, two reset episodes, four echo steps, state, context close, deletion metadata, and independent SDK sandbox absence. |
| Lifecycle unit coverage exceeds 90% | `make check` enforces package branch-inclusive coverage of at least 95%; the acceptance run covered all 178 statements and 44 branches in `provider.py` (100%). |
| Startup failures clean up | `test_provider_startup.py` injects a lost create response, missing route, readiness failure, and health timeout against the real adapter. Confirmed-create failures clean up automatically. Since SEC8a, a lost response requires operator inspection; that test uses its captured transport identity for explicit cleanup and verifies absence. Health timeout requires caller cleanup; the unmodified client invokes it automatically. |
| Cleanup remains safe and retryable | Offline tests cover partial initialization, unknown-identity refusal, malformed routes, HTTP failures, WebSocket connection failure, deletion/wait/client-close failures, repeated stop/close, context errors, and explicit debug retention. See [cleanup regression coverage](cleanup-tests.md). |
| Applicable quality checks pass | `make check` runs Ruff formatting/lint, strict Pyright, and the hermetic unit suite. Runtime checks run separately with `--no-cov` so they do not replace the unit coverage gate. |

## Reproduce the gate

Verified September 30, 2026 on Python 3.11.8 with OpenEnv 0.6.0 and local
SDK/gateway 0.1.2: `make check` passed Ruff, strict Pyright (zero errors or
warnings), and 416 unit tests. Package branch-inclusive coverage was 99.50%;
provider coverage was 100%. All 12 selected integration cases passed in 118.83
seconds, with no skips. Independent SDK absence checks passed for every runtime
sandbox, including the failed-start cases.

Prepare the existing local gateway and validated arm64 EchoEnv image using the
[local setup](local-openshell-testing.md) and [image guide](echo-env-image.md).
Then run from the repository root:

```bash
make check
uv run coverage report --include='src/openenv_openshell/provider.py'
OPENENV_OPENSHELL_ECHO_IMAGE_ID="$(cat tests/integration/images/echo/local-image-id.txt)" \
  uv run pytest -m integration --no-cov \
  tests/integration/test_openenv_client.py \
  tests/integration/test_provider_startup.py \
  tests/integration/test_http_readiness.py -v
```

The runtime selection covers both unmodified client modes, four healthy provider
cleanup paths, four startup/health failures, and two loopback HTTP readiness
tests. An unset image variable skips gateway tests and cannot establish M1 runtime
acceptance. Failed deletion remains an explicit failure; fallback teardown must
not substitute for the client-close assertions.

## Scope

This gate covers the pinned OpenEnv 0.6.0 and SDK/gateway 0.1.2 on the local native
Apple Silicon VM lane, using caller-supplied exact argv and explicit image policy.
The checked-in image ID is a local Docker configuration identity. It does not
establish a pullable registry digest, arbitrary image or driver compatibility,
remote service authentication, long idle sessions, or reconnect behavior.

M2 retains filesystem/network denial acceptance (SEC5/SEC6). I2 retains the wider
EchoEnv suite using the reusable I1 fixture. S5a recorded remote results in
[protocol evidence](protocol-spike.md#remote-gateway-validation-s5a-2026-09-30). M3
public release acceptance is separate from this local provider milestone.
