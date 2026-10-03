"""Disposable collision and replacement controls on the real pinned gateway."""

from unittest.mock import patch

import pytest
from openshell import SandboxClient

from openenv_openshell import OpenShellProvider
from openenv_openshell._adapter import connect
from openenv_openshell.errors import SandboxCreationError, SandboxDeletionError
from tests.integration._runtime import Runtime

pytestmark = pytest.mark.integration


def test_collision_preserves_disposable_owner(openshell_runtime: Runtime) -> None:
    """A second provider's rollback cannot remove the first provider's sandbox."""
    owner = openshell_runtime.provider()
    url = owner.start_container(openshell_runtime.image)
    owner.wait_for_ready(url, timeout_s=60)
    identity = owner.state.sandbox_id
    assert identity
    contender = OpenShellProvider(
        command=owner.config.command,
        policy=owner.config.policy,
        sandbox_name=owner.config.sandbox_name,
        workspace=openshell_runtime.workspace,
        gateway=openshell_runtime.gateway,
    )
    openshell_runtime.providers.append(contender)
    with pytest.raises(SandboxCreationError, match="already in use"):
        contender.start_container(openshell_runtime.image)
    contender.stop_container()
    assert contender.state.sandbox_name is None
    owner.wait_for_ready(url, timeout_s=15)
    assert owner.state.sandbox_id == identity


def test_observed_replacement_preserves_disposable_owner(
    openshell_runtime: Runtime,
) -> None:
    """A stale owned identity cannot delete a new test-owned sandbox by name."""
    original = openshell_runtime.provider()
    original.start_container(openshell_runtime.image)
    identity = original.state.sandbox_id
    name = original.config.sandbox_name
    assert identity
    assert name
    original.stop_container()
    replacement = OpenShellProvider(
        command=original.config.command,
        policy=original.config.policy,
        sandbox_name=name,
        workspace=openshell_runtime.workspace,
        gateway=openshell_runtime.gateway,
    )
    openshell_runtime.providers.append(replacement)
    url = replacement.start_container(openshell_runtime.image)
    replacement.wait_for_ready(url, timeout_s=60)
    assert replacement.state.sandbox_id != identity
    adapter = connect(gateway=openshell_runtime.gateway)
    try:
        with patch(
            "openenv_openshell._sdk.SandboxClient.delete", autospec=True
        ) as delete:
            deletion = adapter.delete(
                name,
                workspace=openshell_runtime.workspace,
                expected_sandbox_id=identity,
            )
        delete.assert_not_called()
        assert deletion.outcome == "already_absent"
    finally:
        adapter.close()
    replacement.wait_for_ready(url, timeout_s=15)


def test_preflight_failure_recovers_and_deletes_owned_sandbox(
    openshell_runtime: Runtime,
) -> None:
    """A failed read-only lookup permits a later first delete on the real gateway."""
    owner = openshell_runtime.provider()
    url = owner.start_container(openshell_runtime.image)
    owner.wait_for_ready(url, timeout_s=60)
    identity = owner.state.sandbox_id
    name = owner.state.sandbox_name
    assert identity
    assert name
    with (
        patch(
            "openenv_openshell._sdk.SandboxClient.get",
            autospec=True,
            side_effect=OSError("Simulated transient lookup failure"),
        ),
        patch("openenv_openshell._sdk.SandboxClient.delete", autospec=True) as delete,
        patch(
            "openenv_openshell._sdk.SandboxClient.wait_deleted", autospec=True
        ) as wait,
        pytest.raises(SandboxDeletionError),
    ):
        owner.stop_container()
    delete.assert_not_called()
    wait.assert_not_called()
    assert owner.state.sandbox_id == identity
    owner.wait_for_ready(url, timeout_s=15)
    owner.stop_container()
    owner.stop_container()
    assert owner.state.deleted
    with SandboxClient.from_active_cluster(
        cluster=openshell_runtime.gateway, timeout=30
    ) as client:
        assert not any(
            sandbox.id == identity or sandbox.name == name
            for sandbox in client.list(workspace=openshell_runtime.workspace).all()
        )
