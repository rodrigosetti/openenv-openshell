"""Canonical explicit-policy provenance over offline provider runs."""

from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import cast
from unittest.mock import patch

import httpx
import pytest

from openenv_openshell import OpenShellProvider
from openenv_openshell.errors import PolicyConfigurationError, SandboxReadinessError
from openenv_openshell.policy import load_policy, policy_digest
from tests.fakes import CreateCall, FakeSandboxAdapter


def test_canonical_policy_digest(tmp_path: Path) -> None:
    """Paths, mappings, field aliases, and YAML formatting converge."""
    path = tmp_path / "policy.yaml"
    path.write_text(
        "# Formatting is not provenance\nversion: 1\nfilesystem_policy:\n"
        "  read_only: [/usr, /é]\nlandlock: {compatibility: best_effort}\n",
        encoding="utf-8",
    )
    normalized = load_policy(path)
    equivalent = load_policy(
        {
            "landlock": {"compatibility": "best_effort"},
            "filesystem": {"read_only": ["/usr", "/é"]},
            "version": 1,
        }
    )
    canonical = (
        '{"filesystem":{"read_only":["/usr","/é"]},'
        '"landlock":{"compatibility":"best_effort"},"version":1}'
    )
    expected = sha256(canonical.encode("utf-8")).hexdigest()
    assert policy_digest(normalized) == policy_digest(equivalent) == expected
    assert len(expected) == 64  # noqa: PLR2004 - SHA-256 hex length.
    assert policy_digest(load_policy({"version": 1})) != expected
    assert (
        policy_digest(
            load_policy(
                {
                    "version": 1,
                    "filesystem": {"read_only": ["/é", "/usr"]},
                    "landlock": {"compatibility": "best_effort"},
                }
            )
        )
        != expected
    )


def test_enum_spellings_have_identical_digests() -> None:
    """Authored and canonical network enum spellings hash the same policy."""

    def digest(tls: str) -> str:
        return policy_digest(
            load_policy(
                {
                    "version": 1,
                    "network_policies": {"api": {"endpoints": [{"tls": tls}]}},
                }
            )
        )

    assert digest("terminate") == digest("NETWORK_TLS_MODE_TERMINATE")
    assert digest("terminate") != digest("passthrough")


@pytest.mark.parametrize("explicit", [False, True])
def test_metadata_attests_to_submitted_policy_only(*, explicit: bool) -> None:
    """The submitted snapshot survives health and deletion without raw content."""
    private_path = "/private-policy-sentinel"
    source: dict[str, object] = {
        "version": 1,
        "filesystem_policy": {"read_only": [private_path]},
    }
    provider = OpenShellProvider(
        command=["server"], policy=source if explicit else None
    )
    adapter = FakeSandboxAdapter()
    source.clear()
    with patch.object(provider, "_connect_adapter", return_value=adapter):
        url = provider.start_container("image")
    create = adapter.calls[0]
    assert isinstance(create, CreateCall)
    expected = (
        None if create.request.policy is None else policy_digest(create.request.policy)
    )
    assert (expected is not None) == explicit
    created = provider.metadata
    assert created is not None
    assert created.policy_digest == expected
    assert private_path not in repr(created)
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    with patch("openenv_openshell.provider.httpx.Client", return_value=client):
        provider.wait_for_ready(url)
    assert provider.metadata is not None
    assert provider.metadata.policy_digest == expected
    provider.stop_container()
    assert provider.metadata is not None
    assert provider.metadata.policy_digest == expected
    assert provider.metadata.deleted_at is not None


def test_policy_digest_retained_after_failed_start() -> None:
    """Rollback retains submitted policy evidence even when readiness fails."""
    policy = {"version": 1}
    provider = OpenShellProvider(command=["server"], policy=policy)
    adapter = FakeSandboxAdapter(failures={"wait_ready": RuntimeError("failed")})
    with (
        patch.object(provider, "_connect_adapter", return_value=adapter),
        pytest.raises(SandboxReadinessError),
    ):
        provider.start_container("image")
    assert provider.metadata is not None
    assert provider.metadata.policy_digest == policy_digest(load_policy(policy))
    assert provider.metadata.deleted_at is not None


def test_inspected_policy_cannot_change_repeated_startup(tmp_path: Path) -> None:
    """Nested filesystem/network edits never change submitted policy or digest."""
    source: dict[str, object] = {
        "version": 1,
        "filesystem": {"read_write": ["/workspace"]},
        "network_policies": {
            "api": {"endpoints": [{"host": "example.com", "port": 443}]}
        },
    }
    path = tmp_path / "policy.yaml"
    path.write_text(
        "version: 1\nfilesystem_policy: {read_write: [/workspace]}\n"
        "network_policies:\n  api:\n    endpoints: [{host: example.com, port: 443}]\n",
        encoding="utf-8",
    )
    expected = load_policy(path)
    provider = OpenShellProvider(command=["server"], policy=source)
    source.clear()
    for _ in range(2):
        configured = provider.config.policy
        assert isinstance(configured, Mapping)
        inspected = dict(configured)
        filesystem = cast("dict[str, list[str]]", inspected["filesystem"])
        filesystem["read_write"].append("/")
        network = cast("dict[str, dict[str, object]]", inspected["network_policies"])
        endpoints = cast("list[dict[str, object]]", network["api"]["endpoints"])
        endpoints[0]["host"] = "unapproved.example"
        network["other"] = {"endpoints": []}
        adapter = FakeSandboxAdapter()
        with patch.object(provider, "_connect_adapter", return_value=adapter):
            provider.start_container("image")
        create = adapter.calls[0]
        assert isinstance(create, CreateCall)
        assert create.request.policy == expected
        assert provider.metadata is not None
        assert provider.metadata.policy_digest == policy_digest(expected)
        provider.stop_container()


def test_config_snapshot_preserves_invalid_tuple_input() -> None:
    """Defensive inspection must not convert invalid public tuples into lists."""
    provider = OpenShellProvider(
        command=["server"],
        policy={"version": 1, "filesystem": {"read_only": ("/usr",)}},
    )
    with (
        patch.object(provider, "_connect_adapter") as connect,
        pytest.raises(PolicyConfigurationError),
    ):
        provider.start_container("image")
    connect.assert_not_called()


def test_path_policy_is_loaded_again_on_each_start(tmp_path: Path) -> None:
    """Path configuration retains load-at-start semantics rather than file bytes."""
    path = tmp_path / "policy.yaml"
    provider = OpenShellProvider(command=["server"], policy=path)
    digests: list[str | None] = []
    for directory in ["/workspace", "/app"]:
        path.write_text(
            f"version: 1\nfilesystem: {{read_only: [{directory}]}}\n",
            encoding="utf-8",
        )
        expected = load_policy(path)
        adapter = FakeSandboxAdapter()
        with patch.object(provider, "_connect_adapter", return_value=adapter):
            provider.start_container("image")
        create = adapter.calls[0]
        assert isinstance(create, CreateCall)
        assert create.request.policy == expected
        assert provider.metadata is not None
        assert provider.metadata.policy_digest == policy_digest(expected)
        digests.append(provider.metadata.policy_digest)
        provider.stop_container()
    assert digests[0] != digests[1]
