"""Offline failure and identity contracts for the isolated S4 experiment."""

from dataclasses import replace
from unittest.mock import MagicMock

import pytest
from openshell import DeletionOutcome, DeletionResult, ServiceExposure

from tests.integration._lifecycle_spike import SpikeError, run_spike

MAX_NAME_LENGTH = 19
IMAGE = "sha256:" + "a" * 64


def test_spike_success(sdk: MagicMock) -> None:
    """Persist the create route, use atomic exposure and verify original deletion."""
    assert run_spike(sdk, image=IMAGE, workspace="default") == "https://route.test"
    args = sdk.create.call_args.kwargs
    assert args["service_exposures"] == [ServiceExposure(target_port=8000)]
    assert args["spec"].template.image == IMAGE
    assert not args["spec"].command
    assert "/app" in args["spec"].policy.filesystem.read_only
    assert not args["spec"].policy.network_policies
    assert len(args["name"]) <= MAX_NAME_LENGTH
    assert [call[0] for call in sdk.mock_calls] == [
        "health",
        "create",
        "wait_ready",
        "delete",
        "wait_deleted",
    ]
    assert sdk.wait_deleted.call_args.kwargs["expected_sandbox_id"] == "identity"
    sdk.close.assert_not_called()


@pytest.mark.parametrize("stage", ["create", "wait_ready"])
@pytest.mark.parametrize("failure", [RuntimeError("private"), KeyboardInterrupt()])
def test_failure_cleanup(sdk: MagicMock, stage: str, failure: BaseException) -> None:
    """Delete even after lost create responses or startup interruption."""
    getattr(sdk, stage).side_effect = failure
    with pytest.raises(type(failure)) as caught:
        run_spike(sdk, image=IMAGE, workspace="default")
    assert caught.value is failure
    sdk.delete.assert_called_once()
    assert sdk.wait_deleted.call_args.kwargs["expected_sandbox_id"] == "identity"


@pytest.mark.parametrize(
    "url", [None, "ftp://route.test", "https://user:secret@route.test"]
)
def test_bad_route_cleanup(sdk: MagicMock, url: str | None) -> None:
    """A missing or unsafe route cannot bypass cleanup."""
    sdk.create.return_value = replace(
        sdk.create.return_value, service_urls={} if url is None else {"": url}
    )
    with pytest.raises(SpikeError):
        run_spike(sdk, image=IMAGE, workspace="default")
    sdk.delete.assert_called_once()
    sdk.wait_ready.assert_not_called()


def test_cleanup_failure_preserves_primary(sdk: MagicMock) -> None:
    """A cleanup error must not mask a startup error."""
    failure = RuntimeError("primary")
    sdk.wait_ready.side_effect = failure
    sdk.delete.side_effect = RuntimeError("cleanup")
    with pytest.raises(RuntimeError) as caught:
        run_spike(sdk, image=IMAGE, workspace="default")
    assert caught.value is failure
    assert "cleanup also failed" in failure.__notes__[0]


def test_cleanup_failure_fails_success(sdk: MagicMock) -> None:
    """A successful startup is insufficient if deletion cannot be confirmed."""
    sdk.wait_deleted.side_effect = RuntimeError("private")
    with pytest.raises(SpikeError, match="cleanup failed"):
        run_spike(sdk, image=IMAGE, workspace="default")


def test_uncertain_create_cleanup(sdk: MagicMock) -> None:
    """An accepted deletion without identity does not imply absence."""
    failure = RuntimeError("lost response")
    sdk.create.side_effect = failure
    sdk.delete.return_value = DeletionResult(DeletionOutcome.ACCEPTED, None)
    with pytest.raises(RuntimeError) as caught:
        run_spike(sdk, image=IMAGE, workspace="default")
    assert caught.value is failure
    assert failure.__notes__
    sdk.wait_deleted.assert_not_called()


def test_preflight(sdk: MagicMock) -> None:
    """Reject invalid inputs and gateway mismatch before mutation."""
    with pytest.raises(SpikeError, match="immutable"):
        run_spike(sdk, image="latest", workspace="default")
    sdk.health.assert_not_called()
    sdk.health.return_value.version = "0.0.116"
    with pytest.raises(SpikeError, match="gateway"):
        run_spike(sdk, image=IMAGE, workspace="default")
    sdk.create.assert_not_called()


def test_ready_identity(sdk: MagicMock) -> None:
    """Readiness must describe the sandbox we created."""
    sdk.wait_ready.return_value = replace(sdk.wait_ready.return_value, id="replacement")
    with pytest.raises(SpikeError, match="identity"):
        run_spike(sdk, image=IMAGE, workspace="default")
    assert sdk.wait_deleted.call_args.kwargs["expected_sandbox_id"] == "identity"
