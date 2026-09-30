"""Public OpenEnv factory contracts with only external I/O replaced."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from websockets.asyncio.client import ClientConnection
from websockets.protocol import State

from openenv_openshell import OpenShellProvider
from openenv_openshell.errors import OpenEnvReadinessTimeout
from tests.fakes import CreateCall, FakeSandboxAdapter
from tests.openenv_client import client_factory


@pytest.mark.parametrize("mode", ["async", "sync"])
def test_public_factory_lifecycle(mode: str) -> None:
    """Upstream bootstrap, protocol, and close retain provider ownership."""
    adapter = FakeSandboxAdapter(service_url="https://route.test/prefix/")
    provider = OpenShellProvider(command=["server"], sandbox_name="chosen")
    health = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    ws = AsyncMock(spec=ClientConnection)
    ws.state = State.OPEN
    ws.recv.side_effect = [
        json.dumps({"type": "observation", "data": {"observation": {}, "done": False}}),
        json.dumps({"type": "observation", "data": {"observation": {"echo": "hello"}}}),
        json.dumps({"type": "state", "data": {"step_count": 1}}),
    ]

    async def run_async() -> None:
        env = await client_factory.from_docker_image(
            "echo:fixture", provider=provider, port=9000, env_vars={"CONTROL": "value"}
        )
        try:
            assert env.base_url == "https://route.test/prefix"
            assert (await env.reset()).observation == {}
            assert (await env.step({"message": "hello"})).observation == {
                "echo": "hello"
            }
            assert (await env.state())["step_count"] == 1
        finally:
            await env.close()
            await env.close()

    with (
        patch.object(provider, "_connect_adapter", return_value=adapter),
        patch("openenv_openshell.provider.httpx.Client", return_value=health),
        patch("openenv.core.env_client.ws_connect", new_callable=AsyncMock) as connect,
    ):
        connect.return_value = ws
        if mode == "async":
            asyncio.run(run_async())
        else:
            env = client_factory.from_docker_image(
                "echo:fixture",
                provider=provider,
                port=9000,
                env_vars={"CONTROL": "value"},
            ).sync()
            try:
                assert env.reset().observation == {}
                assert env.step({"message": "hello"}).observation == {"echo": "hello"}
                assert env.state()["step_count"] == 1
            finally:
                env.close()
                env.close()
        connect.assert_awaited_once_with(
            "wss://route.test/prefix/ws",
            open_timeout=10.0,
            max_size=100 * 1024 * 1024,
            ping_interval=20.0,
            ping_timeout=20.0,
        )
    create = adapter.calls[0]
    assert isinstance(create, CreateCall)
    assert create.request.image == "echo:fixture"
    assert create.request.command == ("server",)
    assert create.request.target_port == 9000  # noqa: PLR2004 - Explicit override.
    assert create.request.environment == {"CONTROL": "value"}
    assert [call.operation for call in adapter.calls] == [
        "create",
        "service_url",
        "wait_ready",
        "delete",
        "wait_deleted",
    ]
    assert provider.state.deleted
    assert adapter.closed
    assert provider.metadata is not None
    assert provider.metadata.ready_at is not None
    assert provider.metadata.deleted_at is not None
    ws.close.assert_awaited_once()
    assert [json.loads(call.args[0])["type"] for call in ws.send.await_args_list] == [
        "reset",
        "step",
        "state",
        "close",
    ]


@pytest.mark.parametrize("stage", ["health", "websocket"])
@pytest.mark.parametrize("mode", ["async", "sync"])
def test_public_factory_failure_cleanup(stage: str, mode: str) -> None:
    """An unresolved factory releases its provider after readiness/connect errors."""
    adapter = FakeSandboxAdapter()
    provider = OpenShellProvider(command=["server"])
    health = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200)))

    async def run_async() -> None:
        await client_factory.from_docker_image("echo:fixture", provider=provider)

    with (
        patch.object(provider, "_connect_adapter", return_value=adapter),
        patch("openenv_openshell.provider.httpx.Client", return_value=health),
        patch("openenv.core.env_client.ws_connect", new_callable=AsyncMock) as connect,
        patch.object(
            provider, "wait_for_ready", wraps=provider.wait_for_ready
        ) as ready,
    ):
        if stage == "health":
            ready.side_effect = OpenEnvReadinessTimeout("Test health timeout")
        else:
            connect.side_effect = OSError("Test connection failure")
        expected = OpenEnvReadinessTimeout if stage == "health" else ConnectionError
        if mode == "async":
            with pytest.raises(expected):
                asyncio.run(run_async())
        else:
            with pytest.raises(expected):
                client_factory.from_docker_image(
                    "echo:fixture", provider=provider
                ).sync()
        assert connect.await_count == (0 if stage == "health" else 1)
    assert provider.state.deleted
    assert provider.state.sandbox_name is None
    assert adapter.closed
    assert [call.operation for call in adapter.calls][-2:] == ["delete", "wait_deleted"]
    health.close()
