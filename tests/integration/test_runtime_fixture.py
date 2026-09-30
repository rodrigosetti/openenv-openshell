"""I1 real-runtime controls for the reusable E2E owner."""

import signal

import pytest
from openshell import SandboxClient

from tests.integration._runtime import Runtime, runtime_scope
from tests.integration.test_protocol_spike import probe_protocol


@pytest.mark.integration
@pytest.mark.parametrize("interrupted", [False, True])
def test_runtime_cleanup(openshell_runtime: Runtime, *, interrupted: bool) -> None:
    """Healthy routed workload and interrupted body both leave no sandbox."""
    nested = Runtime(
        openshell_runtime.image,
        openshell_runtime.workspace,
        openshell_runtime.gateway,
    )
    # Also register with the outer fixture as a fallback if this control fails.
    provider = nested.provider()
    openshell_runtime.providers.append(provider)
    try:
        with runtime_scope(nested):
            url = provider.start_container(nested.image)
            provider.wait_for_ready(url, timeout_s=30)
            probe_protocol(url)
            if interrupted:
                signal.raise_signal(signal.SIGTERM)
    except KeyboardInterrupt:
        assert interrupted
    assert provider.state.deleted
    assert provider.state.sandbox_name is None
    with SandboxClient.from_active_cluster(
        cluster=nested.gateway, timeout=30
    ) as client:
        assert not any(
            sandbox.name == provider.config.sandbox_name
            for sandbox in client.list(workspace=nested.workspace).all()
        )
