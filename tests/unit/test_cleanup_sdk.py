"""Provider cleanup retries over the production adapter and a stateful SDK fake."""

from dataclasses import dataclass, replace
from typing import cast
from unittest.mock import MagicMock, patch

import grpc
import pytest
from openshell import DeletionOutcome, DeletionResult, SandboxClient, SandboxRef

from openenv_openshell import OpenShellProvider
from openenv_openshell._sdk import SDKAdapter
from openenv_openshell.errors import SandboxDeletionError

DELETION_TIMEOUT = 19
RECOVERY_LOOKUPS = 2
PERSISTENT_LOOKUPS = 3


class MissingSandbox(grpc.RpcError):
    """Model the public get NOT_FOUND response without a runtime."""

    def code(self) -> grpc.StatusCode:
        """Return the absence status consumed by SDKAdapter."""
        return grpc.StatusCode.NOT_FOUND


@dataclass
class CleanupRuntime:
    """Deletion waiting succeeds only after the original identity disappears."""

    current: SandboxRef | None
    lookup_failures: int = 1
    lose_delete_reply: bool = False
    apply_delete: bool = True

    def get(self, _name: str, *, workspace: str) -> SandboxRef:
        """Fail preflight before returning the runtime's current identity."""
        assert workspace == "training"
        if self.lookup_failures:
            self.lookup_failures -= 1
            msg = "private-lookup-secret"
            raise OSError(msg)
        if self.current is None:
            raise MissingSandbox
        return self.current

    def delete(
        self, _name: str, *, workspace: str, allow_missing: bool
    ) -> DeletionResult:
        """Optionally apply deletion even when its reply is lost."""
        assert workspace == "training"
        assert allow_missing
        assert self.current is not None
        identity = self.current.id
        if self.apply_delete:
            self.current = None
        if self.lose_delete_reply:
            msg = "private-delete-secret"
            raise OSError(msg)
        return DeletionResult(DeletionOutcome.ACCEPTED, identity)

    def wait_deleted(
        self,
        _name: str,
        *,
        workspace: str,
        expected_sandbox_id: str,
        timeout_seconds: float,
    ) -> None:
        """Prevent a successful fake waiter from masking a missing delete."""
        assert workspace == "training"
        assert expected_sandbox_id == "sandbox-123"
        assert timeout_seconds == DELETION_TIMEOUT
        if self.current is not None and self.current.id == expected_sandbox_id:
            msg = "original sandbox still exists"
            raise TimeoutError(msg)


def cleanup_provider(sdk: MagicMock, runtime: CleanupRuntime) -> OpenShellProvider:
    """Preserve a successful create identity and use SDKAdapter for cleanup."""
    provider = OpenShellProvider(
        command=["server"],
        sandbox_name="owned",
        workspace="training",
        deletion_timeout_s=DELETION_TIMEOUT,
    )
    sdk.create.return_value = runtime.current
    sdk.wait_ready.return_value = runtime.current
    sdk.get.side_effect = runtime.get
    sdk.delete.side_effect = runtime.delete
    sdk.wait_deleted.side_effect = runtime.wait_deleted
    with patch.object(
        provider,
        "_connect_adapter",
        return_value=SDKAdapter(cast("SandboxClient", sdk)),
    ):
        provider.start_container("image")
        with pytest.raises(SandboxDeletionError, match="retry") as caught:
            provider.stop_container()
    assert "private" not in str(caught.value)
    assert caught.value.__suppress_context__
    assert provider.state.sandbox_id == "sandbox-123"
    assert not provider.state.deleted
    return provider


def test_transient_preflight_retries_first_delete(sdk: MagicMock) -> None:
    """A recovered lookup sends exactly one delete and confirms actual absence."""
    runtime = CleanupRuntime(replace(sdk.create.return_value, id="sandbox-123"))
    provider = cleanup_provider(sdk, runtime)
    sdk.delete.assert_not_called()
    sdk.wait_deleted.assert_not_called()
    provider.stop_container()
    provider.stop_container()
    assert runtime.current is None
    assert sdk.get.call_count == RECOVERY_LOOKUPS
    sdk.delete.assert_called_once_with(
        "owned", workspace="training", allow_missing=True
    )
    assert sdk.wait_deleted.call_count == 1
    sdk.close.assert_called_once_with()
    assert provider.state.deleted


def test_persistent_preflight_failure_never_deletes(sdk: MagicMock) -> None:
    """Every failed lookup retains ownership without claiming deletion started."""
    runtime = CleanupRuntime(
        replace(sdk.create.return_value, id="sandbox-123"),
        lookup_failures=PERSISTENT_LOOKUPS,
    )
    provider = cleanup_provider(sdk, runtime)
    for _ in range(2):
        with pytest.raises(SandboxDeletionError):
            provider.stop_container()
    assert sdk.get.call_count == PERSISTENT_LOOKUPS
    sdk.delete.assert_not_called()
    sdk.wait_deleted.assert_not_called()
    sdk.close.assert_not_called()
    assert provider.state.sandbox_id == "sandbox-123"


@pytest.mark.parametrize("replacement", [False, True])
def test_preflight_retry_preserves_replacement_or_absence(
    sdk: MagicMock, *, replacement: bool
) -> None:
    """A retry rechecks identity and never deletes an observed replacement."""
    runtime = CleanupRuntime(replace(sdk.create.return_value, id="sandbox-123"))
    provider = cleanup_provider(sdk, runtime)
    runtime.current = (
        replace(sdk.create.return_value, id="replacement") if replacement else None
    )
    provider.stop_container()
    assert sdk.get.call_count == RECOVERY_LOOKUPS
    sdk.delete.assert_not_called()
    assert sdk.wait_deleted.call_count == 1
    assert provider.state.deleted
    assert runtime.current is not None if replacement else runtime.current is None


@pytest.mark.parametrize("applied", [False, True])
def test_ambiguous_delete_never_repeats_rpc(sdk: MagicMock, *, applied: bool) -> None:
    """Lost replies stay confirmation-only even if deletion was never applied."""
    runtime = CleanupRuntime(
        replace(sdk.create.return_value, id="sandbox-123"),
        lookup_failures=0,
        lose_delete_reply=True,
        apply_delete=applied,
    )
    provider = cleanup_provider(sdk, runtime)
    if not applied:
        with pytest.raises(SandboxDeletionError):
            provider.stop_container()
        assert not provider.state.deleted
        runtime.current = None
    provider.stop_container()
    assert sdk.get.call_count == 1
    assert sdk.delete.call_count == 1
    assert sdk.wait_deleted.call_count == (1 if applied else 2)
    assert provider.state.deleted
