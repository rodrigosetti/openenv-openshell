"""Public cleanup ownership, identity, and retry contracts."""

from unittest.mock import patch

import pytest

from openenv_openshell import OpenShellProvider
from openenv_openshell.errors import SandboxCreationError, SandboxDeletionError
from openenv_openshell.metadata import ProviderState
from tests.fakes import (
    DeleteCall,
    FakeDeletion,
    FakeOperation,
    FakeSandboxAdapter,
    WaitDeletedCall,
)


def owned_provider(adapter: FakeSandboxAdapter) -> OpenShellProvider:
    """Start a real provider over the offline boundary."""
    provider = OpenShellProvider(
        command=["server"],
        sandbox_name="owned",
        workspace="training",
        deletion_timeout_s=19,
    )
    with patch.object(provider, "_connect_adapter", return_value=adapter):
        provider.start_container("image")
    adapter.calls.clear()
    return provider


def test_stop_deletes_original_identity_and_allows_restart() -> None:
    """A different acknowledgement ID cannot change the original wait target."""
    adapter = FakeSandboxAdapter(delete_result=FakeDeletion("replacement"))
    provider = owned_provider(adapter)
    provider.state.ready = True
    provider.stop_container()
    provider.stop_container()
    assert adapter.calls == [
        DeleteCall("owned", "training"),
        WaitDeletedCall("owned", "training", "sandbox-123", 19),
    ]
    assert adapter.closed
    assert provider.state == ProviderState(deleted=True)
    replacement = FakeSandboxAdapter()
    with patch.object(provider, "_connect_adapter", return_value=replacement):
        provider.start_container("next-image")
    assert provider.state.created
    assert not provider.state.deleted


def test_keep_sandbox_releases_ownership_without_deletion() -> None:
    """Keeping the runtime closes client resources and permits another start."""
    adapter = FakeSandboxAdapter()
    provider = OpenShellProvider(command=["server"], keep_sandbox=True)
    with patch.object(provider, "_connect_adapter", return_value=adapter):
        provider.start_container("image")
    adapter.calls.clear()
    provider.stop_container()
    provider.stop_container()
    assert adapter.calls == []
    assert adapter.closed
    assert provider.state == ProviderState()


@pytest.mark.parametrize("operation", ["delete", "wait_deleted", "close"])
def test_cleanup_failure_is_safe_and_retryable(operation: FakeOperation) -> None:
    """Retries preserve ownership and never repeat confirmed deletion."""
    adapter = FakeSandboxAdapter()
    provider = owned_provider(adapter)
    adapter.failures[operation] = TimeoutError("private-token-secret")
    with pytest.raises(SandboxDeletionError, match="retry") as caught:
        provider.stop_container()
    assert "private-token-secret" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__
    assert provider.state.sandbox_name == "owned"
    assert provider.state.deleted == (operation == "close")
    adapter.failures.clear()
    previous_calls = list(adapter.calls)
    provider.stop_container()
    assert provider.state == ProviderState(deleted=True)
    assert adapter.closed
    if operation == "close":
        assert adapter.calls == previous_calls


@pytest.mark.parametrize("outcome", ["completed", "already_absent"])
def test_partial_create_absence_without_identity(outcome: str) -> None:
    """Confirmed absence clears pre-create ownership without an invented ID."""
    deletion = FakeDeletion(
        None, "completed" if outcome == "completed" else "already_absent"
    )
    adapter = FakeSandboxAdapter(delete_result=deletion)
    provider = OpenShellProvider()
    provider.state = ProviderState(sandbox_name="partial")
    with patch.object(provider, "_connect_adapter", return_value=adapter):
        provider.stop_container()
    assert adapter.calls == [DeleteCall("partial", "default")]
    assert provider.state == ProviderState(deleted=True)
    assert adapter.closed


@pytest.mark.parametrize("outcome", ["accepted", "unknown"])
def test_uncertain_deletion_without_identity_retains_ownership(outcome: str) -> None:
    """An acknowledgement alone cannot establish that the runtime is absent."""
    deletion = FakeDeletion(None, "accepted" if outcome == "accepted" else "unknown")
    adapter = FakeSandboxAdapter(delete_result=deletion)
    provider = OpenShellProvider()
    provider.state = ProviderState(sandbox_name="partial")
    with (
        patch.object(provider, "_connect_adapter", return_value=adapter),
        pytest.raises(SandboxDeletionError),
    ):
        provider.stop_container()
    assert not provider.state.deleted
    assert not adapter.closed
    adapter.delete_result = FakeDeletion("recovered")
    provider.stop_container()
    assert adapter.calls[-1] == WaitDeletedCall("partial", "default", "recovered", 60)
    assert provider.state == ProviderState(deleted=True)


def test_recovered_identity_survives_timeout_and_changed_acknowledgement() -> None:
    """Lost create responses recover an ID once and keep it across retries."""
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
    adapter.failures["wait_deleted"] = TimeoutError()
    with pytest.raises(SandboxDeletionError):
        provider.stop_container()
    assert provider.state.sandbox_id == "sandbox-123"
    adapter.failures.clear()
    adapter.delete_result = FakeDeletion("replacement")
    provider.stop_container()
    assert adapter.calls[-1] == WaitDeletedCall("partial", "default", "sandbox-123", 60)


def test_cleanup_connection_failure_retains_partial_state() -> None:
    """Disconnected partial state can reconnect and clean up on a later call."""
    provider = OpenShellProvider()
    provider.state = ProviderState(sandbox_name="partial", sandbox_id="original")
    with (
        patch.object(provider, "_connect_adapter", side_effect=RuntimeError("secret")),
        pytest.raises(SandboxDeletionError),
    ):
        provider.stop_container()
    assert provider.state.sandbox_id == "original"
    adapter = FakeSandboxAdapter()
    with patch.object(provider, "_connect_adapter", return_value=adapter):
        provider.stop_container()
    assert adapter.calls[-1] == WaitDeletedCall("partial", "default", "original", 60)


def test_keep_partial_state_needs_no_connection() -> None:
    """Keeping a runtime also handles ownership without a connected client."""
    provider = OpenShellProvider(keep_sandbox=True)
    provider.state = ProviderState(sandbox_name="partial")
    with patch.object(provider, "_connect_adapter", side_effect=AssertionError):
        provider.stop_container()
    assert provider.state == ProviderState()


def test_cleanup_client_without_sandbox() -> None:
    """An orphaned client is released even without a sandbox name."""
    adapter = FakeSandboxAdapter(
        failures={"create": RuntimeError(), "delete": RuntimeError()}
    )
    provider = OpenShellProvider(command=["server"])
    with (
        patch.object(provider, "_connect_adapter", return_value=adapter),
        pytest.raises(SandboxCreationError),
    ):
        provider.start_container("image")
    provider.state = ProviderState()
    adapter.failures.clear()
    adapter.calls.clear()
    provider.stop_container()
    assert adapter.closed
    assert adapter.calls == []
    assert provider.state == ProviderState()


def test_confirmed_deletion_without_client_needs_no_connection() -> None:
    """Prior confirmed deletion clears stale metadata without gateway access."""
    provider = OpenShellProvider()
    provider.state = ProviderState(sandbox_name="old", deleted=True)
    with patch.object(provider, "_connect_adapter", side_effect=AssertionError):
        provider.stop_container()
    assert provider.state == ProviderState(deleted=True)
