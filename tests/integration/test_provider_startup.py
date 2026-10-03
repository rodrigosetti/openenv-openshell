"""P4 production provider startup through the local routed EchoEnv runtime."""

import os
from contextlib import closing
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
    SandboxDeletionError,
    SandboxReadinessError,
)
from openenv_openshell.policy import load_policy, policy_digest
from tests.integration.test_protocol_spike import COMMAND, probe_protocol


@pytest.mark.integration
@pytest.mark.parametrize("cleanup", ["stop", "close", "context", "context_error"])
def test_provider_startup(cleanup: str) -> None:
    """Provider returns the create route and the actual workload serves OpenEnv."""
    image = os.environ.get("OPENENV_OPENSHELL_ECHO_IMAGE_ID")
    if image is None:
        pytest.skip("Set OPENENV_OPENSHELL_ECHO_IMAGE_ID to the validated image ID")
    workspace = os.environ.get("OPENSHELL_WORKSPACE", "default")
    name = f"oe-p4-{uuid4().hex[:13]}"  # Exercise the 19-character explicit limit.
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
        assert provider.metadata is not None
        assert (provider.metadata.service_url, provider.metadata.policy_digest) == (
            url,
            policy_digest(
                load_policy(Path(__file__).parent / "images/echo/policy.yaml")
            ),
        )
        assert provider.metadata.sandbox_id == provider.state.sandbox_id
        provider.wait_for_ready(url, timeout_s=30)
        assert provider.metadata is not None
        assert provider.metadata.ready_at is not None
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
        assert provider.metadata is not None
        assert provider.metadata.deleted_at is not None
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
    captured_identity: str | None = None

    def lost_create_response(request: CreateRequest) -> Sandbox:
        nonlocal captured_identity
        captured_identity = create(request).sandbox_id
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
        if stage == "create":
            assert not provider.state.deleted
            assert provider.state.sandbox_id is None
            with pytest.raises(SandboxDeletionError, match="operator"):
                provider.stop_container()
        else:
            assert provider.state.deleted
            assert provider.state.sandbox_name is None
    finally:
        if stage == "create" and captured_identity is not None:
            # Test-only operator control: the fake transport captured a successful
            # response. Production cannot infer this identity from a lost reply.
            with closing(connect(gateway=provider.config.gateway)) as operator:
                operator.delete(
                    name, workspace=workspace, expected_sandbox_id=captured_identity
                )
                operator.wait_deleted(
                    name,
                    workspace=workspace,
                    expected_sandbox_id=captured_identity,
                    timeout_s=60,
                )
            provider.state.deleted = True
        provider.stop_container()
        provider.stop_container()
        with SandboxClient.from_active_cluster(timeout=30) as client:
            assert not client.list(
                workspace=workspace, label_selector=f"openenv-p7={name}"
            ).all()


@pytest.mark.integration
@pytest.mark.parametrize("stage", ["service_url", "wait_ready"])
def test_interrupted_start_cleanup(stage: str) -> None:
    """Production rollback confirms absence before any test safety teardown."""
    image = os.environ.get("OPENENV_OPENSHELL_ECHO_IMAGE_ID")
    if image is None:
        pytest.skip("Set OPENENV_OPENSHELL_ECHO_IMAGE_ID to the validated image ID")
    workspace = os.environ.get("OPENSHELL_WORKSPACE", "default")
    gateway = os.environ.get("OPENSHELL_GATEWAY") or None
    name = f"oe-aee-{uuid4().hex[:8]}"
    provider = OpenShellProvider(
        workspace=workspace,
        gateway=gateway,
        sandbox_name=name,
        command=COMMAND,
        policy=Path(__file__).parent / "images/echo/policy.yaml",
        labels={"openenv-aee": name},
    )
    adapter = connect(gateway=gateway)
    interruption = KeyboardInterrupt()
    try:
        with (
            patch.object(provider, "_connect_adapter", return_value=adapter),
            patch.object(adapter, stage, side_effect=interruption),
            pytest.raises(KeyboardInterrupt) as caught,
        ):
            provider.start_container(image)
        assert caught.value is interruption
        assert provider.state.deleted
        assert provider.state.sandbox_name is None
        with SandboxClient.from_active_cluster(cluster=gateway, timeout=30) as client:
            assert not client.list(
                workspace=workspace, label_selector=f"openenv-aee={name}"
            ).all()
    finally:
        provider.stop_container()
        adapter.close()
