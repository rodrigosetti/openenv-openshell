"""P4 production provider startup through the local routed EchoEnv runtime."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from openshell import SandboxClient

from openenv_openshell import OpenShellProvider
from tests.integration.test_protocol_spike import COMMAND, probe_protocol


@pytest.mark.integration
@pytest.mark.parametrize("cleanup", ["stop", "close", "context", "context_error"])
def test_provider_startup(cleanup: str) -> None:
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

    def run_workload() -> None:
        url = provider.start_container(image, env_vars={"P4_CONTROL": "ordinary"})
        assert provider.state.base_url == url
        assert provider.state.created
        assert not provider.state.ready
        assert provider.state.sandbox_id
        provider.wait_for_ready(url, timeout_s=30)
        probe_protocol(url)

    def run_failing_context() -> None:
        with provider:
            run_workload()
            msg = "context body failed"
            raise RuntimeError(msg)

    try:
        if cleanup == "context_error":
            with pytest.raises(RuntimeError, match="context body failed"):
                run_failing_context()
        elif cleanup == "context":
            with provider:
                run_workload()
        else:
            run_workload()
            if cleanup == "close":
                provider.close()
            else:
                provider.stop_container()
        assert provider.state.sandbox_name is None
        assert provider.state.deleted
    finally:
        provider.stop_container()
        provider.stop_container()
        assert provider.state.sandbox_name is None
        assert provider.state.deleted
        with SandboxClient.from_active_cluster(timeout=30) as client:
            assert not client.list(
                workspace=workspace, label_selector=f"openenv-p4={name}"
            ).all()
