# Cleanup regression coverage

The offline tests exercise the production provider over the typed adapter fake.
They require no OpenShell CLI, installation, or gateway. `make check` runs them
with the rest of the unit suite, strict typing, linting, and coverage checks.

| SPEC.md sections 16–17 requirement | Regression coverage |
| --- | --- |
| Stop before start; repeated stop | `test_cleanup.py`: `test_stop_before_start_never_connects`, `test_stop_deletes_original_identity_and_allows_restart` |
| Sandbox already absent | `test_cleanup.py`: `test_partial_create_absence_without_identity`, `test_known_identity_is_verified_even_after_terminal_acknowledgement` |
| Debug retention (`keep_sandbox`) | `test_cleanup.py`: `test_keep_sandbox_releases_ownership_without_deletion`, `test_keep_mode_close_failure_is_retryable_without_deleting`, `test_keep_partial_state_needs_no_connection` |
| Partial state and lost create response | `test_cleanup.py`: `test_uncertain_deletion_without_identity_retains_ownership`, `test_unknown_create_never_deletes_by_name`, `test_cleanup_client_without_sandbox` |
| Delete, deletion-wait, or client-close failure | `test_cleanup.py`: `test_cleanup_failure_is_safe_and_retryable`, `test_cleanup_connection_failure_retains_partial_state` |
| Failed startup rollback and cleanup retry | `test_start_container.py`: `test_rollback_failure_reports_safe_note_and_public_retry`, `test_state_update_failure_rolls_back`; `test_cleanup.py`: `test_keep_mode_close_failure_is_retryable_without_deleting` |
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

## SEC8a mitigation and remaining blocker

A create RPC returning `ALREADY_EXISTS` is a collision, not partial ownership.
The provider closes its client without deleting or waiting on that name. Other
create failures may have lost a response; cleanup cannot infer ownership from
name, managed labels, or a delete response. Inspect the attempted name in
`provider.state.sandbox_name` through the gateway before any operator action.
Unknown ownership is retained and automatic deletion is refused. `keep_sandbox`
still explicitly relinquishes local state and closes the client.

Unknown ownership does not require retaining an SDK connection. Startup rollback
best-effort closes the client and retains the attempted name, image, configured
workspace, and unconfirmed state. Subsequent `close()`/`stop_container()` calls
continue to raise a sanitized operator-inspection error without reconnecting,
deleting, waiting for deletion, marking absence, or enabling ordinary reuse.
If client closure fails, the next cleanup call retries it; a successful closure
is not repeated. `test_unknown_create_releases_client_with_retry` covers these
paths, including `keep_sandbox`, and
`test_disconnected_unknown_state_never_reconnects` covers disconnected state.
The runtime lost-create-response control uses a separate operator client with
its test-captured identity for explicit cleanup after provider client release.

For a successful create, the adapter checks the current ID with public `get()`
before its first name-based delete. Absence or a different ID means the owned
identity has gone; the replacement is left untouched. Lookup failures prevent
deletion. After any delete attempt, including a lost response, provider retries
only `wait_deleted(expected_sandbox_id=original_id)`, never another delete RPC.
If the initial request was rejected or never sent, confirmation may time out;
an operator must inspect the original identity before removing it. Successfully
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
