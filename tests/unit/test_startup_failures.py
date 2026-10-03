"""Failure acceptance cases across sandbox startup and HTTP readiness."""

from unittest.mock import patch

import httpx
import pytest

from openenv_openshell import OpenShellProvider
from openenv_openshell.errors import (
    OpenEnvReadinessTimeout,
    SandboxCreationError,
    SandboxReadinessError,
)
from openenv_openshell.metadata import ProviderState
from tests.fakes import (
    DeleteCall,
    FakeOperation,
    FakeSandboxAdapter,
    WaitDeletedCall,
    WaitReadyCall,
)
from tests.unit.test_readiness import Clock, install_client


@pytest.mark.parametrize("operation", ["service_url", "wait_ready"])
@pytest.mark.parametrize("interruption_type", [KeyboardInterrupt, SystemExit])
def test_startup_interruption_rolls_back(
    operation: FakeOperation, interruption_type: type[BaseException]
) -> None:
    """Direct startup preserves exit semantics and cleans up before returning."""
    interruption = interruption_type("private interruption")
    adapter = FakeSandboxAdapter(failures={operation: interruption})
    provider = OpenShellProvider(
        command=["server"], sandbox_name="interrupted", deletion_timeout_s=11
    )
    with (
        patch.object(provider, "_connect_adapter", return_value=adapter),
        pytest.raises(interruption_type) as caught,
    ):
        provider.start_container("echo:fixture")
    assert caught.value is interruption
    assert adapter.calls[-2:] == [
        DeleteCall("interrupted", "default"),
        WaitDeletedCall("interrupted", "default", "sandbox-123", 11),
    ]
    assert adapter.closed
    assert provider.state == ProviderState(deleted=True)


@pytest.mark.parametrize("cleanup_failure", [OSError, KeyboardInterrupt, SystemExit])
def test_interrupted_startup_cleanup_failure_is_retryable(
    cleanup_failure: type[BaseException], caplog: pytest.LogCaptureFixture
) -> None:
    """A second failure cannot mask the first interruption or erase ownership."""
    interruption = KeyboardInterrupt()
    adapter = FakeSandboxAdapter(
        failures={
            "wait_ready": interruption,
            "wait_deleted": cleanup_failure("secret cleanup details"),
        }
    )
    provider = OpenShellProvider(command=["server"], sandbox_name="interrupted")
    with (
        patch.object(provider, "_connect_adapter", return_value=adapter),
        pytest.raises(KeyboardInterrupt) as caught,
    ):
        provider.start_container("echo:fixture")
    assert caught.value is interruption
    assert "retry" in " ".join(interruption.__notes__)
    assert "secret" not in " ".join(interruption.__notes__) + caplog.text
    assert provider.state.sandbox_id == "sandbox-123"
    assert not adapter.closed
    del adapter.failures["wait_deleted"]
    provider.stop_container()
    assert [call.operation for call in adapter.calls].count("delete") == 1
    assert adapter.closed
    assert provider.state.deleted


@pytest.mark.parametrize("operation", ["create", "wait_ready"])
def test_interrupted_startup_honors_keep_sandbox(operation: FakeOperation) -> None:
    """Retention explicitly releases the client without deleting any sandbox."""
    interruption = KeyboardInterrupt()
    adapter = FakeSandboxAdapter(failures={operation: interruption})
    provider = OpenShellProvider(command=["server"], keep_sandbox=True)
    with (
        patch.object(provider, "_connect_adapter", return_value=adapter),
        pytest.raises(KeyboardInterrupt) as caught,
    ):
        provider.start_container("echo:fixture")
    assert caught.value is interruption
    assert not {"delete", "wait_deleted"} & {call.operation for call in adapter.calls}
    assert adapter.closed
    assert provider.state == ProviderState()


def test_interrupted_create_never_guesses_ownership() -> None:
    """A lost create identity retains inspection data without name deletion."""
    interruption = KeyboardInterrupt()
    adapter = FakeSandboxAdapter(failures={"create": interruption})
    provider = OpenShellProvider(command=["server"], sandbox_name="unknown")
    with (
        patch.object(provider, "_connect_adapter", return_value=adapter),
        pytest.raises(KeyboardInterrupt) as caught,
    ):
        provider.start_container("echo:fixture")
    assert caught.value is interruption
    assert [call.operation for call in adapter.calls] == ["create"]
    assert provider.state.sandbox_name == "unknown"
    assert provider.state.sandbox_id is None
    assert "inspection" in " ".join(interruption.__notes__)


@pytest.mark.parametrize("operation", ["wait_ready"])
def test_sandbox_timeout_rolls_back(operation: FakeOperation) -> None:
    """A timed-out readiness wait deletes by the confirmed create identity."""
    adapter = FakeSandboxAdapter(failures={operation: TimeoutError("upstream timeout")})
    provider = OpenShellProvider(
        command=["server"],
        sandbox_name="timed-out",
        workspace="training",
        startup_timeout_s=7,
        deletion_timeout_s=11,
    )
    error = SandboxCreationError if operation == "create" else SandboxReadinessError
    with (
        patch.object(provider, "_connect_adapter", return_value=adapter),
        pytest.raises(error, match="startup failed"),
    ):
        provider.start_container("echo:fixture")

    expected = ["create"]
    if operation == "wait_ready":
        expected += ["service_url", "wait_ready"]
        assert adapter.calls[2] == WaitReadyCall("timed-out", "training", 7)
    assert [call.operation for call in adapter.calls] == [
        *expected,
        "delete",
        "wait_deleted",
    ]
    assert adapter.calls[-2:] == [
        DeleteCall("timed-out", "training"),
        WaitDeletedCall("timed-out", "training", "sandbox-123", 11),
    ]
    assert adapter.closed
    assert provider.state == ProviderState(deleted=True)
    calls = list(adapter.calls)
    provider.stop_container()
    assert adapter.calls == calls


@pytest.mark.parametrize(
    "failure",
    [
        301,
        401,
        403,
        404,
        500,
        503,
        httpx.ConnectTimeout,
        httpx.ReadTimeout,
        httpx.RemoteProtocolError,
    ],
)
def test_persistent_health_failure_and_caller_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    failure: int | type[httpx.RequestError],
) -> None:
    """Each unhealthy status or transport error times out and permits teardown."""
    clock = Clock()
    monkeypatch.setattr("openenv_openshell.provider.monotonic", clock.monotonic)
    monkeypatch.setattr("openenv_openshell.provider.sleep", clock.sleep)
    adapter = FakeSandboxAdapter()
    provider = OpenShellProvider(command=["server"], sandbox_name="unhealthy")
    monkeypatch.setattr(provider, "_connect_adapter", lambda: adapter)
    url = provider.start_container("echo:fixture")
    calls: list[httpx.Request] = []
    responses: list[httpx.Response] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert str(request.url) == url + "/health"
        if not isinstance(failure, int):
            message = "upstream failure"
            raise failure(message, request=request)
        response = httpx.Response(failure, headers={"location": "https://login.test"})
        responses.append(response)
        return response

    client = install_client(monkeypatch, handler)
    with pytest.raises(OpenEnvReadinessTimeout, match="health readiness timed out"):
        provider.wait_for_ready(url, timeout_s=1)

    assert len(calls) == 2  # noqa: PLR2004 - Probes at 0 and 0.5 seconds only.
    assert clock.sleeps == [0.5, 0.5]
    assert client.is_closed
    assert all(response.is_closed for response in responses)
    assert provider.state.created
    assert not provider.state.ready
    assert not adapter.closed
    assert provider.metadata is not None
    assert provider.metadata.ready_at is None
    assert provider.metadata.deleted_at is None

    provider.stop_container()
    assert adapter.calls[-2:] == [
        DeleteCall("unhealthy", "default"),
        WaitDeletedCall("unhealthy", "default", "sandbox-123", 60),
    ]
    assert adapter.closed
    assert provider.state == ProviderState(deleted=True)
    assert provider.metadata is not None
    assert provider.metadata.ready_at is None
    assert provider.metadata.deleted_at is not None
