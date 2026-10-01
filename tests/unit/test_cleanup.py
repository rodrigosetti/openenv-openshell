"""Public cleanup ownership, identity, and retry contracts."""

from typing import Literal
from unittest.mock import patch

import pytest

from openenv_openshell import OpenShellProvider
from openenv_openshell._adapter import CreateCollisionError
from openenv_openshell.errors import SandboxCreationError, SandboxDeletionError
from openenv_openshell.metadata import ProviderState
from tests.fakes import (
    DeleteCall,
    FakeDeletion,
    FakeOperation,
    FakeSandboxAdapter,
    WaitDeletedCall,
)


def test_stop_before_start_never_connects() -> None:
    """Repeated cleanup of a fresh provider must remain entirely local."""
    provider = OpenShellProvider()
    with patch.object(provider, "_connect_adapter") as connect:
        provider.stop_container()
        provider.stop_container()
    connect.assert_not_called()
    assert provider.state == ProviderState()
    assert provider.metadata is None


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


@pytest.mark.parametrize("outcome", ["completed", "already_absent"])
def test_known_identity_is_verified_even_after_terminal_acknowledgement(
    outcome: str,
) -> None:
    """An already-absent reply cannot bypass the original identity-safe wait."""
    adapter = FakeSandboxAdapter(
        delete_result=FakeDeletion(
            None, "completed" if outcome == "completed" else "already_absent"
        ),
    )
    provider = owned_provider(adapter)
    provider.stop_container()
    calls = list(adapter.calls)
    provider.stop_container()
    assert (
        adapter.calls
        == calls
        == [
            DeleteCall("owned", "training"),
            WaitDeletedCall("owned", "training", "sandbox-123", 19),
        ]
    )
    assert adapter.closed
    assert provider.state == ProviderState(deleted=True)
    assert provider.metadata is not None
    assert provider.metadata.deleted_at is not None


@pytest.mark.parametrize("failed_start", [False, True])
def test_keep_mode_close_failure_is_retryable_without_deleting(
    *,
    failed_start: bool,
) -> None:
    """Retention survives failed client closure during stop or startup rollback."""
    adapter = FakeSandboxAdapter(
        service_url=None if failed_start else "https://route.test",
    )
    provider = OpenShellProvider(
        command=["server"], sandbox_name="kept", keep_sandbox=True
    )
    with patch.object(provider, "_connect_adapter", return_value=adapter):
        if failed_start:
            adapter.failures["close"] = RuntimeError("private-close-detail")
            with pytest.raises(SandboxCreationError) as caught:
                provider.start_container("image")
            assert caught.value.__notes__ == [
                "OpenShell sandbox cleanup failed; call stop_container again to retry",
            ]
        else:
            provider.start_container("image")
            adapter.failures["close"] = RuntimeError("private-close-detail")
            with pytest.raises(SandboxDeletionError):
                provider.stop_container()
        assert provider.state.sandbox_name == "kept"
        assert provider.state.sandbox_id == "sandbox-123"
        assert not provider.state.deleted
        assert not adapter.closed
        with pytest.raises(RuntimeError, match="already owns"):
            provider.start_container("another-image")
    calls = list(adapter.calls)
    adapter.failures.clear()
    provider.stop_container()
    provider.stop_container()
    assert adapter.calls == calls
    assert not any(isinstance(call, DeleteCall) for call in calls)
    assert not any(isinstance(call, WaitDeletedCall) for call in calls)
    assert adapter.closed
    assert provider.state == ProviderState()
    if failed_start:
        assert provider.metadata is None
    else:
        assert provider.metadata is not None
        assert provider.metadata.deleted_at is None


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
def test_partial_create_absence_without_identity(
    outcome: Literal["completed", "already_absent"],
) -> None:
    """No deletion outcome can prove ownership before a delete is authorized."""
    adapter = FakeSandboxAdapter(delete_result=FakeDeletion(None, outcome))
    provider = OpenShellProvider()
    provider.state = ProviderState(sandbox_name="partial")
    with (
        patch.object(provider, "_connect_adapter", return_value=adapter),
        pytest.raises(SandboxDeletionError, match="operator"),
    ):
        provider.stop_container()
    assert adapter.calls == []
    assert not provider.state.deleted


@pytest.mark.parametrize("outcome", ["accepted", "unknown"])
def test_uncertain_deletion_without_identity_retains_ownership(
    outcome: Literal["accepted", "unknown"],
) -> None:
    """Unknown ownership cannot be recovered from a deletion acknowledgement."""
    adapter = FakeSandboxAdapter(delete_result=FakeDeletion(None, outcome))
    provider = OpenShellProvider()
    provider.state = ProviderState(sandbox_name="partial")
    with patch.object(provider, "_connect_adapter", return_value=adapter):
        for _ in range(2):
            with pytest.raises(SandboxDeletionError, match="operator"):
                provider.stop_container()
    assert adapter.calls == []
    assert not provider.state.deleted


def test_unknown_create_never_deletes_by_name() -> None:
    """A lost create response retains diagnosis without guessing ownership."""
    adapter = FakeSandboxAdapter(failures={"create": RuntimeError()})
    provider = OpenShellProvider(command=["server"], sandbox_name="partial")
    with (
        patch.object(provider, "_connect_adapter", return_value=adapter),
        pytest.raises(SandboxCreationError),
    ):
        provider.start_container("image")
    adapter.failures.clear()
    with pytest.raises(SandboxDeletionError, match="operator"):
        provider.stop_container()
    assert provider.state.sandbox_id is None
    assert not any(isinstance(call, DeleteCall) for call in adapter.calls)


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


def test_collision_closes_client_without_deleting_existing_sandbox() -> None:
    """Repeated rollback/cleanup after ALREADY_EXISTS stays entirely local."""
    adapter = FakeSandboxAdapter(failures={"create": CreateCollisionError("secret")})
    provider = OpenShellProvider(command=["server"], sandbox_name="existing")
    with (
        patch.object(provider, "_connect_adapter", return_value=adapter),
        pytest.raises(SandboxCreationError, match="already in use"),
    ):
        provider.start_container("image")
    provider.stop_container()
    assert [call.operation for call in adapter.calls] == ["create"]
    assert adapter.closed
    assert provider.state == ProviderState()


@pytest.mark.parametrize("failure", ["delete", "wait_deleted"])
def test_retry_only_waits_for_original_identity(failure: FakeOperation) -> None:
    """Even a lost delete acknowledgement must not trigger another delete RPC."""
    adapter = FakeSandboxAdapter()
    provider = owned_provider(adapter)
    adapter.failures[failure] = TimeoutError("secret")
    with pytest.raises(SandboxDeletionError):
        provider.stop_container()
    calls = list(adapter.calls)
    adapter.failures.clear()
    adapter.delete_result = FakeDeletion("replacement")
    provider.stop_container()
    assert adapter.calls[len(calls) :] == [
        WaitDeletedCall("owned", "training", "sandbox-123", 19)
    ]
    assert sum(isinstance(call, DeleteCall) for call in adapter.calls) == 1
