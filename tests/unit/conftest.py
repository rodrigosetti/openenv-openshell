"""Shared offline SDK doubles for adapter behavior and release contracts."""

from collections.abc import Iterator
from dataclasses import replace
from unittest.mock import MagicMock, patch

import pytest
from openshell import DeletionOutcome, DeletionResult, SandboxRef
from openshell._proto.openshell_pb2 import HealthResponse
from openshell.sandbox import SandboxStatusRef

from openenv_openshell import OpenShellResources
from openenv_openshell._adapter import CreateRequest

SECRET = "credential-value-must-stay-private"  # noqa: S105 - Redaction sentinel.


@pytest.fixture
def sdk() -> Iterator[MagicMock]:
    """Provide a signature-aware SDK double with real response models."""
    with patch("openenv_openshell._sdk.SandboxClient", autospec=True) as client_type:
        client = client_type.from_active_cluster.return_value
        client.health.return_value = HealthResponse(version="0.1.2")
        client.create.return_value = SandboxRef(
            id="identity",
            name="sandbox",
            workspace="default",
            status=SandboxStatusRef(phase=1, current_policy_version=0),
            service_urls={"": "https://route.test", "named": "https://named.test"},
        )
        client.wait_ready.return_value = replace(
            client.create.return_value, service_urls={}
        )
        client.delete.return_value = DeletionResult(
            DeletionOutcome.ACCEPTED, "identity"
        )
        yield client


@pytest.fixture
def create_request() -> CreateRequest:
    """Provide a resolved create_request without upstream models."""
    return CreateRequest(
        workspace="default",
        name="sandbox",
        image="image@sha256:fixture",
        environment={"SECRET": SECRET},
        service_name="",
        target_port=8000,
        labels={"purpose": "test"},
        providers=("credentials",),
        resources=OpenShellResources(cpu=2, memory="4Gi", gpu_count=1),
        policy={"version": 1, "filesystem": {"read_write": ["/workspace"]}},
    )
