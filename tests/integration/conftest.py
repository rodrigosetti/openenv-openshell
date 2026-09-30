"""Opt-in runtime fixtures shared by EchoEnv and security E2E tests."""

import os
from collections.abc import Iterator
from typing import cast

import pytest
from openshell import SandboxClient

from openenv_openshell._adapter import SDK_VERSION
from tests.integration._runtime import Runtime, runtime_scope


@pytest.fixture
def openshell_gateway(request: pytest.FixtureRequest) -> str | None:
    """Connect to a registered gateway and validate version/workspace access."""
    # pytest 8 leaves FixtureRequest.node unannotated; this fixture is function-scoped.
    node = cast("pytest.Item", request.node)  # pyright: ignore[reportUnknownMemberType]
    if node.get_closest_marker("integration") is None:
        pytest.fail("OpenShell runtime fixtures require the integration marker")

    if not os.environ.get("OPENENV_OPENSHELL_ECHO_IMAGE_ID"):
        pytest.skip("Set OPENENV_OPENSHELL_ECHO_IMAGE_ID to a compatible image")
    gateway = os.environ.get("OPENSHELL_GATEWAY") or None
    workspace = os.environ.get("OPENSHELL_WORKSPACE", "default")
    try:
        with SandboxClient.from_active_cluster(cluster=gateway, timeout=30) as client:
            if client.health().version != SDK_VERSION:
                pytest.fail("E2E requires the pinned OpenShell 0.1.2 gateway")
            client.list(workspace=workspace, page_size=1).all()
    except Exception:  # noqa: BLE001 - Raw transport errors may contain credentials.
        pytest.fail(
            "E2E gateway unavailable; check version and workspace access", pytrace=False
        )
    return gateway


@pytest.fixture
def openshell_runtime(
    request: pytest.FixtureRequest, openshell_gateway: str | None
) -> Iterator[Runtime]:
    """Own every provider created by one test, including partial startup."""
    runtime = Runtime(
        image=os.environ["OPENENV_OPENSHELL_ECHO_IMAGE_ID"],
        workspace=os.environ.get("OPENSHELL_WORKSPACE", "default"),
        gateway=openshell_gateway,
    )
    try:
        with runtime_scope(runtime):
            yield runtime
    finally:
        # Same pytest 8 unannotated node property; function scope guarantees Item.
        node = cast("pytest.Item", request.node)  # pyright: ignore[reportUnknownMemberType]
        node.add_report_section(
            "teardown", "OpenShell E2E", "\n".join(runtime.diagnostics)
        )
