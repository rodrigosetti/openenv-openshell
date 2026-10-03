"""OpenShell 0.1.2 imports and wire models confined to one private module."""

from __future__ import annotations

from contextlib import suppress
from types import MappingProxyType
from typing import TYPE_CHECKING, TypeVar, cast

import grpc
from google.protobuf.descriptor import Descriptor, FieldDescriptor
from google.protobuf.json_format import MessageToDict, ParseDict, ParseError
from openshell import (
    DeletionOutcome,
    SandboxClient,
    SandboxError,
    SandboxRef,
    ServiceExposure,
)
from openshell._proto.openshell_pb2 import SandboxSpec, SandboxTemplate
from openshell._proto.sandbox_pb2 import SandboxPolicy

from openenv_openshell._adapter import (
    SDK_VERSION,
    CreateCollisionError,
    CreateRequest,
    DeleteNotSentError,
    Deletion,
    Sandbox,
)
from openenv_openshell.config import validate_command
from openenv_openshell.errors import (
    OpenShellConnectionError,
    OpenShellProviderError,
    PolicyConfigurationError,
    SandboxCreationError,
    SandboxDeletionError,
    SandboxReadinessError,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

_Result = TypeVar("_Result")
_CONNECTION_CODES = {
    grpc.StatusCode.UNAVAILABLE,
    grpc.StatusCode.UNAUTHENTICATED,
    grpc.StatusCode.PERMISSION_DENIED,
}

_POLICY_ERROR = "Invalid explicit OpenShell policy; check the supported 0.1.2 schema."
_ENUM_PREFIXES = {
    "tls": "NETWORK_TLS_MODE_",
    "enforcement": "NETWORK_ENFORCEMENT_MODE_",
    "access": "NETWORK_ACCESS_PRESET_",
}


def _policy_value(value: object, field: FieldDescriptor) -> object:
    if field.message_type is not None:
        return _policy_fields(value, field.message_type)
    if field.type == FieldDescriptor.TYPE_STRING:
        valid = isinstance(value, str)
    elif field.type == FieldDescriptor.TYPE_BOOL:
        valid = isinstance(value, bool)
    elif field.enum_type is not None:
        # Authored YAML uses short lowercase enum spellings.
        if isinstance(value, str):
            for name in field.enum_type.values_by_name:
                if (
                    name.removeprefix(_ENUM_PREFIXES.get(field.name, ""))
                    == value.upper()
                ):
                    return name
        valid = isinstance(value, str) and value in field.enum_type.values_by_name
    else:
        valid = type(value) is int
    if not valid:
        raise PolicyConfigurationError(_POLICY_ERROR)
    return value


def _policy_fields(value: object, descriptor: Descriptor) -> dict[str, object]:
    if not isinstance(value, dict):
        raise PolicyConfigurationError(_POLICY_ERROR)
    result: dict[str, object] = {}
    for key, child in cast("dict[str, object]", value).items():
        field = descriptor.fields_by_name.get(key)
        if field is None:
            raise PolicyConfigurationError(_POLICY_ERROR)
        if field.is_repeated:
            if field.message_type and field.message_type.GetOptions().map_entry:
                if not isinstance(child, dict):
                    raise PolicyConfigurationError(_POLICY_ERROR)
                item_field = field.message_type.fields_by_name["value"]
                result[key] = {
                    name: _policy_value(item, item_field)
                    for name, item in cast("dict[str, object]", child).items()
                }
            else:
                if not isinstance(child, list):
                    raise PolicyConfigurationError(_POLICY_ERROR)
                result[key] = [
                    _policy_value(item, field) for item in cast("list[object]", child)
                ]
        else:
            result[key] = _policy_value(child, field)
    return dict(sorted(result.items()))


def normalize_policy(policy: Mapping[str, object]) -> dict[str, object]:
    """Validate exact field shapes before strict conversion, without a gateway."""
    if type(policy.get("version")) is not int or policy["version"] != 1:
        raise PolicyConfigurationError(_POLICY_ERROR)
    fields = _policy_fields(dict(policy), cast("Descriptor", SandboxPolicy.DESCRIPTOR))
    landlock = fields.get("landlock")
    if isinstance(landlock, dict) and cast("dict[str, object]", landlock).get(
        "compatibility"
    ) not in {
        "best_effort",
        "hard_requirement",
    }:
        raise PolicyConfigurationError(_POLICY_ERROR)
    try:
        model = ParseDict(fields, SandboxPolicy(), ignore_unknown_fields=False)
    except (ParseError, ValueError, TypeError):
        raise PolicyConfigurationError(_POLICY_ERROR) from None
    # JSON output uses exact snake_case fields and canonical enum names.
    return MessageToDict(model, preserving_proto_field_name=True)


def _call(
    operation: Callable[[], _Result], error: type[OpenShellProviderError]
) -> _Result:
    try:
        return operation()
    except grpc.RpcError as failure:
        # GatewayError is a public RpcError subtype. Never copy details/metadata.
        if (
            error is SandboxCreationError
            and failure.code() == grpc.StatusCode.ALREADY_EXISTS
        ):
            msg = "OpenShell sandbox name is already in use; choose another name."
            raise CreateCollisionError(msg) from None
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
        spec = SandboxSpec(template=SandboxTemplate(image=request.image))
        spec.command.extend(validate_command(request.command))
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
                    normalize_policy(request.policy),
                    SandboxPolicy(),
                    ignore_unknown_fields=False,
                )
            except (ParseError, ValueError, TypeError):
                msg = "Invalid normalized OpenShell policy; check the 0.1.2 schema."
                raise PolicyConfigurationError(msg) from None
            spec.policy.CopyFrom(policy)  # pyright: ignore[reportUnknownMemberType] - Upstream cross-module stub.
        # Explicit policy errors must precede even gateway access. Never create
        # with an omitted/default policy after a conversion failure.
        self._check_gateway()
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

    def delete(
        self, sandbox_name: str, *, workspace: str, expected_sandbox_id: str
    ) -> Deletion:
        """Reject observed replacements before issuing the name-based delete.

        This preflight is not an atomic identity condition: OpenShell 0.1.2
        has no public conditional delete. See docs/cleanup-tests.md.
        """
        if not expected_sandbox_id:
            msg = "Sandbox ownership is unconfirmed; inspect gateway diagnostics."
            raise DeleteNotSentError(msg)
        try:
            current = self._client.get(sandbox_name, workspace=workspace)
        except grpc.RpcError as failure:
            if failure.code() == grpc.StatusCode.NOT_FOUND:
                return Deletion(expected_sandbox_id, "already_absent")
            msg = "Cannot verify sandbox ownership; retry cleanup."
            raise DeleteNotSentError(msg) from None
        except (SandboxError, OSError, ValueError):
            msg = "Cannot verify sandbox ownership; retry cleanup."
            raise DeleteNotSentError(msg) from None
        if current.id != expected_sandbox_id:
            return Deletion(expected_sandbox_id, "already_absent")
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
