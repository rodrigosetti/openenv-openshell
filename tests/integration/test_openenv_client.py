"""P10 unmodified OpenEnv client through the real local OpenShell service."""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest
from openshell import SandboxClient

from openenv_openshell import OpenShellProvider
from tests.integration.test_protocol_spike import COMMAND
from tests.openenv_client import client_factory


@pytest.mark.integration
@pytest.mark.parametrize("mode", ["async", "sync"])
def test_unmodified_openenv_client(mode: str) -> None:
    """Factory health, WebSocket episodes, and client close use the public provider."""
    image = os.environ.get("OPENENV_OPENSHELL_ECHO_IMAGE_ID")
    if image is None:
        pytest.skip("Set OPENENV_OPENSHELL_ECHO_IMAGE_ID to the validated image ID")
    workspace = os.environ.get("OPENSHELL_WORKSPACE", "default")
    name = f"oe-p10-{uuid4().hex[:8]}"
    provider = OpenShellProvider(
        workspace=workspace,
        sandbox_name=name,
        command=COMMAND,
        policy=Path(__file__).parent / "images/echo/policy.yaml",
        labels={"openenv-p10": name},
    )

    async def run_async() -> None:
        env = await client_factory.from_docker_image(image, provider=provider)
        async with env:
            episodes: list[str] = []
            for _ in range(2):
                assert not (await env.reset()).done
                before = await env.state()
                assert before["step_count"] == 0
                episodes.append(before["episode_id"])
                for count, message in enumerate(("hello", "hello again"), start=1):
                    result = await env.step(
                        {
                            "type": "call_tool",
                            "tool_name": "echo_message",
                            "arguments": {"message": message},
                        }
                    )
                    assert result.observation["result"]["data"] == message
                    assert not result.observation["result"]["is_error"]
                    assert (await env.state())["step_count"] == count
            assert episodes[0] != episodes[1]

    try:
        if mode == "async":
            asyncio.run(run_async())
        else:
            env = client_factory.from_docker_image(image, provider=provider).sync()
            with env:
                episodes: list[str] = []
                for _ in range(2):
                    assert not env.reset().done
                    before = env.state()
                    assert before["step_count"] == 0
                    episodes.append(before["episode_id"])
                    for count, message in enumerate(("hello", "hello again"), start=1):
                        result = env.step(
                            {
                                "type": "call_tool",
                                "tool_name": "echo_message",
                                "arguments": {"message": message},
                            }
                        )
                        assert result.observation["result"]["data"] == message
                        assert not result.observation["result"]["is_error"]
                        assert env.state()["step_count"] == count
                assert episodes[0] != episodes[1]
        # Assert before fallback cleanup so it cannot conceal a client teardown bug.
        assert provider.state.deleted
        assert provider.state.sandbox_name is None
        assert provider.metadata is not None
        assert provider.metadata.ready_at is not None
        assert provider.metadata.deleted_at is not None
        with SandboxClient.from_active_cluster(timeout=30) as client:
            assert not client.list(
                workspace=workspace, label_selector=f"openenv-p10={name}"
            ).all()
    finally:
        provider.stop_container()
