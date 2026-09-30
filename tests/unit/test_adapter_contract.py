"""Reviewable OpenShell 0.1.2 snapshots, exercised without a CLI or gateway."""

import json
from dataclasses import asdict, fields
from importlib.metadata import version
from inspect import signature
from pathlib import Path
from typing import TypedDict, cast
from unittest.mock import MagicMock, patch

import pytest
from google.protobuf.json_format import MessageToDict
from openshell import (
    DeletionOutcome,
    DeletionResult,
    SandboxClient,
    SandboxRef,
    ServiceExposure,
)
from openshell._proto.openshell_pb2 import HealthResponse, SandboxSpec

from openenv_openshell._adapter import CreateRequest, connect


class Contract(TypedDict):
    """The reviewed subset of the pinned SDK used by the private adapter."""

    sdk_version: str
    signatures: dict[str, str]
    response_fields: dict[str, list[str]]
    deletion_outcomes: dict[str, int]
    health_fields: dict[str, list[int]]
    connection: dict[str, str]
    calls: list[dict[str, object]]


@pytest.fixture
def contract() -> Contract:
    """Load the committed release snapshot; never regenerate it during tests."""
    path = Path(__file__).parents[1] / "fixtures" / "openshell-0.1.2.json"
    return cast("Contract", json.loads(path.read_text(encoding="utf-8")))


@pytest.mark.parametrize(
    "method",
    [
        "from_active_cluster",
        "health",
        "create",
        "wait_ready",
        "delete",
        "wait_deleted",
        "close",
    ],
)
def test_sdk_signatures(contract: Contract, method: str) -> None:
    """Names, parameter kinds/defaults and response types require upgrade review."""
    assert version("openshell") == contract["sdk_version"]
    assert (
        str(signature(getattr(SandboxClient, method))) == contract["signatures"][method]
    ), f"OpenShell {method} contract changed; review the SDK pin and adapter"


@pytest.mark.parametrize("model", [SandboxRef, DeletionResult, ServiceExposure])
def test_sdk_response_fields(
    contract: Contract,
    model: type[SandboxRef] | type[DeletionResult] | type[ServiceExposure],
) -> None:
    """Real SDK models cannot silently rename identity, routing or outcome fields."""
    assert [field.name for field in fields(model)] == contract["response_fields"][
        model.__name__
    ], f"OpenShell {model.__name__} fields changed; review response translation"


def test_sdk_health_and_deletion_fields(contract: Contract) -> None:
    """Gateway-version wire fields and deletion enum values retain their meaning."""
    assert {
        field.name: [field.number, field.type]
        for field in HealthResponse.DESCRIPTOR.fields
    } == contract["health_fields"]
    assert {outcome.name: outcome.value for outcome in DeletionOutcome} == contract[
        "deletion_outcomes"
    ]


def test_adapter_call_contract(
    contract: Contract, sdk: MagicMock, create_request: CreateRequest
) -> None:
    """Actual calls match the fixed fixture, including model serialization."""
    with patch(
        "openenv_openshell._sdk.SandboxClient.from_active_cluster", return_value=sdk
    ) as factory:
        adapter = connect(gateway="registered")
    factory.assert_called_once_with(**contract["connection"])
    created = adapter.create(create_request)
    ready = adapter.wait_ready("sandbox", workspace="default", timeout_s=12)
    deleted = adapter.delete("sandbox", workspace="default")
    adapter.wait_deleted(
        "sandbox", workspace="default", expected_sandbox_id="identity", timeout_s=5
    )
    adapter.close()
    adapter.close()

    calls: list[dict[str, object]] = []
    for method, args, kwargs in sdk.method_calls:
        normalized = cast("dict[str, object]", dict(kwargs))
        if method == "create":
            spec = normalized["spec"]
            assert isinstance(spec, SandboxSpec)
            normalized["spec"] = MessageToDict(spec, preserving_proto_field_name=True)
            exposures = cast("list[ServiceExposure]", normalized["service_exposures"])
            normalized["service_exposures"] = [
                asdict(exposure) for exposure in exposures
            ]
        calls.append({"method": method, "args": list(args), "kwargs": normalized})
    assert calls == contract["calls"], (
        "Adapter SDK calls differ from reviewed 0.1.2 contract"
    )

    assert created.name == ready.name == "sandbox"
    assert created.sandbox_id == ready.sandbox_id == deleted.sandbox_id == "identity"
    assert deleted.outcome == "accepted"
    assert dict(created.service_urls) == {
        "": "https://route.test",
        "named": "https://named.test",
    }
    assert created.service_urls is not sdk.create.return_value.service_urls
    assert not ready.service_urls
    assert adapter.service_url(created, "") == "https://route.test"
    assert adapter.service_url(created, "named") == "https://named.test"
    assert adapter.service_url(ready, "") is None
    with pytest.raises(TypeError):
        cast("dict[str, str]", created.service_urls)[""] = "https://changed.test"
