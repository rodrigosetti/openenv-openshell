"""P4 production provider startup through the local routed EchoEnv runtime."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from openshell import SandboxClient

from openenv_openshell import OpenShellProvider
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
        assert provider.metadata is not None
        assert provider.metadata.service_url == url
        assert provider.metadata.sandbox_id == provider.state.sandbox_id
        provider.wait_for_ready(url, timeout_s=30)
        assert provider.metadata is not None
        assert provider.metadata.ready_at is not None
        probe_protocol(url)
    finally:
        provider.stop_container()
        provider.stop_container()
        assert provider.state.sandbox_name is None
        assert provider.state.deleted
        assert provider.metadata is not None
        assert provider.metadata.deleted_at is not None
        with SandboxClient.from_active_cluster(timeout=30) as client:
            assert not client.list(
                workspace=workspace, label_selector=f"openenv-p4={name}"
            ).all()
