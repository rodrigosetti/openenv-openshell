"""Successful provider lifecycle contracts without a gateway or network sockets."""

import re
from dataclasses import asdict, replace
from unittest.mock import MagicMock, patch

import httpx
import pytest

from openenv_openshell import (
    OpenShellProvider,
    OpenShellResources,
    OpenShellRunMetadata,
)
from openenv_openshell.metadata import ProviderState
from tests.fakes import (
    CreateCall,
    DeleteCall,
    FakeDeletion,
    FakeSandbox,
    FakeSandboxAdapter,
    ServiceUrlCall,
    WaitDeletedCall,
    WaitReadyCall,
)


@pytest.mark.parametrize("service_name", ["", "openenv"])
@pytest.mark.parametrize("port", [None, 1, 9000, 65535])
def test_configured_startup_mapping(service_name: str, port: int | None) -> None:
    """Public startup preserves caller inputs and create-time routing provenance."""
    image = "registry.test/echo@sha256:fixture"
    url = "https://route.test/a%2Fb/"
    created = FakeSandbox("chosen", "original-id", {service_name: url})
    adapter = FakeSandboxAdapter(
        create_result=created,
        ready_result=FakeSandbox("chosen", "original-id"),
        service_url=url,
        delete_result=FakeDeletion("replacement-id"),
    )
    command = ["launcher", "", "two words", "--port=8000"]
    labels = {"openenv.run_id": "run-42", "managed-by": "caller"}
    providers = ["github-readonly", "huggingface"]
    policy: dict[str, object] = {"version": 1}
    resources = OpenShellResources(cpu=2.5, memory="8Gi", gpu_count=2)
    provider = OpenShellProvider(
        command=command,
        workspace="research",
        sandbox_name="chosen",
        service_name=service_name,
        service_port=8080,
        startup_timeout_s=17,
        deletion_timeout_s=19,
        labels=labels,
        providers=providers,
        resources=resources,
        policy=policy,
    )
    command.clear()
    labels.clear()
    providers.clear()
    policy.clear()
    environment = {"PORT": "8000", "EMPTY": "", "MAX_CONCURRENT_ENVS": "8"}
    with patch.object(provider, "_connect_adapter", return_value=adapter) as connect:
        assert provider.start_container(image, port=port, env_vars=environment) == url
    connect.assert_called_once_with()
    environment.clear()
    create = adapter.calls[0]
    assert isinstance(create, CreateCall)
    request = create.request
    assert request.image == image
    assert request.workspace == "research"
    assert request.name == "chosen"
    assert request.command == ("launcher", "", "two words", "--port=8000")
    assert request.environment == {
        "PORT": "8000",
        "EMPTY": "",
        "MAX_CONCURRENT_ENVS": "8",
    }
    assert request.target_port == (8080 if port is None else port)
    assert request.service_name == service_name
    assert request.labels == {
        "managed-by": "openenv-openshell",
        "openenv.provider": "openshell",
        "openenv.run_id": "run-42",
    }
    assert request.providers == ("github-readonly", "huggingface")
    assert request.resources == resources
    assert request.policy == {"version": 1}
    assert adapter.calls == [
        create,
        ServiceUrlCall(created, service_name),
        WaitReadyCall("chosen", "research", 17),
    ]
    assert provider.state == ProviderState(
        sandbox_name="chosen",
        sandbox_id="original-id",
        image=image,
        base_url=url,
        created=True,
    )
    assert not adapter.closed
    metadata = provider.metadata
    assert metadata is not None
    assert (
        metadata.sandbox_name,
        metadata.sandbox_id,
        metadata.workspace,
        metadata.image,
        metadata.service_url,
    ) == (request.name, created.sandbox_id, request.workspace, request.image, url)
    provider.stop_container()
    assert adapter.calls[-2:] == [
        DeleteCall("chosen", "research"),
        WaitDeletedCall("chosen", "research", "original-id", 19),
    ]
    assert adapter.closed
    assert provider.state == ProviderState(deleted=True)
    assert provider.metadata is not None
    assert provider.metadata.deleted_at is not None
    assert provider.metadata == replace(
        metadata, deleted_at=provider.metadata.deleted_at
    )


def test_default_startup_and_health(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default startup, health, and deletion retain only non-secret provenance."""
    adapter = FakeSandboxAdapter()
    secret = "lifecycle-private-sentinel"  # noqa: S105 - Redaction sentinel.
    provider = OpenShellProvider(command=["server", secret])
    assert provider.state == ProviderState()
    assert provider.metadata is None
    assert adapter.calls == []

    def health(request: httpx.Request) -> httpx.Response:
        assert [call.operation for call in adapter.calls] == [
            "create",
            "service_url",
            "wait_ready",
        ]
        assert provider.state.created
        assert not provider.state.ready
        assert str(request.url) == "https://sandbox-123.openshell.localhost/health"
        return httpx.Response(200)

    client = httpx.Client(transport=httpx.MockTransport(health))
    with (
        patch.object(provider, "_connect_adapter", return_value=adapter),
        patch("openenv_openshell.provider.httpx.Client", return_value=client),
    ):
        monkeypatch.setattr("openenv_openshell.provider.monotonic", lambda: 100.0)
        url = provider.start_container(
            "registry.test/Echo_Env:latest", env_vars={"TOKEN": secret}
        )
        create = adapter.calls[0]
        assert isinstance(create, CreateCall)
        request = create.request
        assert re.fullmatch(r"openenv-echo-env-[0-9a-f]{6}", request.name)
        assert request.workspace == "default"
        assert request.target_port == 8000  # noqa: PLR2004 - Specified default port.
        assert request.service_name == ""
        assert request.command == ("server", secret)
        assert request.environment == {"TOKEN": secret}
        assert request.providers == ()
        assert request.resources is None
        assert request.policy is None
        assert request.labels == {
            "managed-by": "openenv-openshell",
            "openenv.provider": "openshell",
        }
        assert adapter.calls[2] == WaitReadyCall(request.name, "default", 120)
        assert provider.state.sandbox_name == request.name
        created = provider.metadata
        assert created is not None
        assert created.ready_at is None
        assert created.deleted_at is None
        provider.wait_for_ready(url)
    assert provider.state.ready
    assert provider.state.created
    assert not provider.state.deleted
    assert client.is_closed
    assert not adapter.closed
    assert_healthy_cleanup(provider, adapter, created, secret)


def assert_healthy_cleanup(
    provider: OpenShellProvider,
    adapter: FakeSandboxAdapter,
    created: OpenShellRunMetadata,
    secret: str,
) -> None:
    """Verify deletion follows health and preserves immutable, non-secret evidence."""
    healthy = provider.metadata
    assert healthy is not None
    assert healthy.ready_at is not None
    assert healthy.created_at <= healthy.ready_at

    def close_after_deletion() -> None:
        assert adapter.calls[-2:] == [
            DeleteCall(created.sandbox_name, "default"),
            WaitDeletedCall(created.sandbox_name, "default", "sandbox-123", 60),
        ]
        assert provider.state.deleted
        close()

    close = adapter.close
    with patch.object(adapter, "close", side_effect=close_after_deletion) as closed:
        provider.stop_container()
        closed.assert_called_once_with()
    assert adapter.closed
    assert provider.state == ProviderState(deleted=True)
    stopped = provider.metadata
    assert stopped is not None
    assert stopped.deleted_at is not None
    assert healthy.ready_at <= stopped.deleted_at
    assert stopped == replace(healthy, deleted_at=stopped.deleted_at)
    assert created.ready_at is None
    assert created.deleted_at is None
    assert secret not in repr(asdict(stopped))
    assert {"command", "environment", "providers", "policy"}.isdisjoint(asdict(stopped))
    calls = list(adapter.calls)
    provider.stop_container()
    assert adapter.calls == calls
    assert provider.metadata is stopped


@pytest.mark.parametrize("service_name", ["", "named"])
def test_public_startup_selects_exact_sdk_route(
    sdk: MagicMock, service_name: str
) -> None:
    """The production adapter retains the selected route lost by wait_ready."""
    provider = OpenShellProvider(
        command=["server"],
        gateway="registered",
        sandbox_name="sandbox",
        service_name=service_name,
    )
    expected_url = "https://named.test" if service_name else "https://route.test"
    with patch(
        "openenv_openshell._sdk.SandboxClient.from_active_cluster", return_value=sdk
    ) as factory:
        assert provider.start_container("echo:latest") == expected_url
    factory.assert_called_once_with(cluster="registered")
    assert [call[0] for call in sdk.mock_calls] == ["health", "create", "wait_ready"]
    exposure = sdk.create.call_args.kwargs["service_exposures"][0]
    assert exposure.service == service_name
    assert exposure.target_port == provider.config.service_port
    assert list(sdk.create.call_args.kwargs["spec"].command) == ["server"]
    assert provider.state.base_url == expected_url
    assert provider.state.sandbox_id == "identity"
    assert not provider.state.ready
    sdk.wait_ready.assert_called_once_with(
        "sandbox", workspace="default", timeout_seconds=120
    )
    provider.stop_container()
    assert [call[0] for call in sdk.mock_calls] == [
        "health",
        "create",
        "wait_ready",
        "delete",
        "wait_deleted",
        "close",
    ]
    sdk.delete.assert_called_once_with(
        "sandbox", workspace="default", allow_missing=True
    )
    sdk.wait_deleted.assert_called_once_with(
        "sandbox",
        workspace="default",
        expected_sandbox_id="identity",
        timeout_seconds=60,
    )
    assert provider.state == ProviderState(deleted=True)
