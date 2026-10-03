# Cleanup regression coverage

The offline tests exercise the production provider over the typed adapter fake
and the production SDK adapter over a stateful SDK fake. They require no
OpenShell CLI or gateway. `make check` runs them
with the rest of the unit suite, strict typing, linting, and coverage checks.

| SPEC.md sections 16–17 requirement | Regression coverage |
| --- | --- |
| Stop before start; repeated stop | `test_cleanup.py`: `test_stop_before_start_never_connects`, `test_stop_deletes_original_identity_and_allows_restart` |
| Sandbox already absent | `test_cleanup.py`: `test_partial_create_absence_without_identity`, `test_known_identity_is_verified_even_after_terminal_acknowledgement` |
| Debug retention (`keep_sandbox`) | `test_cleanup.py`: `test_keep_sandbox_releases_ownership_without_deletion`, `test_keep_mode_close_failure_is_retryable_without_deleting`, `test_keep_partial_state_needs_no_connection` |
| Partial state and lost create response | `test_cleanup.py`: `test_uncertain_deletion_without_identity_retains_ownership`, `test_unknown_create_never_deletes_by_name`, `test_cleanup_client_without_sandbox` |
| Ownership lookup failure before delete | `test_cleanup_sdk.py`: transient recovery, persistent failure, replacement and NOT_FOUND on retry |
| Delete, deletion-wait, or client-close failure | `test_cleanup.py`: `test_cleanup_failure_is_safe_and_retryable`, `test_cleanup_connection_failure_retains_partial_state` |
| Failed startup rollback and cleanup retry | `test_start_container.py`: `test_rollback_failure_reports_safe_note_and_public_retry`, `test_state_update_failure_rolls_back`; `test_cleanup.py`: `test_keep_mode_close_failure_is_retryable_without_deleting` |
| Catchable startup interruptions | `test_startup_failures.py`: direct service/readiness interruptions, original exception propagation, failed/interrupted cleanup retry, keep mode, and unknown-create refusal |
| Unhealthy server followed by caller cleanup | `test_readiness.py`: `test_owned_health_timeout_public_cleanup` |
| Public close and provider context exit | `test_close.py`: normal/error exits, keep mode, cleanup failures, and failed-start retry |

Test files are in [tests/unit](https://github.com/rodrigosetti/openenv-openshell/tree/main/tests/unit). A known sandbox identity remains
the deletion-wait target even when the delete acknowledgement reports absence
or omits its identity. With no create identity, cleanup refuses to delete and
retains the attempted name for operator inspection. Failed cleanup retains
state for confirmation retry; a client-close failure after confirmed deletion
must not repeat deletion. In keep mode, even
failed-start rollback and retries must avoid both delete and deletion-wait calls.

The separate [runtime checks](https://github.com/rodrigosetti/openenv-openshell/blob/main/tests/integration/README.md#p7-failed-start-cleanup)
exercise local routed workloads and independently check sandbox absence. Offline
coverage does not establish remote gateway behavior or policy enforcement.

Catchable interruptions in `start_container()` run best-effort rollback before
re-raising the original exception. Cleanup uses the configured deletion timeout;
another cleanup failure or interruption adds a fixed retry note and retains
ownership. With `keep_sandbox`, rollback releases local ownership and the client
without deletion. If create was interrupted before returning an identity,
automatic cleanup refuses deletion and retains the attempted name for inspection.
Uncatchable process termination cannot run Python cleanup. Cancellation after
startup returns, while OpenEnv connects its WebSocket, remains a separate client
lifecycle issue (`openenv-openshell-iru`).

`test_provider_startup.py::test_interrupted_start_cleanup` injects an interruption
at service lookup or readiness after a real create. It checks provider deletion
and independently lists the runtime before the test's safety teardown, so teardown
cannot supply the behavior being tested.

Validated on 2026-10-03 against the local OpenShell SDK/gateway 0.1.2 and pinned
native arm64 EchoEnv image: all ten `test_provider_startup.py` controls passed,
including both direct interruption cases and independent absence checks (74.07
seconds). `make check` passed 478 offline tests, Ruff, strict Pyright, and 99.54%
branch-inclusive coverage. This evidence covers startup interruptions; it does
not resolve the separate OpenEnv factory cancellation gap or SEC8c atomic deletion.

## SEC8a mitigation and remaining blocker

A create RPC returning `ALREADY_EXISTS` is a collision, not partial ownership.
The provider closes its client without deleting or waiting on that name. Other
create failures may have lost a response; cleanup cannot infer ownership from
name, managed labels, or a delete response. Inspect the attempted name in
`provider.state.sandbox_name` through the gateway before any operator action.
Unknown ownership is retained and automatic deletion is refused. `keep_sandbox`
still explicitly relinquishes local state and closes the client.

For a successful create, the adapter checks the current ID with public `get()`
before its first name-based delete. Absence or a different ID means the owned
identity has gone; the replacement is left untouched. Lookup failures prevent
deletion and raise the private `DeleteNotSentError`, proving no delete RPC was
dispatched. Cleanup retains ownership and retries that preflight on the next
call; a newly observed replacement or absence prevents deletion. All other
delete failures remain ambiguous. After a delete RPC may have been dispatched,
including a lost response, provider retries only
`wait_deleted(expected_sandbox_id=original_id)`, never another delete RPC.
If the delete RPC was rejected or its dispatch cannot be determined, confirmation
may time out; an operator must inspect the original identity before removing it. Successfully
created workloads with subsequent service/readiness failure still get cleanup.

These are mitigations, **not atomic identity-safe deletion**. In OpenShell 0.1.2,
[`DeleteSandboxRequest`](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/proto/openshell.proto)
has name/workspace/allow-missing fields but no expected ID. The
[gateway handler](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/crates/openshell-server/src/grpc/sandbox.rs)
resolves the name again when deletion begins. A replacement between the client
preflight and that resolution can still be deleted. A client lock, labels,
random name, or identity-aware post-delete wait cannot close this gap.

On 2026-09-30, the user approved merging the SEC8a mitigations and tracking the
remaining atomic-deletion requirement separately as **SEC8c**
(`openenv-openshell-sec8c`). SEC8c remains blocked until a reviewed public
SDK/gateway contract supports atomic conditional deletion or an immutable-ID
delete target. It retains a direct M2 dependency, so mitigation completion does
not imply acceptance of the full security guarantee. This requires an upstream
capability and a deliberate update to the pinned compatibility boundary.

The stateful SDK tests in `tests/unit/test_cleanup_sdk.py` exercise provider and
production adapter together: transient/persistent lookup failure, replacement
or NOT_FOUND on retry, and lost delete replies with or without applied deletion.
Their waiter succeeds only when the original identity is actually absent.
`test_preflight_failure_recovers_and_deletes_owned_sandbox` injects one lookup
failure against a disposable runtime workload, then confirms recovery and
independent gateway absence.

Offline regression coverage includes collision classification, unknown create
ownership, lookup failures/replacements, and confirmation-only retries. The
opt-in `tests/integration/test_cleanup_ownership.py` creates only disposable
owned sandboxes: a collision must preserve the first workload; a stale identity
must preserve its replacement. These controls do not establish atomicity under
concurrent name reuse.

Validation on the local OpenShell 0.1.2 gateway (2026-09-30): `make check`
passed 421 offline tests, lint, and strict typing with 99.53% coverage. The two
disposable ownership controls passed. Nine existing startup/client controls
passed; the lost-create-response control passed after its expectation was
updated to refuse automatic cleanup and use its test-captured identity for
explicit cleanup. The sandbox left by the old expectation was identified by
its exact test name/ID and removed with absence independently confirmed.

After integration with the advanced local `main`, `make check` passed 462
offline tests, lint, and strict typing with 99.54% coverage. All 14 affected
local SDK/gateway 0.1.2 runtime controls passed together in 157.02 seconds:
collision and replacement ownership, provider startup and failure cleanup,
unmodified async/sync OpenEnv clients, policy-before-execution, and managed
credential cleanup. SEC8a is complete under the approved mitigation scope;
SEC8c remains blocked on the upstream atomic-deletion capability.

The `openenv-openshell-jnj` preflight-retry repair was verified on 2026-10-03:
`make check` passed 474 unit tests, Ruff, strict Pyright, and 99.54% coverage.
All 11 local SDK/gateway 0.1.2 controls in `test_cleanup_ownership.py` and
`test_provider_startup.py` passed in 111.63 seconds. The new lookup-failure
control confirmed that the workload remained healthy after the failed preflight,
then recovered on cleanup retry and independently confirmed sandbox absence.
