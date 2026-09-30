"""P4 production provider startup through the local routed EchoEnv runtime."""

import os
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from openshell import SandboxClient

from openenv_openshell import OpenShellProvider
from openenv_openshell._adapter import CreateRequest, Sandbox, connect
from openenv_openshell.errors import (
    OpenEnvReadinessTimeout,
    SandboxCreationError,
    SandboxReadinessError,
)
from tests.integration.test_protocol_spike import COMMAND, probe_protocol


@pytest.mark.integration
def test_provider_startup() -> None:
    """Provider returns the create route and the actual workload serves OpenEnv."""
    image = os.environ.get("OPENENV_OPENSHELL_ECHO_IMAGE_ID")
    if image is None:
        pytest.skip("Set OPENENV_OPENSHELL_ECHO_IMAGE_ID to the validated image ID")
    workspace = os.environ.get("OPENSHELL_WORKSPACE", "default")
    name = f"oe-p4-{uuid4().hex[:8]}"
    provider = OpenShellProvider(
        workspace=workspace,
        sandbox_name=name,
        command=COMMAND,
        policy=Path(__file__).parent / "images/echo/policy.yaml",
        labels={"openenv-p4": name},
    )
    try:
        url = provider.start_container(image, env_vars={"P4_CONTROL": "ordinary"})
        assert provider.state.base_url == url
        assert provider.state.created
        assert not provider.state.ready
        assert provider.state.sandbox_id
        provider.wait_for_ready(url, timeout_s=30)
        probe_protocol(url)
    finally:
        provider.stop_container()
        provider.stop_container()
        assert provider.state.sandbox_name is None
        assert provider.state.deleted
        with SandboxClient.from_active_cluster(timeout=30) as client:
            assert not client.list(
                workspace=workspace, label_selector=f"openenv-p4={name}"
            ).all()


@pytest.mark.integration
@pytest.mark.parametrize("stage", ["create", "service_url", "wait_ready", "health"])
def test_failed_start_cleanup(stage: str) -> None:
    """Real startup failures and health timeouts leave no sandbox."""
    image = os.environ.get("OPENENV_OPENSHELL_ECHO_IMAGE_ID")
    if image is None:
        pytest.skip("Set OPENENV_OPENSHELL_ECHO_IMAGE_ID to the validated image ID")
    workspace = os.environ.get("OPENSHELL_WORKSPACE", "default")
    name = f"oe-p7-{uuid4().hex[:8]}"
    provider = OpenShellProvider(
        workspace=workspace,
        sandbox_name=name,
        command=COMMAND
        if stage != "health"
        else [
            "python",
            "-c",
            "import time; time.sleep(120)",
        ],
        policy=Path(__file__).parent / "images/echo/policy.yaml",
        labels={"openenv-p7": name},
    )
    adapter = connect(gateway=provider.config.gateway)
    create = adapter.create

    def lost_create_response(request: CreateRequest) -> Sandbox:
        create(request)
        msg = "Simulated lost create response"
        raise RuntimeError(msg)

    try:
        with patch.object(provider, "_connect_adapter", return_value=adapter):
            if stage == "create":
                with (
                    patch.object(adapter, "create", side_effect=lost_create_response),
                    pytest.raises(SandboxCreationError),
                ):
                    provider.start_container(image)
            elif stage == "service_url":
                with (
                    patch.object(adapter, "service_url", return_value=None),
                    pytest.raises(SandboxCreationError),
                ):
                    provider.start_container(image)
            elif stage == "wait_ready":
                with (
                    patch.object(adapter, "wait_ready", side_effect=RuntimeError()),
                    pytest.raises(SandboxReadinessError),
                ):
                    provider.start_container(image)
            else:
                url = provider.start_container(image)
                with pytest.raises(OpenEnvReadinessTimeout):
                    provider.wait_for_ready(url, timeout_s=0.5)
                provider.stop_container()
        assert provider.state.deleted
        assert provider.state.sandbox_name is None
    finally:
        provider.stop_container()
        provider.stop_container()
        with SandboxClient.from_active_cluster(timeout=30) as client:
            assert not client.list(
                workspace=workspace, label_selector=f"openenv-p7={name}"
            ).all()
