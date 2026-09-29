"""Offline release contracts approving S1a's generated workload-model boundary.

Private SDK imports belong only here and in the future private adapter. These
checks use the installed, hash-pinned wheel without contacting a gateway.
"""

from importlib.metadata import version
from inspect import Parameter, signature

import pytest
from google.protobuf.json_format import ParseDict, ParseError
from openshell import SandboxClient, ServiceExposure
from openshell._proto.openshell_pb2 import SandboxSpec, SandboxTemplate
from openshell._proto.sandbox_pb2 import SandboxPolicy


def test_selected_sdk_release() -> None:
    """An accidentally substituted SDK fails before runtime tests are attempted."""
    assert version("openshell") == "0.1.2"


@pytest.mark.parametrize(
    ("method", "keywords"),
    [
        (
            "create",
            ("workspace", "spec", "name", "labels", "service_exposures"),
        ),
        ("wait_ready", ("workspace", "timeout_seconds")),
        ("delete", ("workspace", "allow_missing")),
        ("wait_deleted", ("workspace", "timeout_seconds", "expected_sandbox_id")),
    ],
)
def test_lifecycle_keywords(method: str, keywords: tuple[str, ...]) -> None:
    """Lifecycle calls retain the workspace and atomic-service/identity contracts."""
    parameters = signature(getattr(SandboxClient, method)).parameters
    assert (
        tuple(
            name
            for name, parameter in parameters.items()
            if parameter.kind == Parameter.KEYWORD_ONLY
        )
        == keywords
    )
    if method == "create":
        assert parameters["workspace"].default == Parameter.empty
        assert parameters["spec"].default is None


def test_workload_and_policy_round_trip() -> None:
    """The selected models carry every required input without a gateway or CLI."""
    policy = SandboxPolicy(
        version=1,
        filesystem={"read_only": ["/usr"], "read_write": ["/workspace"]},
        process={"run_as_user": "sandbox", "run_as_group": "sandbox"},
        landlock={"compatibility": "best_effort"},
    )
    spec = SandboxSpec(
        template=SandboxTemplate(
            image="example.invalid/openenv@sha256:fixture",
            resources={"limits": {"cpu": "2", "memory": "4Gi"}},
        ),
        environment={"OPENENV_MAX_CONCURRENT_ENVS": "8"},
        providers=["github"],
        resource_requirements={"gpu": {"count": 1}},
        policy=policy,
    )
    restored = SandboxSpec.FromString(spec.SerializeToString())
    assert restored == spec
    assert restored.template.image == "example.invalid/openenv@sha256:fixture"
    assert restored.template.resources["limits"] == {"cpu": "2", "memory": "4Gi"}
    assert dict(restored.environment) == {"OPENENV_MAX_CONCURRENT_ENVS": "8"}
    assert list(restored.providers) == ["github"]
    assert restored.resource_requirements.gpu.count == 1
    assert restored.HasField("policy")
    # Upstream SandboxSpec.pyi resolves its cross-module policy type as unknown.
    assert restored.policy == policy  # pyright: ignore[reportUnknownMemberType]
    assert not policy.network_policies
    # Leaving command empty preserves the image's workload for the runtime spike.
    assert not restored.command
    assert ServiceExposure(target_port=8000).service == ""


def test_policy_conversion_rejects_unknown_fields() -> None:
    """Strict protobuf conversion never silently drops unsupported policy input."""
    policy = ParseDict(
        {"version": 1, "filesystem": {"read_write": ["/workspace"]}},
        SandboxPolicy(),
        ignore_unknown_fields=False,
    )
    assert policy.version == 1
    assert list(policy.filesystem.read_write) == ["/workspace"]
    with pytest.raises(ParseError, match="no field named"):
        ParseDict(
            {"filesystem": {"unsupported_access": True}},
            SandboxPolicy(),
            ignore_unknown_fields=False,
        )
