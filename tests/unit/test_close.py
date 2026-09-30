"""Close and inherited OpenEnv context-manager cleanup contracts."""

from unittest.mock import patch

import pytest

from openenv_openshell import OpenShellProvider
from openenv_openshell.errors import SandboxCreationError, SandboxDeletionError
from openenv_openshell.metadata import ProviderState
from tests.fakes import DeleteCall, FakeOperation, FakeSandboxAdapter, WaitDeletedCall
from tests.unit.test_cleanup import owned_provider


def test_close_before_start_and_empty_context_need_no_gateway() -> None:
    """Configuration-only use neither connects nor creates a sandbox."""
    provider = OpenShellProvider()
    with patch.object(provider, "_connect_adapter", side_effect=AssertionError):
        provider.close()
        with provider as entered:
            assert entered is provider
        provider.close()
    assert provider.state == ProviderState()


def test_close_deletes_and_releases_resources_idempotently() -> None:
    """Close and stop can be mixed without duplicating deletion."""
    adapter = FakeSandboxAdapter()
    provider = owned_provider(adapter)
    provider.close()
    provider.close()
    provider.stop_container()
    assert adapter.calls == [
        DeleteCall("owned", "training"),
        WaitDeletedCall("owned", "training", "sandbox-123", 19),
    ]
    assert adapter.closed
    assert provider.state == ProviderState(deleted=True)


@pytest.mark.parametrize("body_fails", [False, True])
@pytest.mark.parametrize("keep_sandbox", [False, True])
def test_context_exit_cleans_up_and_preserves_body_exception(
    *, body_fails: bool, keep_sandbox: bool
) -> None:
    """Both exit paths release the client and honor explicit retention."""
    adapter = FakeSandboxAdapter()
    provider = OpenShellProvider(command=["server"], keep_sandbox=keep_sandbox)
    body_error = RuntimeError("body failed")

    def run_context() -> None:
        with provider as entered:
            assert entered is provider
            entered.start_container("image")
            adapter.calls.clear()
            if body_fails:
                raise body_error

    with patch.object(provider, "_connect_adapter", return_value=adapter):
        if body_fails:
            with pytest.raises(RuntimeError) as caught:
                run_context()
            assert caught.value is body_error
        else:
            run_context()
    assert adapter.closed
    assert provider.state == ProviderState(deleted=not keep_sandbox)
    assert len(adapter.calls) == (0 if keep_sandbox else 2)
    provider.close()


@pytest.mark.parametrize("operation", ["delete", "wait_deleted", "close"])
@pytest.mark.parametrize("body_fails", [False, True])
def test_context_cleanup_failure_retains_ownership_for_close_retry(
    operation: FakeOperation, *, body_fails: bool
) -> None:
    """Failed exit is visible, sanitized, and retryable without losing identity."""
    adapter = FakeSandboxAdapter()
    provider = owned_provider(adapter)
    adapter.failures[operation] = RuntimeError("private-token-secret")
    body_error = ValueError("body failed")

    def run_context() -> None:
        with provider:
            if body_fails:
                raise body_error

    with pytest.raises(SandboxDeletionError) as caught:
        run_context()
    assert "private-token-secret" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__
    if body_fails:
        upstream_error = caught.value.__context__
        assert upstream_error is not None
        assert upstream_error.__context__ is body_error
    assert provider.state.sandbox_id == "sandbox-123"
    assert provider.state.deleted == (operation == "close")
    previous_calls = list(adapter.calls)
    adapter.failures.clear()
    provider.close()
    assert adapter.closed
    assert provider.state == ProviderState(deleted=True)
    if operation == "close":
        assert adapter.calls == previous_calls


def test_close_recovers_uncertain_failed_start() -> None:
    """Close retries a sandbox whose startup rollback could not delete it."""
    adapter = FakeSandboxAdapter(
        failures={"create": RuntimeError(), "delete": RuntimeError()}
    )
    provider = OpenShellProvider(command=["server"], sandbox_name="partial")
    with (
        patch.object(provider, "_connect_adapter", return_value=adapter),
        pytest.raises(SandboxCreationError),
    ):
        provider.start_container("image")
    adapter.failures.clear()
    provider.close()
    assert adapter.closed
    assert provider.state == ProviderState(deleted=True)
    assert adapter.calls[-1] == WaitDeletedCall("partial", "default", "sandbox-123", 60)
