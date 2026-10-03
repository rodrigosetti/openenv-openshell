"""Configuration and sandbox naming tests."""

# pyright: reportPrivateUsage=false

from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest

from openenv_openshell import (
    OpenShellProvider,
    OpenShellProviderConfig,
    OpenShellResources,
)
from tests.fakes import CreateCall, FakeSandboxAdapter


def test_provider_constructor_collects_keyword_configuration() -> None:
    """The public constructor exposes all stable provider settings as keywords."""
    resources = OpenShellResources(cpu=2.5, memory="16Gi", gpu_count=1)
    provider = OpenShellProvider(
        workspace="research",
        sandbox_name="echo-env",
        policy=Path("strict.yaml"),
        service_port=9000,
        service_name="openenv",
        startup_timeout_s=30,
        deletion_timeout_s=15,
        gateway="https://gateway.example",
        keep_sandbox=True,
        labels={"openenv.run_id": "run-42"},
        providers=["github"],
        resources=resources,
    )

    assert provider.config == OpenShellProviderConfig(
        workspace="research",
        sandbox_name="echo-env",
        policy=Path("strict.yaml"),
        service_port=9000,
        service_name="openenv",
        startup_timeout_s=30,
        deletion_timeout_s=15,
        gateway="https://gateway.example",
        keep_sandbox=True,
        labels={"openenv.run_id": "run-42"},
        providers=("github",),
        resources=resources,
    )


@pytest.mark.parametrize("port", [0, -1, 65536, True, 1.5])
def test_service_port_must_be_an_integer_in_range(port: object) -> None:
    """Invalid target ports fail before any gateway operation."""
    with pytest.raises(ValueError, match="service_port"):
        OpenShellProvider(service_port=cast("int", port))


@pytest.mark.parametrize("field", ["startup", "deletion"])
@pytest.mark.parametrize("value", [0.0, -1.0, float("inf"), float("nan")])
def test_timeouts_must_be_positive_and_finite(field: str, value: float) -> None:
    """Every lifecycle deadline must make forward progress."""
    if field == "startup":
        with pytest.raises(ValueError, match="startup_timeout_s"):
            OpenShellProvider(startup_timeout_s=value)
    else:
        with pytest.raises(ValueError, match="deletion_timeout_s"):
            OpenShellProvider(deletion_timeout_s=value)


@pytest.mark.parametrize("cpu", [0.0, -1.0, float("inf"), float("nan"), True])
def test_cpu_must_be_positive_and_finite(cpu: object) -> None:
    """CPU capacity cannot be zero, negative, infinite, or boolean."""
    with pytest.raises(ValueError, match=r"resources\.cpu"):
        OpenShellResources(cpu=cast("float", cpu))


@pytest.mark.parametrize("memory", ["", "0", "0Gi", "-1Gi", "lots"])
def test_memory_must_be_a_positive_quantity(memory: str) -> None:
    """Memory requests retain their SDK unit while rejecting invalid values."""
    with pytest.raises(ValueError, match=r"resources\.memory"):
        OpenShellResources(memory=memory)


@pytest.mark.parametrize("gpu_count", [0, -1, True, 1.5])
def test_gpu_count_must_be_a_positive_integer(gpu_count: object) -> None:
    """A present GPU request must ask for at least one GPU."""
    with pytest.raises(ValueError, match=r"resources\.gpu_count"):
        OpenShellResources(gpu_count=cast("int", gpu_count))


@pytest.mark.parametrize(
    ("argument", "value"),
    [
        ("workspace", " "),
        ("sandbox_name", ""),
        ("sandbox_name", "Upper_case"),
        ("sandbox_name", "-leading"),
        ("sandbox_name", "trailing-"),
        ("sandbox_name", "a" * 64),
        ("service_name", "has spaces"),
        ("gateway", " "),
    ],
)
def test_names_and_locations_are_validated(argument: str, value: str) -> None:
    """Unsafe identifiers and empty location selectors are rejected early."""
    kwargs: Any = {argument: value}
    with pytest.raises(ValueError, match=argument):
        OpenShellProvider(**kwargs)


@pytest.mark.parametrize("name", ["", "a", "0", "a-b", "a" * 19, "openenv-12345678901"])
def test_service_names_follow_the_pinned_routing_contract(name: str) -> None:
    """Unnamed and boundary-length endpoint names are preserved verbatim."""
    assert OpenShellProvider(service_name=name).config.service_name == name
    assert OpenShellProviderConfig(service_name=name).service_name == name


@pytest.mark.parametrize(
    "name",
    [
        "a" * 20,
        "a" * 63,
        "a--b",
        "a---b",
        "-a",
        "a-",
        "Upper",
        "a_b",
        "a.b",
        "é",
        "a\n",
    ],
)
def test_invalid_service_names_never_connect_or_create(name: str) -> None:
    """Gateway-invalid endpoints fail before startup can acquire a client."""
    with patch.object(OpenShellProvider, "_connect_adapter") as connect:
        with pytest.raises(ValueError, match="service_name"):
            OpenShellProvider(service_name=name, command=["server"]).start_container(
                "image"
            )
        connect.assert_not_called()
    with pytest.raises(ValueError, match="service_name"):
        OpenShellProviderConfig(service_name=name)


def test_mutable_configuration_inputs_are_defensively_copied() -> None:
    """Caller mutations cannot alter configuration after construction."""
    labels = {"openenv.run_id": "before"}
    providers = ["github"]
    policy: dict[str, object] = {"filesystem": {"read": ["/workspace"]}}
    provider = OpenShellProvider(labels=labels, providers=providers, policy=policy)

    labels["openenv.run_id"] = "after"
    providers.append("gitlab")
    cast("dict[str, object]", policy["filesystem"])["read"] = []

    assert provider.config.labels == {"openenv.run_id": "before"}
    assert provider.config.providers == ("github",)
    assert provider.config.policy == {"filesystem": {"read": ["/workspace"]}}
    with pytest.raises(TypeError):
        provider.config.labels["other"] = "value"  # pyright: ignore[reportIndexIssue]


def test_config_policy_reads_cannot_mutate_nested_snapshot() -> None:
    """Nested edits affect only the inspected copy, including mapping views."""
    source = {"version": 1, "filesystem": {"read_write": ["/workspace"]}}
    config = OpenShellProviderConfig(policy=source)
    policy = config.policy
    assert isinstance(policy, Mapping)
    filesystem = cast("dict[str, object]", policy["filesystem"])
    cast("list[str]", filesystem["read_write"]).append("/")
    filesystem["include_workdir"] = True
    for value in policy.values():
        if isinstance(value, dict):
            value.clear()  # pyright: ignore[reportUnknownMemberType]

    assert dict(policy) == source
    assert len(policy) == len(source)
    with pytest.raises(KeyError):
        _ = policy["missing"]
    with pytest.raises(TypeError):
        policy["version"] = 2  # pyright: ignore[reportIndexIssue]


@pytest.mark.parametrize(
    "labels",
    [
        {"api_token": "redacted"},
        {"api-key": "redacted"},
        {"openenv.prompt": "private"},
        {"openenv.task_content": "private"},
        {"openenv.user_data": "private"},
        {"bad key": "value"},
        {"openenv.run": "line\nbreak"},
    ],
)
def test_sensitive_or_malformed_labels_are_rejected(labels: dict[str, str]) -> None:
    """Labels cannot advertise secret/private content or unsafe metadata."""
    with pytest.raises(ValueError, match="label"):
        OpenShellProvider(labels=labels)


def test_label_and_provider_types_are_checked_at_runtime() -> None:
    """Badly typed dynamic input fails with an actionable boundary error."""
    with pytest.raises(TypeError, match="labels"):
        OpenShellProvider(labels=cast("dict[str, str]", {"key": 3}))
    with pytest.raises(TypeError, match="providers"):
        OpenShellProvider(providers=cast("list[str]", "github"))
    with pytest.raises(ValueError, match="providers"):
        OpenShellProvider(providers=[" "])


def test_generated_sandbox_name_is_safe_and_human_readable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Image syntax is removed while its readable basename is preserved."""

    def token_hex(_byte_count: int) -> str:
        return "a7f213"

    monkeypatch.setattr("openenv_openshell.provider.secrets.token_hex", token_hex)
    provider = OpenShellProvider()

    generated = provider._sandbox_name_for_image(  # noqa: SLF001
        "registry.example/team/My.Coding_ENV:latest@sha256:deadbeef"
    )

    assert generated == "openenv-my-c-a7f213"


def test_generated_name_is_bounded_and_has_a_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Long or punctuation-only image basenames still create safe names."""

    def token_hex(_byte_count: int) -> str:
        return "abcdef"

    monkeypatch.setattr("openenv_openshell.provider.secrets.token_hex", token_hex)
    provider = OpenShellProvider()

    long_name = provider._sandbox_name_for_image("x" * 100)  # noqa: SLF001
    fallback = provider._sandbox_name_for_image("registry.example/!!!:latest")  # noqa: SLF001

    assert len(long_name) == 19  # noqa: PLR2004 - Gateway name limit.
    assert fallback == "openenv-env-abcdef"


@pytest.mark.parametrize(
    ("image", "prefix"),
    [
        ("sha256:" + "a" * 64, "sha2"),
        ("registry.example/echo-env:latest@sha256:deadbeef", "echo"),
        ("registry.example/abcd-ef:latest", "abcd"),
        ("registry.example/a:latest", "a"),
        ("registry.example/!!!:latest", "env"),
        ("registry.example/環境:latest", "env"),
    ],
)
def test_generated_name_fits_gateway_limit(
    image: str, prefix: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """IDs, digest references, and sanitized basenames fit the gateway limit."""

    def token_hex(byte_count: int) -> str:
        assert byte_count == 3  # noqa: PLR2004 - Preserve the random suffix entropy.
        return "abcdef"

    monkeypatch.setattr("openenv_openshell.provider.secrets.token_hex", token_hex)
    provider = OpenShellProvider()
    name = provider._sandbox_name_for_image(image)  # noqa: SLF001

    assert name == f"openenv-{prefix}-abcdef"
    assert len(name) <= 19  # noqa: PLR2004 - Gateway name limit.


def test_explicit_sandbox_name_wins_over_generated_name() -> None:
    """A valid caller-selected name is returned unchanged."""
    provider = OpenShellProvider(sandbox_name="chosen-name")

    assert provider._sandbox_name_for_image("ignored:latest") == "chosen-name"  # noqa: SLF001


@pytest.mark.parametrize("length", [20, 63, 64])
def test_oversized_explicit_sandbox_names_never_connect(length: int) -> None:
    """Reject gateway-invalid lengths before obtaining a client or creating."""
    with (
        patch("openenv_openshell.provider.connect") as connect,
        pytest.raises(ValueError, match="sandbox_name must be at most 19"),
    ):
        OpenShellProvider(command=["server"], sandbox_name="a" * length)
    connect.assert_not_called()


def test_explicit_sandbox_name_at_gateway_limit_is_preserved() -> None:
    """The valid 19-character boundary reaches create unchanged."""
    name = "a" * 19
    adapter = FakeSandboxAdapter()
    provider = OpenShellProvider(command=["server"], sandbox_name=name)
    with patch.object(provider, "_connect_adapter", return_value=adapter):
        provider.start_container("image")
    call = adapter.calls[0]
    assert isinstance(call, CreateCall)
    assert call.request.name == name


@pytest.mark.parametrize("name", ["", "openenv", "a" * 63])
def test_service_name_validation_remains_independent(name: str) -> None:
    """The sandbox fix preserves existing local service-name acceptance."""
    assert OpenShellProvider(service_name=name).config.service_name == name
