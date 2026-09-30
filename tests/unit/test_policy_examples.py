"""Release-schema and security-posture contracts for authored policy examples."""

from dataclasses import replace
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

import pytest
from google.protobuf.json_format import MessageToDict
from openshell._proto.openshell_pb2 import SandboxSpec

from openenv_openshell._adapter import CreateRequest
from openenv_openshell._sdk import SDKAdapter
from openenv_openshell.policy import load_policy

_ROOT = Path(__file__).parents[2]
_EXAMPLES = _ROOT / "examples/policies"
_STRICT_PATHS = {
    "read_only": ["/bin", "/usr", "/lib", "/etc", "/proc", "/dev/urandom", "/app"],
    "read_write": ["/workspace", "/tmp", "/dev/null"],  # noqa: S108 - Sandbox paths.
}


@pytest.mark.parametrize(
    "filename", ["deny-all.yaml", "hf-minimal.yaml", "image-compatible.yaml"]
)
def test_example_create_policy_roundtrip(
    filename: str, sdk: MagicMock, create_request: CreateRequest
) -> None:
    """Every shipped YAML strictly converts to the pinned release's wire model."""
    policy = load_policy(_EXAMPLES / filename)
    assert policy["version"] == 1
    SDKAdapter(sdk).create(replace(create_request, policy=policy))
    spec = sdk.create.call_args.kwargs["spec"]
    assert isinstance(spec, SandboxSpec)
    assert spec.HasField("policy")
    assert MessageToDict(spec.policy, preserving_proto_field_name=True) == policy  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType] - Upstream cross-module stub.
    assert load_policy(policy) == policy


@pytest.mark.parametrize("filename", ["deny-all.yaml", "hf-minimal.yaml"])
def test_strict_example_posture(filename: str) -> None:
    """Strict examples cannot add workdir writes or degrade Landlock silently."""
    policy = load_policy(_EXAMPLES / filename)
    filesystem = cast("dict[str, object]", policy["filesystem"])
    # False protobuf scalars are omitted on serialization.
    assert filesystem.get("include_workdir", False) is False
    assert filesystem == _STRICT_PATHS
    assert policy["landlock"] == {"compatibility": "hard_requirement"}
    assert policy["process"] == {
        "run_as_user": "sandbox",
        "run_as_group": "sandbox",
    }
    assert set(policy) == {"version", "filesystem", "landlock", "process"} | (
        {"network_policies"} if filename == "hf-minimal.yaml" else set()
    )


def test_huggingface_example_limits_egress() -> None:
    """Only the reviewed binary/host may make enforced read-only REST requests."""
    policy = load_policy(_EXAMPLES / "hf-minimal.yaml")
    assert policy["network_policies"] == {
        "huggingface-read": {
            "name": "huggingface-read",
            "binaries": [{"path": "/usr/bin/curl"}],
            "endpoints": [
                {
                    "host": "huggingface.co",
                    "port": 443,
                    "protocol": "rest",
                    "enforcement": "NETWORK_ENFORCEMENT_MODE_ENFORCE",
                    "access": "NETWORK_ACCESS_PRESET_READ_ONLY",
                }
            ],
        }
    }


def test_image_compatibility_example_matches_reviewed_probe() -> None:
    """The compatibility example retains the documented fixture's broader posture."""
    policy = load_policy(_EXAMPLES / "image-compatible.yaml")
    assert policy == load_policy(_ROOT / "tests/integration/images/echo/policy.yaml")
    assert policy["landlock"] == {"compatibility": "best_effort"}
    assert cast("dict[str, object]", policy["filesystem"])["include_workdir"] is True
    assert "process" not in policy
    assert not policy.get("network_policies")


def test_image_selection_omits_policy(
    sdk: MagicMock, create_request: CreateRequest
) -> None:
    """Image/default resolution needs absence, never an empty explicit policy."""
    SDKAdapter(sdk).create(replace(create_request, policy=None))
    spec = sdk.create.call_args.kwargs["spec"]
    assert isinstance(spec, SandboxSpec)
    assert not spec.HasField("policy")
