"""Tests for the deterministic OpenShell adapter test harness."""

import pytest

from openenv_openshell import OpenShellResources
from tests.fakes import (
    CreateCall,
    CreateRequest,
    DeleteCall,
    FakeDeletion,
    FakeOperation,
    FakeSandbox,
    FakeSandboxAdapter,
    ServiceUrlCall,
    WaitDeletedCall,
    WaitReadyCall,
)


def test_fake_captures_a_complete_successful_lifecycle() -> None:
    """Every lifecycle result and call is deterministic and inspectable."""
    created = FakeSandbox(name="chosen-name", sandbox_id="sandbox-created")
    ready = FakeSandbox(name="chosen-name", sandbox_id="sandbox-ready")
    deleted = FakeDeletion(sandbox_id="sandbox-ready")
    resources = OpenShellResources(cpu=2.0, memory="4Gi", gpu_count=1)
    policy = {"network": {"default": "deny"}}
    environment = {"OPENENV_PORT": "9000"}
    labels = {"purpose": "unit-test"}
    providers = ["credentials"]
    adapter = FakeSandboxAdapter(
        create_result=created,
        ready_result=ready,
        service_url="https://routed.example.test",
        delete_result=deleted,
    )

    request = CreateRequest(
        workspace="workspace",
        name="chosen-name",
        image="registry.example.test/environment@sha256:1234",
        command=("server",),
        environment=environment,
        service_name="openenv",
        target_port=9000,
        labels=labels,
        providers=providers,
        resources=resources,
        policy=policy,
    )
    assert adapter.create(request) is created
    assert (
        adapter.wait_ready("chosen-name", workspace="workspace", timeout_s=12.5)
        is ready
    )
    assert adapter.service_url(ready, "openenv") == "https://routed.example.test"
    assert (
        adapter.delete(
            "chosen-name", workspace="workspace", expected_sandbox_id="sandbox-123"
        )
        is deleted
    )
    assert (
        adapter.wait_deleted(
            "chosen-name",
            workspace="workspace",
            expected_sandbox_id="sandbox-ready",
            timeout_s=7.5,
        )
        is None
    )

    assert adapter.calls == [
        CreateCall(
            CreateRequest(
                workspace="workspace",
                name="chosen-name",
                image="registry.example.test/environment@sha256:1234",
                command=("server",),
                environment={"OPENENV_PORT": "9000"},
                service_name="openenv",
                target_port=9000,
                labels={"purpose": "unit-test"},
                providers=("credentials",),
                resources=resources,
                policy=policy,
            ),
        ),
        WaitReadyCall("chosen-name", "workspace", 12.5),
        ServiceUrlCall(ready, "openenv"),
        DeleteCall("chosen-name", "workspace"),
        WaitDeletedCall("chosen-name", "workspace", "sandbox-ready", 7.5),
    ]

    environment["LATE_MUTATION"] = "not captured"
    labels["late"] = "not captured"
    providers.append("not-captured")
    create_call = adapter.calls[0]
    assert isinstance(create_call, CreateCall)
    assert create_call.request.environment == {"OPENENV_PORT": "9000"}
    assert create_call.request.labels == {"purpose": "unit-test"}
    assert create_call.request.providers == ("credentials",)


def _invoke(adapter: FakeSandboxAdapter, operation: FakeOperation) -> None:
    if operation == "create":
        adapter.create(
            CreateRequest(
                workspace="default",
                name="sandbox",
                image="image",
                command=("server",),
                environment={},
                service_name="",
                target_port=8000,
                labels={},
                providers=(),
                resources=None,
                policy=None,
            ),
        )
    elif operation == "wait_ready":
        adapter.wait_ready("sandbox", workspace="default", timeout_s=1.0)
    elif operation == "service_url":
        adapter.service_url(FakeSandbox("openenv-test-abc123", "sandbox-123"), "")
    elif operation == "delete":
        adapter.delete("sandbox", workspace="default", expected_sandbox_id="identity")
    else:
        adapter.wait_deleted(
            "sandbox",
            workspace="default",
            expected_sandbox_id="sandbox-123",
            timeout_s=1.0,
        )


@pytest.mark.parametrize(
    "operation",
    ["create", "wait_ready", "service_url", "delete", "wait_deleted"],
)
def test_fake_injects_failure_after_capturing_call(operation: FakeOperation) -> None:
    """Each operation can fail independently while retaining diagnostics."""
    failure = RuntimeError(f"injected {operation} failure")
    adapter = FakeSandboxAdapter(failures={operation: failure})

    with pytest.raises(RuntimeError, match=f"injected {operation} failure"):
        _invoke(adapter, operation)

    assert len(adapter.calls) == 1
    assert adapter.calls[0].operation == operation


def test_fake_can_return_a_missing_service_url() -> None:
    """The fake represents the missing-route startup failure explicitly."""
    adapter = FakeSandboxAdapter(service_url=None)

    assert (
        adapter.service_url(FakeSandbox("openenv-test-abc123", "sandbox-123"), "")
        is None
    )
