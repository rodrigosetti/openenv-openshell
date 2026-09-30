"""I2 EchoEnv E2E through the unmodified OpenEnv client and owned runtime."""

import asyncio
from http import HTTPStatus

import httpx
import pytest
from openshell import SandboxClient

from tests.integration._runtime import Runtime
from tests.openenv_client import client_factory


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
        with httpx.Client(trust_env=False, timeout=5) as client:
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
