"""Offline adapter calls against the selected SDK's real models and signatures."""

from dataclasses import replace
from importlib.metadata import PackageNotFoundError
from traceback import format_exception
from typing import cast
from unittest.mock import MagicMock, patch

import grpc
import pytest
from openshell import (
    DeletionOutcome,
    DeletionResult,
    GatewayError,
    SandboxClient,
    SandboxError,
)
from openshell._proto.openshell_pb2 import HealthResponse

from openenv_openshell import OpenShellResources
from openenv_openshell._adapter import (
    CreateCollisionError,
    CreateRequest,
    SandboxAdapter,
    connect,
)
from openenv_openshell._sdk import SDKAdapter
from openenv_openshell.errors import (
    OpenShellConnectionError,
    OpenShellProviderError,
    PolicyConfigurationError,
    SandboxCreationError,
    SandboxDeletionError,
    SandboxReadinessError,
)
from tests.fakes import FakeSandboxAdapter

SECRET = "credential-value-must-stay-private"  # noqa: S105 - Redaction sentinel.


def test_lifecycle(sdk: MagicMock, create_request: CreateRequest) -> None:
    """The typed adapter uses only public lifecycle calls and retains routes."""
    adapter: SandboxAdapter = connect(gateway="registered")
    created = adapter.create(create_request)
    ready = adapter.wait_ready("sandbox", workspace="default", timeout_s=12)
    assert created.sandbox_id == ready.sandbox_id == "identity"
    assert adapter.service_url(created, "") == "https://route.test"
    assert adapter.service_url(created, "named") == "https://named.test"
    assert adapter.service_url(ready, "") is None
    sdk.health.assert_called_once_with()
    kwargs = sdk.create.call_args.kwargs
    assert kwargs["workspace"] == "default"
    assert kwargs["name"] == "sandbox"
    assert kwargs["labels"] == create_request.labels
    assert kwargs["service_exposures"][0].target_port == create_request.target_port
    assert kwargs["service_exposures"][0].service == ""
    spec = kwargs["spec"]
    assert spec.template.image == create_request.image
    assert dict(spec.environment) == create_request.environment
    assert list(spec.providers) == ["credentials"]
    assert spec.template.resources["limits"] == {"cpu": "2", "memory": "4Gi"}
    assert spec.resource_requirements.gpu.count == 1
    assert spec.HasField("policy")
    assert list(spec.command) == list(create_request.command)
    sdk.wait_ready.assert_called_once_with(
        "sandbox", workspace="default", timeout_seconds=12
    )
    deleted = adapter.delete(
        "sandbox", workspace="default", expected_sandbox_id="identity"
    )
    assert deleted.sandbox_id == "identity"
    assert deleted.outcome == "accepted"
    adapter.wait_deleted(
        "sandbox", workspace="default", expected_sandbox_id="identity", timeout_s=5
    )
    sdk.delete.assert_called_once_with(
        "sandbox", workspace="default", allow_missing=True
    )
    sdk.wait_deleted.assert_called_once_with(
        "sandbox",
        workspace="default",
        expected_sandbox_id="identity",
        timeout_seconds=5,
    )
    adapter.close()
    adapter.close()
    sdk.close.assert_called_once_with()
    with pytest.raises(OpenShellConnectionError, match="closed"):
        adapter.create(create_request)


@pytest.mark.parametrize(
    "resources",
    [
        None,
        OpenShellResources(),
        OpenShellResources(cpu=1),
        OpenShellResources(memory="1Gi"),
        OpenShellResources(gpu_count=2),
    ],
)
def test_optional_inputs(
    sdk: MagicMock, create_request: CreateRequest, resources: OpenShellResources | None
) -> None:
    """Unset workload inputs remain unset, preserving upstream defaults."""
    connect().create(
        replace(create_request, resources=resources, policy=None, service_name="named")
    )
    spec = sdk.create.call_args.kwargs["spec"]
    assert not spec.HasField("policy")
    assert sdk.create.call_args.kwargs["service_exposures"][0].service == "named"


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (DeletionOutcome.COMPLETED, "completed"),
        (DeletionOutcome.ALREADY_ABSENT, "already_absent"),
        (DeletionOutcome.UNSPECIFIED, "unknown"),
        (DeletionOutcome(99), "unknown"),
    ],
)
def test_deletion_outcomes(
    sdk: MagicMock, outcome: DeletionOutcome, expected: str
) -> None:
    """No unspecified/future outcome is mistaken for completed deletion."""
    sdk.delete.return_value = DeletionResult(outcome, None)
    result = connect().delete(
        "sandbox", workspace="default", expected_sandbox_id="identity"
    )
    assert result.outcome == expected
    assert result.sandbox_id is None


@pytest.mark.parametrize("installed", ["0.0.116", "0.1.3", SECRET])
def test_wrong_sdk(installed: str) -> None:
    """Version errors are actionable and exclude untrusted version values."""
    with (
        patch("openenv_openshell._adapter.version", return_value=installed),
        pytest.raises(OpenShellConnectionError, match="uv sync --locked") as error,
    ):
        connect()
    assert SECRET not in str(error.value)


def test_missing_sdk() -> None:
    """Missing SDK metadata gives installation guidance."""
    with (
        patch("openenv_openshell._adapter.version", side_effect=PackageNotFoundError),
        pytest.raises(OpenShellConnectionError, match="uv sync --locked"),
    ):
        connect()


def test_broken_sdk_import() -> None:
    """A broken SDK import does not expose its raw import error."""
    with (
        patch.dict("sys.modules", {"openenv_openshell._sdk": None}),
        pytest.raises(OpenShellConnectionError, match="uv sync --locked"),
    ):
        connect()


@pytest.mark.parametrize("gateway_version", ["0.0.116", "", SECRET])
def test_gateway_version(sdk: MagicMock, gateway_version: str) -> None:
    """Reject incompatible gateways and release the newly acquired client."""
    sdk.health.return_value = HealthResponse(version=gateway_version)
    with pytest.raises(OpenShellConnectionError, match=r"0\.1\.2 gateway") as error:
        connect()
    assert SECRET not in str(error.value)
    sdk.close.assert_called_once_with()
    sdk.create.assert_not_called()


def test_direct_wrapper_checks_gateway(
    sdk: MagicMock, create_request: CreateRequest
) -> None:
    """Injected clients cannot bypass the pre-create gateway check."""
    sdk.health.return_value = HealthResponse(version="0.0.116")
    with pytest.raises(OpenShellConnectionError):
        SDKAdapter(cast("SandboxClient", sdk)).create(create_request)
    sdk.create.assert_not_called()


def test_failed_health_and_close(sdk: MagicMock) -> None:
    """A secondary close failure never replaces the connection error."""
    sdk.health.side_effect = SandboxError(SECRET)
    sdk.close.side_effect = OSError(SECRET)
    with pytest.raises(OpenShellConnectionError) as error:
        connect()
    assert SECRET not in "".join(format_exception(error.value))
    sdk.close.assert_called_once_with()


def test_failed_connection(sdk: MagicMock) -> None:
    """Registry/configuration failures are actionable connection errors."""
    with (
        patch(
            "openenv_openshell._sdk.SandboxClient.from_active_cluster",
            side_effect=SandboxError(SECRET),
        ),
        pytest.raises(OpenShellConnectionError) as error,
    ):
        connect()
    assert SECRET not in "".join(format_exception(error.value))
    sdk.close.assert_not_called()


@pytest.mark.parametrize(
    "policy",
    [
        {SECRET: True},
        {},
        {"version": 2},
        {"version": "1"},
        {"version": True},
        {"version": 1, "filesystem": {"include_workdir": 1}},
        {"version": 1, "landlock": {"compatibility": SECRET}},
        {"version": 1, "filesystem": {"read_only": [False]}},
        {"version": 1, "network_policies": {"api": {"endpoints": [{"port": -1}]}}},
    ],
)
def test_invalid_policy(
    sdk: MagicMock, create_request: CreateRequest, policy: dict[str, object]
) -> None:
    """Strict conversion fails before create without including raw policy."""
    with pytest.raises(PolicyConfigurationError) as error:
        SDKAdapter(cast("SandboxClient", sdk)).create(
            replace(create_request, policy=policy)
        )
    sdk.health.assert_not_called()
    sdk.create.assert_not_called()
    assert SECRET not in "".join(format_exception(error.value))
    assert SECRET not in repr(create_request)


class TransportError(grpc.RpcError):
    """Controlled gRPC failure with secret-bearing diagnostics."""

    def __init__(self, status: grpc.StatusCode) -> None:
        """Set a controlled transport code and sensitive diagnostic."""
        super().__init__(SECRET)
        self.status = status

    def code(self) -> grpc.StatusCode:
        """Return the public transport status."""
        return self.status


def _invoke(
    adapter: SandboxAdapter, operation: str, create_request: CreateRequest
) -> None:
    if operation == "create":
        adapter.create(create_request)
    elif operation == "wait_ready":
        adapter.wait_ready("sandbox", workspace="default", timeout_s=1)
    elif operation == "delete":
        adapter.delete("sandbox", workspace="default", expected_sandbox_id="identity")
    elif operation == "wait_deleted":
        adapter.wait_deleted(
            "sandbox", workspace="default", expected_sandbox_id="identity", timeout_s=1
        )
    else:
        adapter.close()


@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        ("create", SandboxCreationError),
        ("wait_ready", SandboxReadinessError),
        ("delete", SandboxDeletionError),
        ("wait_deleted", SandboxDeletionError),
        ("close", OpenShellConnectionError),
    ],
)
@pytest.mark.parametrize(
    "failure",
    [
        SandboxError(SECRET),
        OSError(SECRET),
        ValueError(SECRET),
        TransportError(grpc.StatusCode.INVALID_ARGUMENT),
        GatewayError(TransportError(grpc.StatusCode.INVALID_ARGUMENT)),
    ],
)
def test_operation_errors(
    sdk: MagicMock,
    create_request: CreateRequest,
    operation: str,
    expected: type[OpenShellProviderError],
    failure: Exception,
) -> None:
    """Each operation translates SDK errors without exception-chain leaks."""
    adapter = connect()
    getattr(sdk, operation).side_effect = failure
    with pytest.raises(expected) as error:
        _invoke(adapter, operation, create_request)
    assert SECRET not in "".join(format_exception(error.value))


@pytest.mark.parametrize(
    "status",
    [
        grpc.StatusCode.UNAVAILABLE,
        grpc.StatusCode.UNAUTHENTICATED,
        grpc.StatusCode.PERMISSION_DENIED,
    ],
)
def test_transport_errors(
    sdk: MagicMock, create_request: CreateRequest, status: grpc.StatusCode
) -> None:
    """Connection and authentication transport failures have stable meanings."""
    sdk.create.side_effect = TransportError(status)
    with pytest.raises(OpenShellConnectionError) as error:
        connect().create(create_request)
    assert SECRET not in "".join(format_exception(error.value))


def test_fake_conforms() -> None:
    """The existing deterministic fake satisfies the production protocol."""
    adapter: SandboxAdapter = FakeSandboxAdapter()
    adapter.close()


@pytest.mark.parametrize("command", [(), ("",), ("server", SECRET + "\x00")])
def test_adapter_rejects_invalid_command(
    command: tuple[str, ...], sdk: MagicMock, create_request: CreateRequest
) -> None:
    """Direct adapter requests cannot silently create a shell workload."""
    adapter = SDKAdapter(sdk)
    with pytest.raises(ValueError, match="command") as error:
        adapter.create(replace(create_request, command=command))
    assert SECRET not in "".join(format_exception(error.value))
    sdk.health.assert_not_called()
    sdk.create.assert_not_called()


def test_collision_has_distinct_safe_error(
    sdk: MagicMock, create_request: CreateRequest
) -> None:
    """A collision cannot be treated as a partially created owned sandbox."""
    sdk.create.side_effect = TransportError(grpc.StatusCode.ALREADY_EXISTS)
    with pytest.raises(CreateCollisionError) as caught:
        connect().create(create_request)
    assert SECRET not in "".join(format_exception(caught.value))
    sdk.delete.assert_not_called()


@pytest.mark.parametrize("identity", ["replacement", ""])
def test_observed_replacement_is_never_deleted(sdk: MagicMock, identity: str) -> None:
    """A mismatched or missing current identity is not the owned sandbox."""
    sdk.get.return_value = replace(sdk.create.return_value, id=identity)
    deletion = connect().delete(
        "sandbox", workspace="default", expected_sandbox_id="identity"
    )
    assert deletion.outcome == "already_absent"
    assert deletion.sandbox_id == "identity"
    sdk.delete.assert_not_called()


@pytest.mark.parametrize(
    "failure",
    [
        TransportError(grpc.StatusCode.NOT_FOUND),
        TransportError(grpc.StatusCode.UNAVAILABLE),
        SandboxError(SECRET),
        OSError(SECRET),
        ValueError(SECRET),
    ],
)
def test_identity_preflight_errors_fail_safely(
    sdk: MagicMock, failure: Exception
) -> None:
    """Only confirmed absence completes cleanup; lookup failures cannot delete."""
    sdk.get.side_effect = failure
    adapter = connect()
    if (
        isinstance(failure, TransportError)
        and failure.code() == grpc.StatusCode.NOT_FOUND
    ):
        assert (
            adapter.delete(
                "sandbox", workspace="default", expected_sandbox_id="identity"
            ).outcome
            == "already_absent"
        )
    else:
        with pytest.raises(SandboxDeletionError) as caught:
            adapter.delete(
                "sandbox", workspace="default", expected_sandbox_id="identity"
            )
        assert SECRET not in "".join(format_exception(caught.value))
    sdk.delete.assert_not_called()


def test_missing_expected_identity_never_queries_or_deletes(sdk: MagicMock) -> None:
    """The private adapter cannot be called with an unknown ownership identity."""
    with pytest.raises(SandboxDeletionError, match="ownership"):
        connect().delete("sandbox", workspace="default", expected_sandbox_id="")
    sdk.get.assert_not_called()
    sdk.delete.assert_not_called()
