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
    assert not spec.command
    assert SECRET not in repr(request)


def test_default_request_and_gateway(sdk: MagicMock) -> None:
    """Defaults select the active gateway and an unnamed target-only route."""
    provider = OpenShellProvider(service_port=8080)
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
    request = OpenShellProvider()._create_request(  # noqa: SLF001
        "echo", policy=POLICY, port=port
    )
    assert request.target_port == port


@pytest.mark.parametrize("port", [0, -1, 65536, True, 1.5, SECRET])
def test_invalid_port(port: object, sdk: MagicMock) -> None:
    """Invalid explicit ports fail before any gateway call without echoing input."""
    with pytest.raises(ValueError, match="port") as error:
        OpenShellProvider()._create_request(  # noqa: SLF001
            "echo", policy=POLICY, port=cast("int", port)
        )
    assert SECRET not in "".join(format_exception(error.value))
    sdk.health.assert_not_called()
    sdk.create.assert_not_called()


@pytest.mark.parametrize("image", ["", " ", "echo\x00invalid", 42])
def test_invalid_image(image: object) -> None:
    """Empty or malformed image input fails during local preparation."""
    with pytest.raises(ValueError, match="image"):
        OpenShellProvider()._create_request(  # noqa: SLF001
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
        OpenShellProvider()._create_request(  # noqa: SLF001
            "echo", policy=POLICY, env_vars=cast("dict[str, str]", environment)
        )
    assert SECRET not in "".join(format_exception(error.value))


def test_unknown_options_are_rejected() -> None:
    """Unsupported upstream options cannot silently change execution semantics."""
    with pytest.raises(ValueError, match="Unsupported") as error:
        OpenShellProvider()._create_request("echo", policy=POLICY, unsupported=SECRET)  # noqa: SLF001
    assert SECRET not in "".join(format_exception(error.value))


def test_request_detaches_caller_input(caplog: pytest.LogCaptureFixture) -> None:
    """Prepared inputs survive later mutation and keep secrets out of diagnostics."""
    environment = {"TOKEN": SECRET}
    policy: dict[str, object] = {"filesystem": {"read_write": ["/workspace"]}}
    request = OpenShellProvider()._create_request(  # noqa: SLF001
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
