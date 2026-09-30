"""Run provenance and event contracts over offline lifecycle and HTTP fakes."""

import logging
from dataclasses import FrozenInstanceError, asdict
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from unittest.mock import patch

import httpx
import pytest

from openenv_openshell import OpenShellProvider, OpenShellRunMetadata
from openenv_openshell.errors import (
    SandboxCreationError,
    SandboxDeletionError,
    SandboxReadinessError,
)
from openenv_openshell.metadata import package_version
from tests.fakes import FakeDeletion, FakeOperation, FakeSandboxAdapter

SECRET = "observability-private-sentinel"  # noqa: S105 - Secret redaction sentinel.


def events(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Read only provider events, independent of third-party logging."""
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == "openenv_openshell"
    ]


def test_run_snapshot_and_event_order(caplog: pytest.LogCaptureFixture) -> None:
    """Snapshots are immutable, versioned, timed, and retained through cleanup."""
    caplog.set_level(logging.INFO, logger="openenv_openshell")
    adapter = FakeSandboxAdapter()
    provider = OpenShellProvider(
        command=["server", SECRET], sandbox_name="chosen", workspace="training"
    )
    assert provider.metadata is None
    before = datetime.now(UTC)
    with patch.object(provider, "_connect_adapter", return_value=adapter):
        url = provider.start_container(
            "image@sha256:fixture", env_vars={"TOKEN": SECRET}
        )
    created = provider.metadata
    assert isinstance(created, OpenShellRunMetadata)
    assert created.sandbox_name == "chosen"
    assert created.sandbox_id == "sandbox-123"
    assert created.workspace == "training"
    assert created.image == "image@sha256:fixture"
    assert created.service_url == url
    assert created.created_at.tzinfo is UTC
    assert before <= created.created_at <= datetime.now(UTC)
    assert created.openenv_provider_version == version("openenv-openshell")
    assert created.openshell_version == version("openshell")
    assert created.openenv_version == version("openenv")
    assert created.policy_digest is None
    assert created.ready_at is None
    assert created.deleted_at is None
    assert SECRET not in repr(asdict(created))
    with pytest.raises(FrozenInstanceError):
        created.image = "changed"  # type: ignore[misc] - Check frozen public contract.
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    with patch("openenv_openshell.provider.httpx.Client", return_value=client):
        provider.wait_for_ready(url)
    healthy = provider.metadata
    assert healthy is not None
    assert healthy.ready_at is not None
    assert healthy.created_at <= healthy.ready_at <= datetime.now(UTC)
    provider.stop_container()
    stopped = provider.metadata
    assert stopped is not None
    assert stopped.deleted_at is not None
    assert healthy.ready_at <= stopped.deleted_at <= datetime.now(UTC)
    assert stopped.ready_at == healthy.ready_at
    assert created.ready_at is None
    provider.stop_container()
    assert provider.metadata is stopped
    assert events(caplog) == [
        "sandbox.create.started",
        "sandbox.create.completed",
        "service.exposed",
        "sandbox.ready",
        "openenv.health.ready",
        "sandbox.delete.started",
        "sandbox.delete.completed",
    ]
    assert SECRET not in repr([record.__dict__ for record in caplog.records])


@pytest.mark.parametrize("keep_sandbox", [False, True])
def test_retention_restart_and_rejected_start(*, keep_sandbox: bool) -> None:
    """Retained runs have no deletion time; invalid starts preserve prior evidence."""
    provider = OpenShellProvider(command=["server"], keep_sandbox=keep_sandbox)
    with patch.object(provider, "_connect_adapter", return_value=FakeSandboxAdapter()):
        provider.start_container("first")
    provider.stop_container()
    previous = provider.metadata
    assert previous is not None
    assert (previous.deleted_at is None) == keep_sandbox
    with pytest.raises(ValueError, match="image"):
        provider.start_container("")
    assert provider.metadata is previous
    adapter = FakeSandboxAdapter(failures={"create": RuntimeError(SECRET)})
    with (
        patch.object(provider, "_connect_adapter", return_value=adapter),
        pytest.raises(SandboxCreationError),
    ):
        provider.start_container("failed")
    assert provider.metadata is None


@pytest.mark.parametrize("operation", ["delete", "wait_deleted", "close"])
def test_cleanup_failure_events_and_retry(
    caplog: pytest.LogCaptureFixture, operation: FakeOperation
) -> None:
    """Errors contain no SDK detail; completion is logged only on confirmed absence."""
    caplog.set_level(logging.INFO, logger="openenv_openshell")
    adapter = FakeSandboxAdapter()
    provider = OpenShellProvider(command=["server"])
    with patch.object(provider, "_connect_adapter", return_value=adapter):
        provider.start_container("image")
    caplog.clear()
    adapter.failures[operation] = RuntimeError(SECRET)
    with pytest.raises(SandboxDeletionError):
        provider.stop_container()
    expected = ["sandbox.delete.started"]
    if operation == "close":
        expected.append("sandbox.delete.completed")
    expected.append("provider.cleanup.failed")
    assert events(caplog) == expected
    assert provider.metadata is not None
    assert (provider.metadata.deleted_at is not None) == (operation == "close")
    failed = provider.metadata
    adapter.failures.clear()
    provider.stop_container()
    assert provider.metadata is not None
    assert provider.metadata.deleted_at is not None
    if operation == "close":
        assert provider.metadata is failed
    assert SECRET not in repr([record.__dict__ for record in caplog.records])
    warning = next(r for r in caplog.records if r.levelno == logging.WARNING)
    assert warning.exc_info is None


@pytest.mark.parametrize("operation", ["delete", "wait_deleted", "close", None])
def test_rollback_reporting(
    caplog: pytest.LogCaptureFixture, operation: FakeOperation | None
) -> None:
    """Readiness failures retain route provenance and report rollback truthfully."""
    caplog.set_level(logging.INFO, logger="openenv_openshell")
    adapter = FakeSandboxAdapter(failures={"wait_ready": RuntimeError(SECRET)})
    if operation is not None:
        adapter.failures[operation] = RuntimeError(SECRET)
    provider = OpenShellProvider(command=["server"])
    with (
        patch.object(provider, "_connect_adapter", return_value=adapter),
        pytest.raises(SandboxReadinessError),
    ):
        provider.start_container("image")
    assert "sandbox.ready" not in events(caplog)
    assert ("sandbox.delete.completed" in events(caplog)) == (
        operation in {None, "close"}
    )
    assert ("provider.cleanup.failed" in events(caplog)) == (operation is not None)
    assert provider.metadata is not None
    assert provider.metadata.ready_at is None
    assert SECRET not in repr([record.__dict__ for record in caplog.records])


def test_uncertain_rollback_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    """Lost create with uncertain deletion cannot emit successful completion."""
    caplog.set_level(logging.INFO, logger="openenv_openshell")
    adapter = FakeSandboxAdapter(
        failures={"create": RuntimeError(SECRET)},
        delete_result=FakeDeletion(None, "unknown"),
    )
    provider = OpenShellProvider(command=["server"])
    with (
        patch.object(provider, "_connect_adapter", return_value=adapter),
        pytest.raises(SandboxCreationError),
    ):
        provider.start_container("image")
    assert events(caplog) == [
        "sandbox.create.started",
        "sandbox.delete.started",
        "provider.cleanup.failed",
    ]
    assert provider.metadata is None


def test_missing_distribution_has_no_invented_version() -> None:
    """A source-only installation records missing distribution metadata as None."""
    with patch("openenv_openshell.metadata.version", side_effect=PackageNotFoundError):
        assert package_version("openenv-openshell") is None
