"""I2 EchoEnv E2E through the unmodified OpenEnv client and owned runtime."""

import asyncio
import ssl
from http import HTTPStatus

import httpx
import pytest
from openshell import SandboxClient

from tests.integration._runtime import Runtime
from tests.openenv_client import client_factory

# A real ASGI workload that reports receipt of /ws before accepting its upgrade.
# This makes cancellation during the actual gateway-routed handshake deterministic.
PENDING_HANDSHAKE_SERVER = """
import asyncio
import uvicorn
from starlette.applications import Starlette
from starlette.responses import Response
from starlette.routing import Route, WebSocketRoute

connecting = False

async def health(request):
    return Response(status_code=200)

async def status(request):
    return Response(status_code=200 if connecting else 409)

async def websocket(socket):
    global connecting
    connecting = True
    await asyncio.Future()

app = Starlette(routes=[Route('/health', health), Route('/connecting', status),
                       WebSocketRoute('/ws', websocket)])
uvicorn.run(app, host='0.0.0.0', port=8000, log_level='error')
"""


@pytest.mark.integration
@pytest.mark.parametrize("mode", ["async", "sync"])
def test_unmodified_openenv_client(openshell_runtime: Runtime, mode: str) -> None:
    """Health, repeated WebSocket episodes, and close leave no live sandbox."""
    provider = openshell_runtime.provider()
    image = openshell_runtime.image
    messages = ("hello", "hello again", "Unicode echo: café 🌍\nsecond line")

    def assert_health() -> None:
        # Check the actual selected route without a second startup/health wait.
        assert provider.state.base_url is not None
        # Keep proxies disabled while honoring SSL_CERT_FILE for private CAs.
        with httpx.Client(
            trust_env=False, verify=ssl.create_default_context(), timeout=5
        ) as client:
            response = client.get(f"{provider.state.base_url.rstrip('/')}/health")
        assert response.status_code == HTTPStatus.OK
        assert provider.state.ready

    async def run_async() -> None:
        env = await client_factory.from_docker_image(image, provider=provider)
        async with env:
            assert_health()
            episodes: list[str] = []
            for _ in range(2):
                assert not (await env.reset()).done
                before = await env.state()
                assert before["step_count"] == 0
                episodes.append(before["episode_id"])
                for count, message in enumerate(messages, start=1):
                    result = await env.step(
                        {
                            "type": "call_tool",
                            "tool_name": "echo_message",
                            "arguments": {"message": message},
                        }
                    )
                    assert result.observation["result"]["data"] == message
                    assert not result.done
                    assert not result.observation["result"]["is_error"]
                    assert (await env.state())["step_count"] == count
            assert episodes[0] != episodes[1]

    if mode == "async":
        asyncio.run(run_async())
    else:
        env = client_factory.from_docker_image(image, provider=provider).sync()
        with env:
            assert_health()
            episodes: list[str] = []
            for _ in range(2):
                assert not env.reset().done
                before = env.state()
                assert before["step_count"] == 0
                episodes.append(before["episode_id"])
                for count, message in enumerate(messages, start=1):
                    result = env.step(
                        {
                            "type": "call_tool",
                            "tool_name": "echo_message",
                            "arguments": {"message": message},
                        }
                    )
                    assert result.observation["result"]["data"] == message
                    assert not result.done
                    assert not result.observation["result"]["is_error"]
                    assert env.state()["step_count"] == count
            assert episodes[0] != episodes[1]
    # Assert before fallback cleanup so it cannot conceal a client teardown bug.
    assert provider.state.deleted
    assert provider.state.sandbox_name is None
    assert provider.metadata is not None
    assert provider.metadata.ready_at is not None
    assert provider.metadata.deleted_at is not None
    with SandboxClient.from_active_cluster(
        cluster=openshell_runtime.gateway, timeout=30
    ) as client:
        assert not any(
            sandbox.name == provider.config.sandbox_name
            for sandbox in client.list(workspace=openshell_runtime.workspace).all()
        )


@pytest.mark.integration
def test_factory_cancellation_deletes_owned_sandbox(openshell_runtime: Runtime) -> None:
    """A real pending WebSocket handshake is cancelled without fixture cleanup."""
    provider = openshell_runtime.provider(
        command=["/app/env/.venv/bin/python", "-c", PENDING_HANDSHAKE_SERVER]
    )

    async def bootstrap() -> None:
        await client_factory.from_docker_image(
            openshell_runtime.image, provider=provider
        )

    async def run_async() -> None:
        task = asyncio.create_task(bootstrap())
        try:
            async with (
                asyncio.timeout(180),
                httpx.AsyncClient(
                    trust_env=False, verify=ssl.create_default_context(), timeout=2
                ) as client,
            ):
                while provider.state.base_url is None:
                    if task.done():
                        await task
                        pytest.fail("Factory returned before cancellation")
                    await asyncio.sleep(0.05)
                # This request proves the server received the real upgrade.
                # No client, transport, provider, or gateway method is replaced.
                async with asyncio.timeout(5):
                    while True:
                        response = await client.get(
                            f"{provider.state.base_url.rstrip('/')}/connecting"
                        )
                        if response.status_code == HTTPStatus.OK:
                            break
                        assert response.status_code == HTTPStatus.CONFLICT
                        await asyncio.sleep(0.05)
                assert provider.state.created
                assert provider.state.sandbox_id is not None
                task.cancel("factory cancellation")
                with pytest.raises(asyncio.CancelledError) as caught:
                    await task
                assert caught.value.args == ("factory cancellation",)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run_async())
    # Check before fixture teardown: only the unmodified factory may clean up.
    assert provider.state.deleted
    assert provider.state.sandbox_name is None
    assert provider.metadata is not None
    assert provider.metadata.deleted_at is not None
    with SandboxClient.from_active_cluster(
        cluster=openshell_runtime.gateway, timeout=30
    ) as client:
        assert not any(
            sandbox.name == provider.config.sandbox_name
            or sandbox.id == provider.metadata.sandbox_id
            for sandbox in client.list(workspace=openshell_runtime.workspace).all()
        )
