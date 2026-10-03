"""Typed test doubles for the private OpenShell adapter boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, TypeAlias

if TYPE_CHECKING:
    from collections.abc import Mapping


from openenv_openshell._adapter import (
    CreateRequest,
)
from openenv_openshell._adapter import (
    Deletion as FakeDeletion,
)
from openenv_openshell._adapter import (
    Sandbox as FakeSandbox,
)

FakeOperation: TypeAlias = Literal[
    "create",
    "wait_ready",
    "service_url",
    "delete",
    "wait_deleted",
    "close",
]


@dataclass(frozen=True, slots=True)
class CreateCall:
    """Captured arguments for one sandbox create request."""

    request: CreateRequest
    operation: Literal["create"] = field(default="create", init=False)


@dataclass(frozen=True, slots=True)
class WaitReadyCall:
    """Captured arguments for one sandbox readiness wait."""

    sandbox_name: str
    workspace: str
    timeout_s: float
    operation: Literal["wait_ready"] = field(default="wait_ready", init=False)


@dataclass(frozen=True, slots=True)
class ServiceUrlCall:
    """Captured arguments for one service URL lookup."""

    sandbox: FakeSandbox
    service_name: str
    operation: Literal["service_url"] = field(default="service_url", init=False)


@dataclass(frozen=True, slots=True)
class DeleteCall:
    """Captured arguments for one sandbox deletion request."""

    sandbox_name: str
    workspace: str
    expected_sandbox_id: str = "sandbox-123"
    operation: Literal["delete"] = field(default="delete", init=False)


@dataclass(frozen=True, slots=True)
class WaitDeletedCall:
    """Captured arguments for one sandbox deletion wait."""

    sandbox_name: str
    workspace: str
    expected_sandbox_id: str
    timeout_s: float
    operation: Literal["wait_deleted"] = field(default="wait_deleted", init=False)


AdapterCall: TypeAlias = (
    CreateCall | WaitReadyCall | ServiceUrlCall | DeleteCall | WaitDeletedCall
)


class FakeSandboxAdapter:
    """Deterministic, configurable fake for provider lifecycle unit tests."""

    def __init__(
        self,
        *,
        create_result: FakeSandbox | None = None,
        ready_result: FakeSandbox | None = None,
        service_url: str | None = "https://sandbox-123.openshell.localhost",
        delete_result: FakeDeletion | None = None,
        failures: Mapping[FakeOperation, BaseException] | None = None,
    ) -> None:
        """Configure results and per-operation failures without external I/O."""
        self.create_result = create_result or FakeSandbox(
            "openenv-test-abc123", "sandbox-123"
        )
        self.ready_result = ready_result or self.create_result
        self.service_url_result = service_url
        self.delete_result = delete_result or FakeDeletion(
            sandbox_id=self.create_result.sandbox_id,
        )
        self.failures = dict(failures or {})
        self.calls: list[AdapterCall] = []
        self.closed = False
        self.close_attempts = 0

    def create(self, request: CreateRequest) -> FakeSandbox:
        """Capture a create request and return its configured sandbox."""
        self.calls.append(
            CreateCall(
                CreateRequest(
                    workspace=request.workspace,
                    name=request.name,
                    image=request.image,
                    command=tuple(request.command),
                    environment=dict(request.environment),
                    service_name=request.service_name,
                    target_port=request.target_port,
                    labels=dict(request.labels),
                    providers=tuple(request.providers),
                    resources=request.resources,
                    policy=request.policy,
                ),
            ),
        )
        self._raise_failure("create")
        return self.create_result

    def wait_ready(
        self,
        sandbox_name: str,
        *,
        workspace: str,
        timeout_s: float,
    ) -> FakeSandbox:
        """Capture a readiness wait and return the configured ready sandbox."""
        self.calls.append(WaitReadyCall(sandbox_name, workspace, timeout_s))
        self._raise_failure("wait_ready")
        return self.ready_result

    def service_url(self, sandbox: FakeSandbox, service_name: str) -> str | None:
        """Capture service lookup and return a configured URL or absence."""
        self.calls.append(ServiceUrlCall(sandbox, service_name))
        self._raise_failure("service_url")
        return self.service_url_result

    def delete(
        self, sandbox_name: str, *, workspace: str, expected_sandbox_id: str
    ) -> FakeDeletion:
        """Capture a delete request and return its acknowledgement."""
        self.calls.append(DeleteCall(sandbox_name, workspace, expected_sandbox_id))
        self._raise_failure("delete")
        return self.delete_result

    def wait_deleted(
        self,
        sandbox_name: str,
        *,
        workspace: str,
        expected_sandbox_id: str,
        timeout_s: float,
    ) -> None:
        """Capture a deletion wait and complete deterministically."""
        self.calls.append(
            WaitDeletedCall(
                sandbox_name,
                workspace,
                expected_sandbox_id,
                timeout_s,
            ),
        )
        self._raise_failure("wait_deleted")

    def close(self) -> None:
        """Release fake resources without contacting a gateway."""
        self.close_attempts += 1
        self._raise_failure("close")
        self.closed = True

    def _raise_failure(self, operation: FakeOperation) -> None:
        failure = self.failures.get(operation)
        if failure is not None:
            raise failure
