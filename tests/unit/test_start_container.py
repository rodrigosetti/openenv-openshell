"""Production startup lifecycle over the typed offline adapter boundary."""

from traceback import format_exception
from typing import Literal
from unittest.mock import patch

import pytest

from openenv_openshell import OpenShellProvider
from openenv_openshell._adapter import Sandbox
from openenv_openshell.errors import (
    OpenShellProviderError,
    PolicyConfigurationError,
    SandboxCreationError,
    SandboxDeletionError,
    SandboxReadinessError,
)
from openenv_openshell.metadata import ProviderState
from tests.fakes import (
    CreateCall,
    FakeDeletion,
    FakeOperation,
    FakeSandboxAdapter,
    WaitDeletedCall,
    WaitReadyCall,
)

SECRET = "private-startup-sentinel"  # noqa: S105 - Redaction sentinel.


@pytest.mark.parametrize("service", ["", "openenv"])
def test_start_preserves_request_and_create_route(service: str) -> None:
    """Readiness discards URLs; exact argv/environment and selected route survive."""
    created = Sandbox("chosen", "identity", {service: "https://route.test/prefix/"})
    adapter = FakeSandboxAdapter(
        create_result=created,
        ready_result=Sandbox("chosen", "identity"),
        service_url=created.service_urls[service],
    )
    command = ["launcher", "", "two words", SECRET]
    environment = {"TOKEN": SECRET, "PORT": "9000"}
    provider = OpenShellProvider(
        command=command,
        sandbox_name="chosen",
        workspace="training",
        service_name=service,
        startup_timeout_s=17,
        policy={"version": 1},
    )
    with patch.object(provider, "_connect_adapter", return_value=adapter):
        assert provider.start_container(
            "image:tag", port=9000, env_vars=environment
        ) == ("https://route.test/prefix/")
        with pytest.raises(OpenShellProviderError, match="already owns"):
            provider.start_container("other")
    assert [call.operation for call in adapter.calls] == [
        "create",
        "service_url",
        "wait_ready",
    ]
    call = adapter.calls[0]
    assert isinstance(call, CreateCall)
    assert tuple(call.request.command) == tuple(command)
    assert call.request.environment == environment
    assert call.request.target_port == int(environment["PORT"])
    assert call.request.policy == {"version": 1}
    assert adapter.calls[2] == WaitReadyCall("chosen", "training", 17)
    assert provider.state.sandbox_name == "chosen"
    assert provider.state.sandbox_id == "identity"
    assert provider.state.image == "image:tag"
    assert provider.state.base_url == created.service_urls[service]
    assert provider.state.created
    assert not provider.state.ready
    assert not provider.state.deleted
    assert not adapter.closed


@pytest.mark.parametrize(
    ("command", "policy", "options", "error"),
    [
        (None, None, {}, ValueError),
        (["server"], {"version": 2}, {}, PolicyConfigurationError),
        (["server"], None, {"port": False}, ValueError),
        (["server"], None, {"workdir": SECRET}, ValueError),
    ],
)
def test_invalid_inputs_never_connect(
    command: list[str] | None,
    policy: dict[str, int] | None,
    options: dict[str, object],
    error: type[Exception],
) -> None:
    """Fail closed locally before obtaining a gateway client."""
    provider = OpenShellProvider(command=command, policy=policy)
    with (
        patch.object(provider, "_connect_adapter") as connect,
        pytest.raises(error),
    ):
        provider.start_container("image", **options)  # pyright: ignore[reportArgumentType] - Invalid untyped caller input.
    connect.assert_not_called()
    assert provider.state.sandbox_name is None


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "/relative",
        "ftp://route.test",
        "https://user:secret@route.test",
        "https://route.test?token=private",
        "https://route.test#private",
    ],
)
def test_unusable_route_rolls_back(url: str | None) -> None:
    """Missing/malformed selected routes fail without falling back or waiting."""
    adapter = FakeSandboxAdapter(service_url=url)
    provider = OpenShellProvider(command=["server"], sandbox_name="chosen")
    with (
        patch.object(provider, "_connect_adapter", return_value=adapter),
        pytest.raises(SandboxCreationError, match="startup failed"),
    ):
        provider.start_container("image")
    assert [call.operation for call in adapter.calls] == [
        "create",
        "service_url",
        "delete",
        "wait_deleted",
    ]
    assert provider.state.deleted
    assert adapter.closed


@pytest.mark.parametrize("operation", ["service_url", "wait_ready"])
def test_runtime_failure_cleans_up_and_redacts(operation: FakeOperation) -> None:
    """Failures after a confirmed create request rollback."""
    adapter = FakeSandboxAdapter()
    adapter.failures[operation] = RuntimeError(SECRET)
    provider = OpenShellProvider(command=["server"], sandbox_name="chosen")
    error = SandboxReadinessError if operation == "wait_ready" else SandboxCreationError
    with (
        patch.object(provider, "_connect_adapter", return_value=adapter),
        pytest.raises(error) as raised,
    ):
        provider.start_container("image")
    assert SECRET not in str(raised.value)
    assert raised.value.__suppress_context__
    assert adapter.calls[-1] == WaitDeletedCall("chosen", "default", "sandbox-123", 60)
    assert provider.state.deleted
    assert adapter.closed


@pytest.mark.parametrize("operation", ["delete", "wait_deleted", "close"])
def test_cleanup_failure_preserves_startup_error(operation: FakeOperation) -> None:
    """Uncertain rollback retains state/client and prevents another create."""
    adapter = FakeSandboxAdapter(service_url=None)
    adapter.failures[operation] = RuntimeError(SECRET)
    provider = OpenShellProvider(command=["server"])
    with patch.object(provider, "_connect_adapter", return_value=adapter):
        with pytest.raises(SandboxCreationError):
            provider.start_container("image")
        assert not adapter.closed
        assert provider.state.deleted == (operation == "close")
        with pytest.raises(OpenShellProviderError, match="already owns"):
            provider.start_container("other")


@pytest.mark.parametrize(
    "outcome", ["already_absent", "completed", "accepted", "unknown"]
)
def test_create_failure_without_identity(
    outcome: Literal["already_absent", "completed", "accepted", "unknown"],
) -> None:
    """An uncertain create must never use delete to discover an identity."""
    adapter = FakeSandboxAdapter(failures={"create": RuntimeError(SECRET)})
    adapter.delete_result = FakeDeletion(None, outcome)
    provider = OpenShellProvider(command=["server"])
    with (
        patch.object(provider, "_connect_adapter", return_value=adapter),
        pytest.raises(SandboxCreationError),
    ):
        provider.start_container("image")
    assert not provider.state.deleted
    assert adapter.closed
    assert [call.operation for call in adapter.calls] == ["create"]


def test_keep_sandbox_retains_failure_for_inspection() -> None:
    """Debug retention releases ownership without deleting the failed sandbox."""
    adapter = FakeSandboxAdapter(service_url=None)
    provider = OpenShellProvider(command=["server"], keep_sandbox=True)
    with (
        patch.object(provider, "_connect_adapter", return_value=adapter),
        pytest.raises(SandboxCreationError),
    ):
        provider.start_container("image")
    assert [call.operation for call in adapter.calls] == ["create", "service_url"]
    assert adapter.closed
    assert not provider.state.deleted
    assert provider.state.sandbox_name is None


def test_readiness_identity_mismatch_fails() -> None:
    """A replacement cannot be treated as the originally created workload."""
    adapter = FakeSandboxAdapter(ready_result=Sandbox("chosen", "replacement"))
    provider = OpenShellProvider(command=["server"])
    with (
        patch.object(provider, "_connect_adapter", return_value=adapter),
        pytest.raises(SandboxReadinessError),
    ):
        provider.start_container("image")
    assert isinstance(adapter.calls[-1], WaitDeletedCall)
    assert adapter.calls[-1].expected_sandbox_id == "sandbox-123"
    assert provider.state.sandbox_id is None
    assert provider.state.deleted


def test_confirmed_rollback_allows_fresh_start() -> None:
    """A cleaned-up failure can restart with fresh state and default policy."""
    adapter = FakeSandboxAdapter(service_url=None)
    provider = OpenShellProvider(command=["server"])
    fresh_adapter = FakeSandboxAdapter(service_url="https://route.test")
    with patch.object(
        provider, "_connect_adapter", side_effect=[adapter, fresh_adapter]
    ):
        with pytest.raises(SandboxCreationError):
            provider.start_container("first")
        assert provider.start_container("second") == "https://route.test"
    assert provider.state.image == "second"
    assert not provider.state.deleted
    create_calls = [
        call for call in fresh_adapter.calls if isinstance(call, CreateCall)
    ]
    assert create_calls[-1].request.policy is None


@pytest.mark.parametrize("operation", ["service_url", "wait_ready"])
@pytest.mark.parametrize("cleanup", ["delete", "wait_deleted", "close"])
def test_rollback_failure_reports_safe_note_and_public_retry(
    operation: FakeOperation,
    cleanup: FakeOperation,
) -> None:
    """Every startup stage preserves its error while exposing a safe retry note."""
    adapter = FakeSandboxAdapter(
        failures={
            operation: RuntimeError(SECRET),
            cleanup: TimeoutError(SECRET),
        }
    )
    provider = OpenShellProvider(command=["server", SECRET], sandbox_name="chosen")
    error = SandboxReadinessError if operation == "wait_ready" else SandboxCreationError
    with (
        patch.object(provider, "_connect_adapter", return_value=adapter),
        pytest.raises(error) as caught,
    ):
        provider.start_container("image", env_vars={"TOKEN": SECRET})
    assert str(caught.value) == "OpenShell sandbox startup failed"
    assert caught.value.__notes__ == [
        "OpenShell sandbox cleanup failed; call stop_container again to retry",
    ]
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__
    assert SECRET not in "".join(format_exception(caught.value))
    adapter.failures.clear()
    calls = list(adapter.calls)
    provider.stop_container()
    provider.stop_container()
    assert adapter.closed
    assert provider.state.sandbox_name is None
    assert provider.state.deleted
    if cleanup == "close":
        assert adapter.calls == calls


def test_lost_create_reply_requires_operator_inspection() -> None:
    """Create ambiguity survives retries without ever deleting an unowned name."""
    adapter = FakeSandboxAdapter(failures={"create": RuntimeError(SECRET)})
    provider = OpenShellProvider(command=["server"], sandbox_name="chosen")
    with (
        patch.object(provider, "_connect_adapter", return_value=adapter),
        pytest.raises(SandboxCreationError),
    ):
        provider.start_container("image")
    adapter.failures.clear()
    with pytest.raises(SandboxDeletionError, match="operator"):
        provider.stop_container()
    assert [call.operation for call in adapter.calls] == ["create"]


@pytest.mark.parametrize("field", ["sandbox_id", "created", "base_url"])
def test_state_update_failure_rolls_back(field: str) -> None:
    """Failing post-create state assignments still delete the requested sandbox."""
    failed = False

    class FailingState(ProviderState):
        def __setattr__(self, name: str, value: object) -> None:
            nonlocal failed
            if not failed and name == field and value not in (None, False):
                failed = True
                raise RuntimeError(SECRET)
            super().__setattr__(name, value)

    adapter = FakeSandboxAdapter()
    provider = OpenShellProvider(command=["server"], sandbox_name="chosen")
    with (
        patch("openenv_openshell.provider.ProviderState", FailingState),
        patch.object(provider, "_connect_adapter", return_value=adapter),
        pytest.raises(SandboxCreationError),
    ):
        provider.start_container("image")
    assert adapter.calls[-1] == WaitDeletedCall("chosen", "default", "sandbox-123", 60)
    assert provider.state.deleted
    assert adapter.closed


def test_initial_state_failure_never_connects() -> None:
    """Building ownership metadata before connecting avoids an orphaned client."""
    provider = OpenShellProvider(command=["server"])
    with (
        patch("openenv_openshell.provider.ProviderState", side_effect=RuntimeError()),
        patch.object(provider, "_connect_adapter") as connect,
        pytest.raises(RuntimeError),
    ):
        provider.start_container("image")
    connect.assert_not_called()
