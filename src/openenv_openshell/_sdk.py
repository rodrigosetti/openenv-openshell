"""OpenShell 0.1.2 imports and wire models confined to one private module."""

from __future__ import annotations

from contextlib import suppress
from types import MappingProxyType
from typing import TYPE_CHECKING, TypeVar

import grpc
from google.protobuf.json_format import ParseDict, ParseError
from openshell import (
    DeletionOutcome,
    SandboxClient,
    SandboxError,
    SandboxRef,
    ServiceExposure,
)
from openshell._proto.openshell_pb2 import SandboxSpec, SandboxTemplate
from openshell._proto.sandbox_pb2 import SandboxPolicy

from openenv_openshell._adapter import SDK_VERSION, CreateRequest, Deletion, Sandbox
from openenv_openshell.errors import (
    OpenShellConnectionError,
    OpenShellProviderError,
    PolicyConfigurationError,
    SandboxCreationError,
    SandboxDeletionError,
    SandboxReadinessError,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_Result = TypeVar("_Result")
_CONNECTION_CODES = {
    grpc.StatusCode.UNAVAILABLE,
    grpc.StatusCode.UNAUTHENTICATED,
    grpc.StatusCode.PERMISSION_DENIED,
}


def _call(
    operation: Callable[[], _Result], error: type[OpenShellProviderError]
) -> _Result:
    try:
        return operation()
    except grpc.RpcError as failure:
        # GatewayError is a public RpcError subtype. Never copy details/metadata.
        if failure.code() in _CONNECTION_CODES:
            msg = (
                "Cannot reach or authenticate to OpenShell; "
                "check gateway and credentials."
            )
            raise OpenShellConnectionError(msg) from None
        msg = "OpenShell operation failed; check gateway diagnostics."
        raise error(msg) from None
    except (SandboxError, OSError, ValueError):
        msg = "OpenShell operation failed; check gateway diagnostics."
        raise error(msg) from None


def _sandbox(result: SandboxRef) -> Sandbox:
    return Sandbox(result.name, result.id, MappingProxyType(dict(result.service_urls)))


class SDKAdapter:
    """Translate stable project inputs to the pinned public SDK lifecycle calls."""

    def __init__(self, client: SandboxClient) -> None:
        """Wrap a client; the connection factory verifies gateway compatibility."""
        self._client = client
        self._closed = False
        self._gateway_checked = False

    @classmethod
    def connect(cls, *, gateway: str | None = None) -> SDKAdapter:
        """Connect through the CLI gateway registry without insecure overrides."""
        client = _call(
            lambda: SandboxClient.from_active_cluster(cluster=gateway),
            OpenShellConnectionError,
        )
        adapter = cls(client)
        try:
            adapter._check_gateway()
        except OpenShellProviderError:
            # Failure to close must not replace the actionable connection error.
            with suppress(OpenShellProviderError):
                adapter.close()
            raise
        return adapter

    def _check_gateway(self) -> None:
        if self._closed:
            msg = "OpenShell client is closed; create a new adapter."
            raise OpenShellConnectionError(msg)
        if not self._gateway_checked:
            health = _call(self._client.health, OpenShellConnectionError)
            if health.version != SDK_VERSION:
                msg = "Use an OpenShell 0.1.2 gateway with the pinned SDK."
                raise OpenShellConnectionError(msg)
            self._gateway_checked = True

    def create(self, request: CreateRequest) -> Sandbox:
        """Build private models and request an atomic service exposure."""
        self._check_gateway()
        spec = SandboxSpec(template=SandboxTemplate(image=request.image))
        spec.environment.update(request.environment)
        spec.providers.extend(request.providers)
        resources = request.resources
        if resources is not None:
            limits: dict[str, str] = {}
            if resources.cpu is not None:
                limits["cpu"] = str(resources.cpu)
            if resources.memory is not None:
                limits["memory"] = resources.memory
            if limits:
                spec.template.resources.update({"limits": limits})
            if resources.gpu_count is not None:
                spec.resource_requirements.gpu.count = resources.gpu_count
        if request.policy is not None:
            try:
                policy = ParseDict(
                    dict(request.policy), SandboxPolicy(), ignore_unknown_fields=False
                )
            except (ParseError, ValueError, TypeError):
                msg = "Invalid normalized OpenShell policy; check the 0.1.2 schema."
                raise PolicyConfigurationError(msg) from None
            spec.policy.CopyFrom(policy)  # pyright: ignore[reportUnknownMemberType] - Upstream cross-module stub.
        return _sandbox(
            _call(
                lambda: self._client.create(
                    workspace=request.workspace,
                    name=request.name,
                    spec=spec,
                    labels=request.labels,
                    service_exposures=[
                        ServiceExposure(
                            target_port=request.target_port,
                            service=request.service_name,
                        )
                    ],
                ),
                SandboxCreationError,
            )
        )

    def wait_ready(
        self, sandbox_name: str, *, workspace: str, timeout_s: float
    ) -> Sandbox:
        """Translate readiness timeouts and detach the returned SDK reference."""
        return _sandbox(
            _call(
                lambda: self._client.wait_ready(
                    sandbox_name, workspace=workspace, timeout_seconds=timeout_s
                ),
                SandboxReadinessError,
            )
        )

    def service_url(self, sandbox: Sandbox, service_name: str) -> str | None:
        """Use only the captured create-time route; never query get()."""
        return sandbox.service_urls.get(service_name)

    def delete(self, sandbox_name: str, *, workspace: str) -> Deletion:
        """Retain both outcome and identity; unknown outcomes stay uncertain."""
        result = _call(
            lambda: self._client.delete(
                sandbox_name, workspace=workspace, allow_missing=True
            ),
            SandboxDeletionError,
        )
        if result.outcome == DeletionOutcome.COMPLETED:
            return Deletion(result.sandbox_id, "completed")
        if result.outcome == DeletionOutcome.ACCEPTED:
            return Deletion(result.sandbox_id, "accepted")
        if result.outcome == DeletionOutcome.ALREADY_ABSENT:
            return Deletion(result.sandbox_id, "already_absent")
        return Deletion(result.sandbox_id, "unknown")

    def wait_deleted(
        self,
        sandbox_name: str,
        *,
        workspace: str,
        expected_sandbox_id: str,
        timeout_s: float,
    ) -> None:
        """Pass the original sandbox identity to the public deletion waiter."""
        _call(
            lambda: self._client.wait_deleted(
                sandbox_name,
                workspace=workspace,
                expected_sandbox_id=expected_sandbox_id,
                timeout_seconds=timeout_s,
            ),
            SandboxDeletionError,
        )

    def close(self) -> None:
        """Close the client idempotently, allowing retries after a close failure."""
        if not self._closed:
            _call(self._client.close, OpenShellConnectionError)
            self._closed = True
