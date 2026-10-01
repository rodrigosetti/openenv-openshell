"""Public error and logging redaction through the production SDK adapter."""

import logging
from traceback import format_exception
from unittest.mock import MagicMock, patch

import httpx
import pytest
from openshell import SandboxError

from openenv_openshell import OpenShellProvider
from openenv_openshell.errors import (
    OpenEnvReadinessTimeout,
    OpenShellConnectionError,
    OpenShellProviderError,
    SandboxCreationError,
    SandboxDeletionError,
    SandboxReadinessError,
)

# Synthetic redaction sentinels, never real credentials.
SECRETS = (
    "t5-sdk-credential-sentinel",
    "t5-bearer-token-sentinel",
    "t5-raw-environment-sentinel",
    "t5-command-argument-sentinel",
)
DIAGNOSTIC = (
    "credential=" + SECRETS[0] + " Authorization: Bearer " + " ".join(SECRETS[1:])
)


def assert_safe(
    caplog: pytest.LogCaptureFixture, error: BaseException | None = None
) -> None:
    """Check formatted output and log payloads, including exception attachments."""
    output = caplog.text + repr([record.__dict__ for record in caplog.records])
    if error is not None:
        output += str(error) + repr(getattr(error, "__notes__", []))
        output += "".join(format_exception(error))
    for secret in SECRETS:
        assert secret not in output
    for record in caplog.records:
        if record.name.startswith("openenv_openshell"):
            assert record.exc_info is None
            assert record.stack_info is None


def configured_provider() -> OpenShellProvider:
    """Place sensitive argv in the real configuration boundary."""
    return OpenShellProvider(command=["server", SECRETS[3]], sandbox_name="sandbox")


@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        ("health", OpenShellConnectionError),
        ("create", SandboxCreationError),
        ("wait_ready", SandboxReadinessError),
        ("delete", SandboxDeletionError),
        ("wait_deleted", SandboxDeletionError),
        ("close", SandboxDeletionError),
    ],
)
def test_public_sdk_failure_redaction(
    sdk: MagicMock,
    caplog: pytest.LogCaptureFixture,
    operation: str,
    expected: type[OpenShellProviderError],
) -> None:
    """Production translation and provider logging never copy SDK diagnostics."""
    caplog.set_level(logging.DEBUG)
    provider = configured_provider()
    getattr(sdk, operation).side_effect = SandboxError(DIAGNOSTIC)
    if operation in {"health", "create", "wait_ready"}:
        with pytest.raises(expected) as caught:
            provider.start_container("image", env_vars={"ACCESS_TOKEN": SECRETS[2]})
    else:
        provider.start_container("image", env_vars={"ACCESS_TOKEN": SECRETS[2]})
        with pytest.raises(expected) as caught:
            provider.close()
    assert_safe(caplog, caught.value)
    getattr(sdk, operation).side_effect = None
    if operation == "create":
        with pytest.raises(SandboxDeletionError) as cleanup:
            provider.close()
        assert_safe(caplog, cleanup.value)
    else:
        provider.close()
    assert_safe(caplog)


@pytest.mark.parametrize("startup", ["wait_ready"])
@pytest.mark.parametrize("cleanup", ["delete", "wait_deleted", "close"])
def test_sdk_rollback_note_and_retry_redaction(
    sdk: MagicMock,
    caplog: pytest.LogCaptureFixture,
    startup: str,
    cleanup: str,
) -> None:
    """Secondary cleanup diagnostics cannot leak via notes or retry warnings."""
    caplog.set_level(logging.DEBUG)
    provider = configured_provider()
    getattr(sdk, startup).side_effect = SandboxError(DIAGNOSTIC)
    getattr(sdk, cleanup).side_effect = OSError(DIAGNOSTIC)
    expected = SandboxCreationError if startup == "create" else SandboxReadinessError
    with pytest.raises(expected) as caught:
        provider.start_container("image", env_vars={"ACCESS_TOKEN": SECRETS[2]})
    assert caught.value.__notes__ == [
        "OpenShell sandbox cleanup failed; call stop_container again to retry"
    ]
    assert any(record.levelno == logging.WARNING for record in caplog.records)
    assert_safe(caplog, caught.value)
    getattr(sdk, startup).side_effect = None
    getattr(sdk, cleanup).side_effect = None
    provider.close()
    assert_safe(caplog)


def test_http_diagnostics_redaction(
    sdk: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    """HTTP failure detail is omitted from public timeout output and logs."""
    caplog.set_level(logging.DEBUG)
    provider = configured_provider()
    url = provider.start_container("image", env_vars={"ACCESS_TOKEN": SECRETS[2]})
    sdk.health.assert_called_once_with()

    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(DIAGNOSTIC, request=request)

    client = httpx.Client(transport=httpx.MockTransport(fail))
    with (
        patch("openenv_openshell.provider.httpx.Client", return_value=client),
        patch("openenv_openshell.provider.monotonic", side_effect=[0, 0, 1, 1]),
        pytest.raises(OpenEnvReadinessTimeout) as caught,
    ):
        provider.wait_for_ready(url, timeout_s=1)
    assert client.is_closed
    assert_safe(caplog, caught.value)
    provider.close()
    assert_safe(caplog)


def test_successful_sdk_lifecycle_redaction(
    sdk: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    """Sensitive inputs reach the workload but never become lifecycle log fields."""
    caplog.set_level(logging.DEBUG)
    provider = configured_provider()
    url = provider.start_container("image", env_vars={"ACCESS_TOKEN": SECRETS[2]})
    spec = sdk.create.call_args.kwargs["spec"]
    assert list(spec.command) == ["server", SECRETS[3]]
    assert spec.environment["ACCESS_TOKEN"] == SECRETS[2]
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    with patch("openenv_openshell.provider.httpx.Client", return_value=client):
        provider.wait_for_ready(url)
    provider.close()
    assert provider.state.deleted
    assert_safe(caplog)
