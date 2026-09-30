"""Provider input preparation through the pinned SDK without gateway access."""

# pyright: reportPrivateUsage=false

from traceback import format_exception
from typing import cast
from unittest.mock import MagicMock, patch

import pytest

from openenv_openshell import OpenShellProvider, OpenShellResources
from tests.fakes import CreateCall, FakeSandboxAdapter

SECRET = "private-environment-value"  # noqa: S105 - Redaction sentinel.
POLICY: dict[str, object] = {"version": 1}


def test_configured_request_reaches_sdk(sdk: MagicMock) -> None:
    """Configuration and explicit port reach the actual reviewed SDK fields."""
    resources = OpenShellResources(cpu=2.5, memory="8Gi", gpu_count=2)
    provider = OpenShellProvider(
        command=["server", SECRET, "", "argument with spaces"],
        workspace="research",
        sandbox_name="chosen",
        service_name="openenv",
        service_port=8001,
        gateway="registered",
        labels={"openenv.run_id": "run-42", "managed-by": "caller"},
        providers=["github", "huggingface"],
        resources=resources,
        keep_sandbox=True,
        startup_timeout_s=42,
        deletion_timeout_s=12,
    )
    request = provider._create_request(  # noqa: SLF001
        "registry.test/echo@sha256:fixture",
        port=9000,
        env_vars={"TOKEN": SECRET, "EMPTY": ""},
        policy=POLICY,
    )
    with patch(
        "openenv_openshell._sdk.SandboxClient.from_active_cluster", return_value=sdk
    ) as factory:
        adapter = provider._connect_adapter()  # noqa: SLF001
    factory.assert_called_once_with(cluster="registered")
    adapter.create(request)
    args = sdk.create.call_args.kwargs
    assert args["workspace"] == "research"
    assert args["name"] == "chosen"
    assert args["labels"] == {
        "openenv.run_id": "run-42",
        "managed-by": "openenv-openshell",
        "openenv.provider": "openshell",
    }
    assert args["service_exposures"][0].target_port == request.target_port
    assert args["service_exposures"][0].service == "openenv"
    spec = args["spec"]
    assert spec.template.image == request.image
    assert dict(spec.environment) == {"TOKEN": SECRET, "EMPTY": ""}
    assert list(spec.providers) == ["github", "huggingface"]
    assert spec.template.resources["limits"] == {"cpu": "2.5", "memory": "8Gi"}
    assert spec.resource_requirements.gpu.count == resources.gpu_count
    assert spec.policy.version == 1
    assert list(spec.command) == ["server", SECRET, "", "argument with spaces"]
    assert SECRET not in repr(request)


def test_default_request_and_gateway(sdk: MagicMock) -> None:
    """Defaults select the active gateway and an unnamed target-only route."""
    provider = OpenShellProvider(service_port=8080, command=["server"])
    request = provider._create_request("echo:latest", policy=POLICY)  # noqa: SLF001
    assert request.name.startswith("openenv-echo-")
    assert request.target_port == provider.config.service_port
    assert request.workspace == "default"
    assert not request.environment
    assert not request.providers
    assert request.resources is None
    with patch(
        "openenv_openshell._sdk.SandboxClient.from_active_cluster", return_value=sdk
    ) as factory:
        provider._connect_adapter().create(request)  # noqa: SLF001
    factory.assert_called_once_with(cluster=None)
    spec = sdk.create.call_args.kwargs["spec"]
    assert not spec.template.HasField("resources")
    assert not spec.HasField("resource_requirements")
    assert sdk.create.call_args.kwargs["service_exposures"][0].service == ""


@pytest.mark.parametrize("port", [1, 65535])
def test_port_boundaries(port: int) -> None:
    """An explicit target port overrides the configured default at both bounds."""
    request = OpenShellProvider(command=["server"])._create_request(  # noqa: SLF001
        "echo", policy=POLICY, port=port
    )
    assert request.target_port == port


@pytest.mark.parametrize("port", [0, -1, 65536, True, 1.5, SECRET])
def test_invalid_port(port: object, sdk: MagicMock) -> None:
    """Invalid explicit ports fail before any gateway call without echoing input."""
    with pytest.raises(ValueError, match="port") as error:
        OpenShellProvider(command=["server"])._create_request(  # noqa: SLF001
            "echo", policy=POLICY, port=cast("int", port)
        )
    assert SECRET not in "".join(format_exception(error.value))
    sdk.health.assert_not_called()
    sdk.create.assert_not_called()


@pytest.mark.parametrize("image", ["", " ", "echo\x00invalid", 42])
def test_invalid_image(image: object) -> None:
    """Empty or malformed image input fails during local preparation."""
    with pytest.raises(ValueError, match="image"):
        OpenShellProvider(command=["server"])._create_request(  # noqa: SLF001
            cast("str", image), policy=POLICY
        )


@pytest.mark.parametrize(
    "environment",
    [
        {"": SECRET},
        {"INVALID=NAME": SECRET},
        {"INVALID\x00NAME": SECRET},
        {"TOKEN": SECRET + "\x00"},
        {"TOKEN": 42},
        {42: SECRET},
    ],
)
def test_invalid_environment(environment: dict[object, object]) -> None:
    """Malformed environment input never appears in errors or logs."""
    with pytest.raises(ValueError, match="env_vars") as error:
        OpenShellProvider(command=["server"])._create_request(  # noqa: SLF001
            "echo", policy=POLICY, env_vars=cast("dict[str, str]", environment)
        )
    assert SECRET not in "".join(format_exception(error.value))


def test_unknown_options_are_rejected() -> None:
    """Unsupported upstream options cannot silently change execution semantics."""
    with pytest.raises(ValueError, match="Unsupported") as error:
        OpenShellProvider(command=["server"])._create_request(  # noqa: SLF001
            "echo", policy=POLICY, unsupported=SECRET
        )
    assert SECRET not in "".join(format_exception(error.value))


def test_request_detaches_caller_input(caplog: pytest.LogCaptureFixture) -> None:
    """Prepared inputs survive later mutation and keep secrets out of diagnostics."""
    environment = {"TOKEN": SECRET}
    policy: dict[str, object] = {"filesystem": {"read_write": ["/workspace"]}}
    request = OpenShellProvider(command=["server"])._create_request(  # noqa: SLF001
        "echo", policy=policy, env_vars=environment
    )
    environment.clear()
    cast("dict[str, object]", policy["filesystem"]).clear()
    assert request.environment == {"TOKEN": SECRET}
    assert request.policy == {"filesystem": {"read_write": ["/workspace"]}}
    with pytest.raises(TypeError):
        cast("dict[str, str]", request.environment)["TOKEN"] = SECRET
    fake = FakeSandboxAdapter()
    fake.create(request)
    assert SECRET not in repr(fake.calls)
    assert SECRET not in caplog.text
    captured = fake.calls[0]
    assert isinstance(captured, CreateCall)
    assert captured.request.environment == request.environment


@pytest.mark.parametrize("names", [[], ["github-readonly"], ["second", "first"]])
def test_provider_selection_is_explicit_and_detached(
    names: list[str], sdk: MagicMock
) -> None:
    """Only selected instance names reach the wire, without environment discovery."""
    selected = tuple(names)
    provider = OpenShellProvider(providers=names, command=["server"])
    names.append("later-mutation")
    request = provider._create_request(  # noqa: SLF001
        "echo", policy=POLICY, env_vars={"MAX_CONCURRENT_ENVS": "8"}
    )
    provider._connect_adapter().create(request)  # noqa: SLF001
    spec = sdk.create.call_args.kwargs["spec"]
    assert request.providers == selected
    assert tuple(spec.providers) == selected
    assert dict(spec.environment) == {"MAX_CONCURRENT_ENVS": "8"}
    assert not spec.template.environment


@pytest.mark.parametrize(
    "command",
    [
        [],
        "server",
        b"server",
        42,
        [""],
        [" "],
        ["server", 42],
        ["server", SECRET + "\x00"],
    ],
)
def test_invalid_command(command: object, sdk: MagicMock) -> None:
    """Invalid or missing argv fails offline without disclosing argument values."""
    with pytest.raises((TypeError, ValueError), match="command") as error:
        OpenShellProvider(command=cast("list[str]", command))
    assert SECRET not in "".join(format_exception(error.value))
    sdk.health.assert_not_called()
    sdk.create.assert_not_called()


def test_command_is_detached_and_preserved(sdk: MagicMock) -> None:
    """Caller argv is frozen, redacted, and transmitted without shell rewriting."""
    command = ["sh", "-c", 'cd "/app dir" && exec server "$TOKEN"', "", SECRET]
    provider = OpenShellProvider(command=command)
    command.clear()
    request = provider._create_request("echo", policy=POLICY)  # noqa: SLF001
    fake = FakeSandboxAdapter()
    fake.create(request)
    with patch(
        "openenv_openshell._sdk.SandboxClient.from_active_cluster", return_value=sdk
    ):
        provider._connect_adapter().create(request)  # noqa: SLF001
    assert list(sdk.create.call_args.kwargs["spec"].command) == list(request.command)
    assert request.command == provider.config.command
    captured = fake.calls[0]
    assert isinstance(captured, CreateCall)
    assert captured.request.command == request.command
    assert SECRET not in repr(provider.config)
    assert SECRET not in repr(request)
    assert SECRET not in repr(fake.calls)


def test_missing_command_fails_before_gateway(sdk: MagicMock) -> None:
    """Readiness-only configuration is allowed but cannot prepare a workload."""
    provider = OpenShellProvider()
    with pytest.raises(ValueError, match=r"0\.1\.2 requires explicit command"):
        provider._create_request("echo", policy=POLICY)  # noqa: SLF001
    sdk.health.assert_not_called()
    sdk.create.assert_not_called()
