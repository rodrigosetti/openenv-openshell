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
        provider.wait_for_ready(url, timeout_s=30)
        probe_protocol(url)
    finally:
        # P6 owns public stop_container; use the real SDK for verified test teardown.
        with SandboxClient.from_active_cluster(timeout=30) as client:
            deletion = client.delete(name, workspace=workspace, allow_missing=True)
            identity = provider.state.sandbox_id or deletion.sandbox_id
            if identity is not None:
                client.wait_deleted(
                    name,
                    workspace=workspace,
                    expected_sandbox_id=identity,
                    timeout_seconds=60,
                )
            assert not client.list(
                workspace=workspace, label_selector=f"openenv-p4={name}"
            ).all()
        if provider._adapter is not None:  # noqa: SLF001 - Temporary teardown until P6.  # pyright: ignore[reportPrivateUsage]
            provider._adapter.close()  # noqa: SLF001 - Temporary teardown until P6.  # pyright: ignore[reportPrivateUsage]
