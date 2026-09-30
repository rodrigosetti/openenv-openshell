"""SEC4: explicit policy gates the production adapter's live create path."""

from __future__ import annotations

import logging
import os
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch
from uuid import uuid4

import pytest
from google.protobuf.json_format import MessageToDict
from openshell import SandboxClient, SandboxRef

from openenv_openshell._adapter import CreateRequest
from openenv_openshell._sdk import SDKAdapter
from openenv_openshell.errors import PolicyConfigurationError
from openenv_openshell.policy import load_policy
from tests.integration.test_protocol_spike import COMMAND, probe_protocol

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from openshell import ServiceExposure
    from openshell._proto.openshell_pb2 import SandboxSpec

logger = logging.getLogger(__name__)


@pytest.mark.integration
def test_policy_prevents_execution(tmp_path: Path) -> None:
    """Invalid input sends no create; a valid control runs routed EchoEnv.

    Only the test supplies the S3a command at the SDK boundary, since automatic
    image command resolution is pending S6a/P4. All policy translation and
    atomic service creation use the production adapter with a real client.
    """
    image = os.environ.get("OPENENV_OPENSHELL_ECHO_IMAGE_ID")
    if image is None:
        pytest.skip("Set OPENENV_OPENSHELL_ECHO_IMAGE_ID to the validated image ID")
    workspace = os.environ.get("OPENSHELL_WORKSPACE", "default")
    name = f"oe-sec4-{uuid4().hex[:8]}"
    label = f"openenv-sec4={name}"
    fixture = Path(__file__).parent / "images/echo/policy.yaml"
    policy = load_policy(fixture)
    request = CreateRequest(
        workspace=workspace,
        name=name,
        image=image,
        environment={},
        service_name="",
        target_port=8000,
        labels={"openenv-sec4": name},
        providers=(),
        resources=None,
        policy=policy,
    )
    invalid_yaml = tmp_path / "invalid-policy.yaml"
    invalid_yaml.write_text("version: 1\nversion: 2\n", encoding="utf-8")
    with SandboxClient.from_active_cluster(timeout=30) as client:
        adapter = SDKAdapter(client)
        real_create = client.create

        def create_workload(
            *,
            workspace: str,
            name: str,
            spec: SandboxSpec,
            labels: Mapping[str, str],
            service_exposures: Sequence[ServiceExposure],
        ) -> SandboxRef:
            # Assert policy is already present when the workload is submitted.
            assert spec.HasField("policy")
            actual = MessageToDict(spec.policy, preserving_proto_field_name=True)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType] - Upstream cross-module stub.
            assert actual == policy
            spec.command.extend(COMMAND)
            return real_create(
                workspace=workspace,
                name=name,
                spec=spec,
                labels=labels,
                service_exposures=service_exposures,
            )

        sandbox_id: str | None = None
        try:
            with patch.object(client, "create", side_effect=create_workload) as create:
                # Exercise both the source loader and direct adapter inputs.
                for source in (invalid_yaml, {"version": 1, "unknown": True}):
                    with pytest.raises(PolicyConfigurationError):
                        adapter.create(replace(request, policy=load_policy(source)))
                invalid_policies: list[dict[str, object]] = [
                    {"version": 2},
                    {"version": "1"},
                    {"version": 1, "filesystem": {"include_workdir": 1}},
                    {"version": 1, "landlock": {"compatibility": "invalid"}},
                ]
                for invalid in invalid_policies:
                    with pytest.raises(PolicyConfigurationError):
                        adapter.create(replace(request, policy=invalid))
                create.assert_not_called()
                assert not client.list(workspace=workspace, label_selector=label).all()
                logger.info("Invalid policies sent no create RPC; no workload exists")

                created = adapter.create(request)
                sandbox_id = created.sandbox_id
                create.assert_called_once()
                url = adapter.service_url(created, "")
                assert url is not None
                ready = adapter.wait_ready(name, workspace=workspace, timeout_s=120)
                assert ready.sandbox_id == sandbox_id
                probe_protocol(url)
                logger.info(
                    "Valid initial policy control executed EchoEnv successfully"
                )
        finally:
            # Also covers a create whose response was lost and failed assertions.
            deletion = adapter.delete(name, workspace=workspace)
            expected_id = sandbox_id or deletion.sandbox_id
            if expected_id is not None:
                adapter.wait_deleted(
                    name,
                    workspace=workspace,
                    expected_sandbox_id=expected_id,
                    timeout_s=60,
                )
            else:
                assert deletion.outcome in {"completed", "already_absent"}
            assert not client.list(workspace=workspace, label_selector=label).all()
            logger.info("SEC4 sandbox %s deletion verified", name)
