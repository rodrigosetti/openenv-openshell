"""Explicit policy loading and offline schema contracts."""

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

import pytest
from google.protobuf.json_format import MessageToDict
from openshell._proto.openshell_pb2 import SandboxSpec

from openenv_openshell._adapter import CreateRequest
from openenv_openshell._sdk import SDKAdapter
from openenv_openshell.errors import PolicyConfigurationError
from openenv_openshell.policy import load_policy

if TYPE_CHECKING:
    from collections.abc import Mapping

SECRET = "private-policy-sentinel"  # noqa: S105 - Redaction sentinel.


def test_fixture_policy_roundtrip(
    sdk: MagicMock, create_request: CreateRequest
) -> None:
    """The image's actual YAML policy is embedded without a gateway in tests."""
    fixture = Path(__file__).parents[1] / "integration/images/echo/policy.yaml"
    policy = load_policy(fixture)
    assert policy["version"] == 1
    assert "filesystem_policy" not in policy
    assert policy["landlock"] == {"compatibility": "best_effort"}
    SDKAdapter(sdk).create(replace(create_request, policy=policy))
    spec = sdk.create.call_args.kwargs["spec"]
    assert isinstance(spec, SandboxSpec)
    assert MessageToDict(spec.policy, preserving_proto_field_name=True) == policy  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType] - Upstream cross-module stub.


def test_mapping_normalization_is_detached_and_deterministic(tmp_path: Path) -> None:
    """Input key order and YAML versus mappings produce identical output."""
    paths = ["/workspace", "/tmp"]  # noqa: S108 - Sandbox paths.
    source: dict[str, object] = {
        "filesystem_policy": {"read_write": paths, "include_workdir": True},
        "version": 1,
        "network_policies": {},
    }
    path = tmp_path / "policy.yaml"
    path.write_text(
        "version: 1\nnetwork_policies: {}\nfilesystem_policy:\n"
        "  include_workdir: true\n  read_write: [/workspace, /tmp]\n",
        encoding="utf-8",
    )
    result = load_policy(source)
    assert (
        result
        == load_policy(str(path))
        == load_policy(dict(reversed(list(source.items()))))
    )
    paths.append("/secret")
    assert cast("Mapping[str, object]", result["filesystem"])["read_write"] == [
        "/workspace",
        "/tmp",  # noqa: S108 - Sandbox paths.
    ]


def test_network_and_process_normalization() -> None:
    """Authored enum spellings normalize to exact SDK enum names."""
    result = load_policy(
        {
            "version": 1,
            "process": {"run_as_user": "sandbox", "run_as_group": "sandbox"},
            "network_policies": {
                "api": {
                    "name": "api",
                    "binaries": [{"path": "/usr/bin/curl"}],
                    "endpoints": [
                        {
                            "host": "example.com",
                            "port": 443,
                            "tls": "terminate",
                            "access": "read_only",
                            "enforcement": "enforce",
                        }
                    ],
                }
            },
        }
    )
    rules = cast("dict[str, dict[str, object]]", result["network_policies"])
    endpoints = cast("list[dict[str, object]]", rules["api"]["endpoints"])
    assert endpoints[0]["tls"] == "NETWORK_TLS_MODE_TERMINATE"
    assert endpoints[0]["access"] == "NETWORK_ACCESS_PRESET_READ_ONLY"
    assert load_policy(result) == result


@pytest.mark.parametrize(
    "source",
    [
        None,
        [],
        1,
        True,
        {},
        {"version": 2},
        {"version": True},
        {"version": "1"},
        {"version": 1, SECRET: True},
        {"version": 1, "filesystem": None},
        {"version": 1, "filesystem": [], "filesystem_policy": {}},
        {"version": 1, "filesystem": {SECRET: "value"}},
        {"version": 1, "filesystem": {"include_workdir": 1}},
        {"version": 1, "filesystem": {"read_write": "all"}},
        {"version": 1, "filesystem": {"read_only": [False]}},
        {"version": 1, "filesystem": {"read_only": ("/usr",)}},
        {"version": 1, "landlock": {"compatibility": SECRET}},
        {"version": 1, "landlock": {}},
        {"version": 1, "network_policies": []},
        {"version": 1, "network_policies": {"api": {"endpoints": {}}}},
        {"version": 1, "network_policies": {"api": {"endpoints": [{"port": True}]}}},
        {"version": 1, "network_policies": {"api": {"endpoints": [{"port": -1}]}}},
        {"version": 1, "network_policies": {"api": {"endpoints": [{"tls": SECRET}]}}},
        {"version": 1, "network_policies": {"api": {"endpoints": [{"tls": 1}]}}},
        {
            "version": 1,
            "network_policies": {"api": {"endpoints": [{"access": "only"}]}},
        },
        {"version": 1, "process": {"run_as_user": 1}},
        {"version": 1, "process": {"run_as_user": 1.5}},
        {"version": 1, 2: SECRET},
    ],
)
def test_invalid_mapping_is_secret_safe(source: object) -> None:
    """Malformed, unknown, ambiguous or coercible values never broaden policy."""
    with pytest.raises(PolicyConfigurationError) as failure:
        load_policy(source)
    assert SECRET not in str(failure.value)
    assert failure.value.__cause__ is None


@pytest.mark.parametrize(
    "contents",
    [
        "",
        "[]",
        "version: [",
        "version: 1\n---\nversion: 1",
        "version: 1\nversion: 2",
        "version: 1\nfilesystem_policy:\n  read_only: []\n  read_only: [/secret]",
        "version: 1\n2: value",
        "version: 1\n<<: {version: 2}",
        "version: 1\nfilesystem_policy: &policy {}",
        "version: 1\nfilesystem_policy: *policy",
        "version: 1\nprocess: !!python/object:private {}",
        "version: 1\nprocess: 2026-09-30",
    ],
)
def test_invalid_yaml_is_secret_safe(tmp_path: Path, contents: str) -> None:
    """Reject unsafe YAML, duplicate/merge keys, aliases and multiple documents."""
    path = tmp_path / SECRET
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(PolicyConfigurationError) as failure:
        load_policy(path)
    assert SECRET not in str(failure.value)
    assert failure.value.__cause__ is None


def test_missing_unreadable_and_oversized_files(tmp_path: Path) -> None:
    """File errors and excessive input cannot fall back to a default policy."""
    for path in [tmp_path / SECRET, tmp_path]:
        with pytest.raises(PolicyConfigurationError):
            load_policy(path)
    path = tmp_path / "large.yaml"
    path.write_bytes(b" " * (1024 * 1024 + 1))
    with pytest.raises(PolicyConfigurationError):
        load_policy(path)
    path.write_bytes(b"\xff")
    with pytest.raises(PolicyConfigurationError):
        load_policy(path)


def test_recursive_and_deep_mapping() -> None:
    """Caller mappings with cycles or excessive nesting are bounded."""
    cycle: dict[str, object] = {"version": 1}
    cycle["filesystem"] = cycle
    with pytest.raises(PolicyConfigurationError):
        load_policy(cycle)


def test_canonical_enum_names() -> None:
    """Normalized names accepted by ParseDict retain their exact semantics."""
    assert load_policy(
        {
            "version": 1,
            "network_policies": {
                "api": {
                    "endpoints": [{"tls": "NETWORK_TLS_MODE_TERMINATE"}],
                }
            },
        }
    )["network_policies"]
