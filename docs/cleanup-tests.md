# Cleanup regression coverage

The offline tests exercise the production provider over the typed adapter fake.
They require no OpenShell CLI, installation, or gateway. `make check` runs them
with the rest of the unit suite, strict typing, linting, and coverage checks.

| SPEC.md sections 16–17 requirement | Regression coverage |
| --- | --- |
| Stop before start; repeated stop | `test_cleanup.py`: `test_stop_before_start_never_connects`, `test_stop_deletes_original_identity_and_allows_restart` |
| Sandbox already absent | `test_cleanup.py`: `test_partial_create_absence_without_identity`, `test_known_identity_is_verified_even_after_terminal_acknowledgement` |
| Debug retention (`keep_sandbox`) | `test_cleanup.py`: `test_keep_sandbox_releases_ownership_without_deletion`, `test_keep_mode_close_failure_is_retryable_without_deleting`, `test_keep_partial_state_needs_no_connection` |
| Partial state and lost create response | `test_cleanup.py`: `test_uncertain_deletion_without_identity_retains_ownership`, `test_recovered_identity_survives_timeout_and_changed_acknowledgement`, `test_cleanup_client_without_sandbox` |
| Delete, deletion-wait, or client-close failure | `test_cleanup.py`: `test_cleanup_failure_is_safe_and_retryable`, `test_cleanup_connection_failure_retains_partial_state` |
| Failed startup rollback and cleanup retry | `test_start_container.py`: `test_rollback_failure_reports_safe_note_and_public_retry`, `test_state_update_failure_rolls_back`; `test_cleanup.py`: `test_keep_mode_close_failure_is_retryable_without_deleting` |
| Unhealthy server followed by caller cleanup | `test_readiness.py`: `test_owned_health_timeout_public_cleanup` |
| Public close and provider context exit | `test_close.py`: normal/error exits, keep mode, cleanup failures, and failed-start retry |

Test files are in [tests/unit](https://github.com/rodrigosetti/openenv-openshell/tree/main/tests/unit). A known sandbox identity remains
the deletion-wait target even when the delete acknowledgement reports absence
or omits its identity. With no identity, only an explicit terminal outcome
confirms absence. Failed cleanup retains ownership for retry; a client-close
failure after confirmed deletion must not repeat deletion. In keep mode, even
failed-start rollback and retries must avoid both delete and deletion-wait calls.

The separate [runtime checks](https://github.com/rodrigosetti/openenv-openshell/blob/main/tests/integration/README.md#p7-failed-start-cleanup)
exercise local routed workloads and independently check sandbox absence. Offline
coverage does not establish remote gateway behavior or policy enforcement.
